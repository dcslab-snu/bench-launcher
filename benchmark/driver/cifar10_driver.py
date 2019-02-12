# coding: UTF-8

import asyncio
from typing import Optional, Set

import psutil

from benchmark.driver.base_driver import BenchDriver


class Cifar10Driver(BenchDriver):
    _benches: Set[str] = {'cifar10_train', 'cifar10_eval'}
    bench_name: str = 'cifar10'
    _bench_home: str = BenchDriver.get_bench_home(bench_name)

    @staticmethod
    def has(bench_name: str) -> bool:
        return bench_name in Cifar10Driver._benches

    def _find_bench_proc(self) -> Optional[psutil.Process]:
        if self._name == 'raytrace':
            exec_name = 'rtview'
        else:
            exec_name = self._name

        for process in self._async_proc_info.children(recursive=True):  # type: psutil.Process
            if process.name() == exec_name and process.is_running():
                return process

        return None

    async def _launch_bench(self) -> asyncio.subprocess.Process:
        cmd = '{0}/parsecmgmt -a run -p {1} -i native -n {2}' \
            .format(self._bench_home, self._name, self._num_threads)

        return await self._cgroup.exec_command(cmd, stdout=asyncio.subprocess.DEVNULL)
