#!/usr/bin/env python3
# coding: UTF-8

import sys
from pathlib import Path
from typing import List

from post_scripts.tools import WorkloadResult, read_result


def run(workspace: Path, global_cfg_path: Path):
    results: List[WorkloadResult] = read_result(workspace)

    error_file = workspace / 'ERROR'
    if error_file.exists():
        error_file.unlink()

    for result in results:
        if 0 in result.metrics.get('llc_occupancy'):
            print(f'{result.name} has 0 llc_occupancy value!', file=sys.stderr)

            if not error_file.exists():
                with error_file.open('w') as fp:
                    fp.write(result.name)
            else:
                with error_file.open('a') as fp:
                    fp.write(result.name)
