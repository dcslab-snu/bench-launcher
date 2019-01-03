#!/usr/bin/env python3.6
# coding: UTF-8

import argparse
import asyncio
import contextlib
import glob
import importlib
import json
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Coroutine, Dict, Generator, List, Optional, Set, Tuple, Union

import aiofiles

from benchmark.benchmark import Benchmark
from containers.bench_config import BenchConfig
from containers.launcher_config import LauncherConfig
from containers.perf_config import PerfConfig, PerfEvent
from containers.rabbit_mq_config import RabbitMQConfig


def parse_workload_cfg(wl_configs: List[Dict[str, Any]]) -> Tuple[BenchConfig, ...]:
    return tuple(
            BenchConfig(config['name'],
                        config.get('type', 'bg'),
                        config['binding_cores'],
                        config.get('num_of_threads', None),
                        config.get('numa_nodes', None),
                        config.get('cpu_freq', None),
                        config.get('cpu_percent', None),
                        config.get('cbm_ranges', None))
            for config in wl_configs
    )


def parse_perf_cfg(global_cfg: Dict[str, Any], local_cfg: Optional[Dict[str, Any]]) -> PerfConfig:
    events = tuple(
            PerfEvent(elem, elem)
            if type(elem) is str else
            PerfEvent(elem['event'], elem['alias'])
            for elem in global_cfg['events'] + local_cfg['extra_events']
    )

    return PerfConfig(global_cfg['interval'], events)


def parse_rabbit_mq_cfg(rabbit_cfg: Dict[str, Any]) -> RabbitMQConfig:
    return RabbitMQConfig(rabbit_cfg['host'], rabbit_cfg['queue_name']['workload_creation'])


def parse_launcher_cfg(launcher_cfg: Optional[Dict[str, Union[bool, List[str]]]]) -> LauncherConfig:
    if launcher_cfg is None:
        return LauncherConfig([], False, False)

    cwd = Path(__file__).parent
    post_scripts = cwd / 'post_scripts'

    postscripts: List[Path] = []

    for script in launcher_cfg.get('post_scripts', []):
        script_path = post_scripts / script

        if not script_path.exists():
            raise FileNotFoundError(f'post script {script_path} is not exist')
        elif not script_path.is_file():
            raise ValueError(f'post script {script_path} is not a file')

        postscripts.append(Path('post_scripts') / script)

    return LauncherConfig(postscripts,
                          launcher_cfg.get('hyper-threading', False),
                          launcher_cfg.get('stops_with_the_first', False))


def create_benchmarks(bench_cfgs: Tuple[BenchConfig, ...],
                      perf_cfg: PerfConfig,
                      rabbit_cfg: RabbitMQConfig,
                      work_space: Path,
                      is_verbose: bool) -> Generator[Benchmark, Any, None]:
    bench_dict: Dict[str, List[BenchConfig]] = dict()

    for bench in bench_cfgs:
        if bench.name not in bench_dict:
            bench_dict[bench.name] = []
        bench_dict[bench.name].append(bench)

    return (
        Benchmark(BenchConfig.gen_identifier(bench_cfg, bench_dict[bench_cfg.name]),
                  bench_cfg, perf_cfg, rabbit_cfg, work_space, logging.DEBUG if is_verbose else logging.INFO)
        for bench_cfg in bench_cfgs
    )


_ENERGY_FILE_NAME = 'energy_uj'
_MAX_ENERGY_VALUE_FILE_NAME = 'max_energy_range_uj'


