# coding: UTF-8

from typing import List, Optional, Union

from benchmark.driver.base_driver import BenchDriver, bench_driver


class BenchConfig:
    def __init__(self, workload_name: str, workload_type: str, binding_cores: str, num_of_threads: int = None,
                 numa_mem_nodes: str = None, cpu_freq: float = None, cycle_limit: float = None,
                 cycle_limit_period: int = None, cbm_ranges: Union[str, List[str]] = None):
        self._workload_name: str = workload_name
        self._workload_type: str = workload_type
        self._binding_cores: str = binding_cores
        self._num_of_threads: Optional[int] = num_of_threads
        self._numa_mem_nodes: Optional[str] = numa_mem_nodes
        self._cpu_freq: Optional[float] = cpu_freq
        self._cycle_limit: Optional[float] = cycle_limit
        self._cycle_limit_period: Optional[int] = cycle_limit_period
        self._cbm_ranges: Optional[Union[str, List[str]]] = cbm_ranges

    @property
    def name(self) -> str:
        return self._workload_name

    @property
    def workload_type(self) -> str:
        return self._workload_type

    @property
    def binding_cores(self) -> str:
        return self._binding_cores

    @property
    def num_of_threads(self) -> Optional[int]:
        return self._num_of_threads

    @property
    def numa_nodes(self) -> Optional[str]:
        return self._numa_mem_nodes

    @property
    def cpu_freq(self) -> Optional[float]:
        return self._cpu_freq

    @property
    def cycle_limit(self) -> Optional[float]:
        return self._cycle_limit

    @property
    def cycle_limit_period(self) -> Optional[int]:
        return self._cycle_limit_period

    @property
    def cbm_ranges(self) -> Optional[Union[str, List[str]]]:
        return self._cbm_ranges

    def generate_driver(self, identifier: str) -> BenchDriver:
        return bench_driver(self._workload_name, self._workload_type, identifier, self._binding_cores,
                            self._num_of_threads, self._numa_mem_nodes, self._cpu_freq, self._cycle_limit,
                            self._cbm_ranges)

    @staticmethod
    def gen_identifier(target: 'BenchConfig', configs: List['BenchConfig']) -> str:
        type_same = True
        threads_same = True
        cores_same = True
        numa_same = True
        freq_same = True
        percent_same = True
        cbm_same = True

        index_in_same_cfg = None
        num_of_same_cfg = 0

        for config in configs:
            _all_same = True

            if target._workload_type != config._workload_type:
                _all_same = type_same = False
            if target._num_of_threads != config._num_of_threads:
                _all_same = threads_same = False
            if target._binding_cores != config._binding_cores:
                _all_same = cores_same = False
            if target._numa_mem_nodes != config._numa_mem_nodes:
                _all_same = numa_same = False
            if target._cpu_freq != config._cpu_freq:
                _all_same = freq_same = False
            if target._cycle_limit != config._cycle_limit:
                _all_same = percent_same = False
            if target.cbm_ranges != config._cbm_ranges:
                _all_same = cbm_same = False

            if _all_same:
                if target is config:
                    index_in_same_cfg = num_of_same_cfg
                else:
                    num_of_same_cfg += 1

        names: List[str] = [target.name]

        if not type_same:
            names.append(f'{target.workload_type}')
        if not threads_same:
            names.append(f'{target.num_of_threads}threads')
        if not cores_same:
            names.append(f'core({target.binding_cores})')
        if not numa_same:
            names.append(f'socket({target.numa_nodes})')
        if not freq_same:
            names.append(f'{target.cpu_freq}GHz')
        if not percent_same:
                names.append(f'{target.cycle_limit}GHz')
        if not cbm_same:
            names.append(f'cbm{target.cbm_ranges}')
        if num_of_same_cfg is not 0:
            names.append(str(index_in_same_cfg))

        return '_'.join(names)
