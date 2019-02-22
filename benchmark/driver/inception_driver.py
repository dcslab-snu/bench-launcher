# coding: UTF-8

import asyncio
from typing import Optional, Set

import psutil

from benchmark.driver.base_driver import BenchDriver


class InceptionDriver(BenchDriver):
    _benches: Set[str] = {'imagenet_train', 'imagenet_eval'}
    bench_name: str = 'inception'
    _bench_home: str = BenchDriver.get_bench_home(bench_name)

    @staticmethod
    def has(bench_name: str) -> bool:
        return bench_name in InceptionDriver._benches

    def _find_bench_proc(self) -> Optional[psutil.Process]:

        cmdline = self._async_proc_info.cmdline()
        exec_cmdline = cmdline[1]
        cmdline_list = exec_cmdline.split('/')
        exec_name = cmdline_list[len(cmdline_list)-1].rstrip('.py')
        """
        print(f'[_find_bench_proc] self._name: {self._name}')
        print(f'[_find_bench_proc] self._async_proc_info.name(): {self._async_proc_info.name()}')
        print(f'[_find_bench_proc] self._async_proc_info.cmdline(): {self._async_proc_info.cmdline()}')
        print(f'[_find_bench_proc] exec_name: {exec_name}')
        """
        if self._name in exec_name and self._async_proc_info.is_running():
            return self._async_proc_info

    async def _launch_bench(self) -> asyncio.subprocess.Process:
        if 'train' in self._name:
            args = '--max_steps 5 --data_dir /ssd2/converted_data'
            cmd = '{0}/{1} {2}' \
                .format(self._bench_home, self._name, args)
        elif 'eval' in self._name:
            args = '--num_examples 800 --run_once --data_dir /ssd2/converted_data --checkpoint_dir /tmp/imagenet_train_for_eval'
            cmd = '{0}/{1} {2}' \
                .format(self._bench_home, self._name, args)

        return await self._cgroup.exec_command(cmd, stdout=asyncio.subprocess.DEVNULL)