@contextlib.contextmanager
def power_monitor(work_space: Path):
    """
    Saves power consumption to `work_space`/result.json when exit `with` scope.

    Example:
    ::
        with power_monitor(Path('experiment_1')):
            # run benchmark and join

    :param work_space: parent directory of result.json
    """
    base_dir = Path('/sys/class/powercap/intel-rapl')

    monitors: Dict[Path, Tuple[int, Dict[Path, int]]] = dict()

    while True:
        socket_id = len(monitors)
        socket_monitor: Path = base_dir / f'intel-rapl:{socket_id}'

        if socket_monitor.exists():
            with (socket_monitor / _ENERGY_FILE_NAME).open() as fp:
                socket_power = int(fp.readline())

            socket_dict: Dict[Path, int] = dict()
            monitors[socket_monitor] = (socket_power, socket_dict)

            while True:
                sub_id = len(socket_dict)
                sub_monitor = socket_monitor / f'intel-rapl:{socket_id}:{sub_id}'

                if sub_monitor.exists():
                    with (sub_monitor / _ENERGY_FILE_NAME).open() as fp:
                        before = int(fp.readline())
                        socket_dict[sub_monitor] = before
                else:
                    break
        else:
            break

    yield

    ret: List[Dict[str, Union[str, int, Dict[str, int]]]] = list()

    for socket_path, (prev_socket_power, socket) in monitors.items():
        with (socket_path / 'name').open() as name_fp, (socket_path / _ENERGY_FILE_NAME).open() as power_fp:
            sub_name = name_fp.readline().strip()
            after = int(power_fp.readline())

        if after > prev_socket_power:
            diff = after - prev_socket_power
        else:
            with (socket_path / _MAX_ENERGY_VALUE_FILE_NAME).open() as fp:
                max_value = int(fp.readline())
                diff = max_value - prev_socket_power + after

        ret_dict: Dict[str, Union[str, int, Dict[str, int]]] = {
            'package_name': sub_name,
            'power': diff,
            'domains': dict()
        }

        for path, before in socket.items():
            with (path / _ENERGY_FILE_NAME).open() as energy_fp, (path / 'name').open() as name_fp:
                after = int(energy_fp.readline())
                name = name_fp.readline().strip()

                if after > prev_socket_power:
                    diff = after - before
                else:
                    with (path / _MAX_ENERGY_VALUE_FILE_NAME).open() as fp:
                        max_value = int(fp.readline())
                        diff = max_value - before + after

                ret_dict['domains'][name] = diff

        ret.append(ret_dict)

    result_file = work_space / 'result.json'
    if result_file.exists():
        with result_file.open('r+') as fp:
            try:
                original = json.load(fp)
                original['power'] = ret

                fp.seek(0)
                json.dump(original, fp, indent=4)

            except json.decoder.JSONDecodeError:
                fp.seek(0)
                fp.truncate()
                json.dump({'power': ret}, fp, indent=4)
    else:
        with result_file.open('w') as fp:
            json.dump({'power': ret}, fp, indent=4)


@contextlib.contextmanager
def hyper_threading_guard(loop: asyncio.AbstractEventLoop, ht_flag):
    async def _gather_online_core(online_file: Path, core_id: int):
        if online_file.is_file():
            async with aiofiles.open(online_file) as afp:
                line = await afp.readline()
                if line.strip() == '1':
                    return core_id

    jobs: List[Coroutine] = []

    cur_core_id = 1
    while True:
        path = Path(f'/sys/devices/system/cpu/cpu{cur_core_id}')

        if not path.is_dir():
            break

        else:
            jobs.append(_gather_online_core(path / 'online', cur_core_id))

        cur_core_id += 1

    online_core: Set[int] = set(filter(None.__ne__, loop.run_until_complete(asyncio.gather(*jobs))))

    if not ht_flag:
        print('disabling Hyper-Threading...')

        logical_cores: Set[int] = set()

        for cur_core_id in online_core | {0}:
            with open(f'/sys/devices/system/cpu/cpu{cur_core_id}/topology/thread_siblings_list') as fp:
                for core in fp.readline().strip().split(',')[1:]:
                    logical_cores.add(int(core))

        files_to_write = ('/sys/devices/system/cpu/cpu{}/online'.format(core_id) for core_id in logical_cores)
        subprocess.run(('sudo', 'tee', *files_to_write), input="0", encoding='UTF-8', stdout=subprocess.DEVNULL)

        print('Hyper-Threading is disabled.')

    yield

    files_to_write = ('/sys/devices/system/cpu/cpu{}/online'.format(core_id) for core_id in online_core)

    subprocess.run(('sudo', 'tee', *files_to_write), input="1", encoding='UTF-8', stdout=subprocess.DEVNULL)


GLOBAL_CFG_PATH: Path = Path(__file__).resolve().parent / 'config.json'


