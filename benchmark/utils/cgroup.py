# coding: UTF-8

import asyncio
import getpass
import grp
import os
import shlex
from typing import Iterable, Optional, Set

import aiofiles

from .hyphen import convert_to_set


class Cgroup:
    CPUSET_MOUNT_POINT = '/sys/fs/cgroup/cpuset'
    CPU_MOUNT_POINT = '/sys/fs/cgroup/cpu'
    MEMORY_MOUNT_POINT = '/sys/fs/cgroup/memory'

    def __init__(self, group_name: str, controllers: str) -> None:
        self._group_name: str = group_name
        self._controllers: str = controllers
        self._group_path: str = f'{controllers}:{group_name}'

    async def create_group(self) -> None:
        uname: str = getpass.getuser()
        gid: int = os.getegid()
        gname: str = grp.getgrgid(gid).gr_name

        proc = await asyncio.create_subprocess_exec(
                'sudo', 'cgcreate', '-a', f'{uname}:{gname}', '-d', '700', '-f',
                '600', '-t', f'{uname}:{gname}', '-s', '600', '-g', self._group_path)
        await proc.communicate()

    async def exec_command(self, command: str, **kwargs) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
                'cgexec', '--sticky', '-g', self._group_path, *shlex.split(command), **kwargs)

    async def rename(self, new_group_name) -> None:
        proc = await asyncio.create_subprocess_exec(
                'sudo', 'mv', f'{Cgroup.CPUSET_MOUNT_POINT}/{self._group_name}',
                f'{Cgroup.CPUSET_MOUNT_POINT}/{new_group_name}'
        )
        await proc.communicate()

        proc = await asyncio.create_subprocess_exec(
                'sudo', 'mv', f'{Cgroup.CPU_MOUNT_POINT}/{self._group_name}',
                f'{Cgroup.CPU_MOUNT_POINT}/{new_group_name}'
        )
        await proc.communicate()

        proc = await asyncio.create_subprocess_exec(
            'sudo', 'mv', f'{Cgroup.MEMORY_MOUNT_POINT}/{self._group_name}',
            f'{Cgroup.MEMORY_MOUNT_POINT}/{new_group_name}'
        )
        await proc.communicate()

        self._group_name = new_group_name
        self._group_path = f'{self._controllers}:{self._group_name}'

    async def assign_cpus(self, core_ids: str) -> None:
        proc = await asyncio.create_subprocess_exec('cgset', '-r', f'cpuset.cpus={core_ids}', self._group_name)
        await proc.communicate()

    async def assign_mems(self, socket_ids: str) -> None:
        proc = await asyncio.create_subprocess_exec('cgset', '-r', f'cpuset.mems={socket_ids}', self._group_name)
        await proc.communicate()

    async def _get_cpu_affinity_from_group(self) -> Set[int]:
        async with aiofiles.open(f'{Cgroup.CPUSET_MOUNT_POINT}/{self._group_name}/cpuset.cpus') as afp:
            line: str = await afp.readline()
            core_set: Set[int] = convert_to_set(line)
        return core_set

    async def limit_cpu_quota(self, limit_percentage: float, period: Optional[int] = None) -> None:
        if period is None:
            async with aiofiles.open(f'{Cgroup.CPU_MOUNT_POINT}/cpu.cfs_period_us') as afp:
                line: str = await afp.readline()
                period = int(line)

        cpu_cores = await self._get_cpu_affinity_from_group()
        quota = int(period * limit_percentage / 100 * len(cpu_cores))
        quota_proc = await asyncio.create_subprocess_exec('cgset', '-r', f'cpu.cfs_quota_us={quota}',
                                                          self._group_name)
        await quota_proc.communicate()
        period_proc = await asyncio.create_subprocess_exec('cgset', '-r', f'cpu.cfs_period_us={period}',
                                                           self._group_name)
        await period_proc.communicate()

    async def limit_memory_percent(self, limit_percentage: float) -> None:
        limit_bytes = int(limit_percentage * 32 * 1024 * 1024 * 1024)
        proc = await asyncio.create_subprocess_exec('cgset', '-r', f'memory.limit_in_bytes={limit_bytes}'
                                                    , self._group_name)
        await proc.communicate()

    async def add_tasks(self, pids: Iterable[int]) -> None:
        proc = await asyncio.create_subprocess_exec('cgclassify', '-g', self._group_path, '--sticky', *map(str, pids))
        await proc.communicate()

    async def delete(self) -> None:
        proc = await asyncio.create_subprocess_exec('sudo', 'cgdelete', '-r', '-g', self._group_path)
        await proc.communicate()