def launch(loop: asyncio.AbstractEventLoop, workspace: Path, print_log: bool, print_metric_log: bool, verbose: bool):
    config_file = workspace / 'config.json'

    if not workspace.exists():
        print(f'{workspace.resolve()} is not exist.', file=sys.stderr)
        return False
    elif not config_file.exists():
        print(f'{config_file.resolve()} is not exist.', file=sys.stderr)
        return False

    with config_file.open() as local_config_fp, \
            GLOBAL_CFG_PATH.open() as global_config_fp:
        local_cfg_source: Dict[str, Any] = json.load(local_config_fp)
        global_cfg_source: Dict[str, Any] = json.load(global_config_fp)

        bench_cfgs = parse_workload_cfg(local_cfg_source['workloads'])
        perf_cfg = parse_perf_cfg(global_cfg_source['perf'], local_cfg_source.get('perf', {'extra_events': []}))
        rabbit_cfg = parse_rabbit_mq_cfg(global_cfg_source['rabbitMQ'])
        launcher_cfg = parse_launcher_cfg(local_cfg_source.get('launcher'))

    task_map: Dict[asyncio.Task, Benchmark] = dict()

    was_successful = True

    result_file = workspace / 'result.json'
    if result_file.exists():
        result_file.unlink()

    def stop_all():
        print('force stop all tasks...', file=sys.stderr)

        for a_task in task_map:
            if not a_task.done():
                a_task.cancel()

        nonlocal was_successful
        was_successful = False

    def store_runtime(a_task: asyncio.Task):
        a_bench = task_map[a_task]

        if result_file.exists():
            with result_file.open('r+') as fp:
                try:
                    original: Dict[str, Any] = json.load(fp)

                    if 'runtime' in original:
                        original['runtime'][a_bench.identifier] = a_bench.runtime
                    else:
                        original['runtime'] = {a_bench.identifier: a_bench.runtime}

                    fp.seek(0)
                    json.dump(original, fp, indent=4)

                except json.decoder.JSONDecodeError:
                    fp.seek(0)
                    fp.truncate()
                    json.dump({'runtime': {a_bench.identifier: a_bench.runtime}}, fp, indent=4)
        else:
            with result_file.open('w') as fp:
                json.dump({'runtime': {a_bench.identifier: a_bench.runtime}}, fp, indent=4)

        a_task.remove_done_callback(store_runtime)

    benches = tuple(create_benchmarks(bench_cfgs, perf_cfg, rabbit_cfg, workspace, verbose))

    loop.add_signal_handler(signal.SIGHUP, stop_all)
    loop.add_signal_handler(signal.SIGTERM, stop_all)
    loop.add_signal_handler(signal.SIGINT, stop_all)

    with power_monitor(workspace), hyper_threading_guard(loop, launcher_cfg.hyper_threading):
        # invoke benchmark loaders in parallel and wait for launching actual benchmarks
        loop.run_until_complete(asyncio.wait(tuple(bench.start_and_pause(print_log) for bench in benches)))

        for bench in benches:
            bench.resume()

        for bench in benches:
            task: asyncio.Task = loop.create_task(bench.monitor(print_metric_log))
            task.add_done_callback(store_runtime)
            task_map[task] = bench

        # start monitoring
        return_when = asyncio.FIRST_COMPLETED if launcher_cfg.stops_with_the_first else asyncio.ALL_COMPLETED
        finished, unfinished = loop.run_until_complete(asyncio.wait(task_map.keys(), return_when=return_when))

        for task in unfinished:
            task.cancel()

        loop.run_until_complete(asyncio.gather(*unfinished))

    loop.remove_signal_handler(signal.SIGHUP)
    loop.remove_signal_handler(signal.SIGTERM)
    loop.remove_signal_handler(signal.SIGINT)

    # run post scripts
    for script in launcher_cfg.post_scripts:
        name = str(script)
        if name.endswith('.py'):
            name = name[:-3]
        script_module = importlib.import_module(name.replace('/', '.'))
        script_module.run(workspace, GLOBAL_CFG_PATH)

    return was_successful


def main():
    parser = argparse.ArgumentParser(description='Launch benchmark written in config file.')
    parser.add_argument('config_dir', metavar='PARENT_DIR_OF_CONFIG_FILE', type=str, nargs='+',
                        help='Directory path where the config file (config.json) exist. (support wildcard *)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Print more detail log')
    parser.add_argument('-L', '--print-log', action='store_true', help='Print all logs to stdout. (implies -M)')
    parser.add_argument('-M', '--print-metric-log', action='store_true',
                        help='Print all metric related logs to stdout.')
    args = parser.parse_args()

    dirs = list()

    for path in args.config_dir:  # type: str
        if not path.endswith('/'):
            path += '/'

        dirs += glob.glob(path)

    loop = asyncio.get_event_loop()
    try:
        print_log = args.print_log
        print_metric_log = args.print_metric_log

        for i, workspace in enumerate(dirs):
            if i is not 0:
                time.sleep(10)

            if not launch(loop, Path(workspace), print_log, print_metric_log, args.verbose):
                break

    finally:
        loop.stop()
        loop.close()


if __name__ == '__main__':
    main()
