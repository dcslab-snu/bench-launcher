#!/usr/bin/env python3
# coding: UTF-8

import csv
from collections import OrderedDict
from functools import reduce
from pathlib import Path
from statistics import mean
from typing import List

from orderedset import OrderedSet

from post_scripts.tools import WorkloadResult, read_result


def run(workspace: Path, global_cfg_path: Path):
    results: List[WorkloadResult] = read_result(workspace)
    output_path = workspace / 'output'

    if not output_path.exists():
        output_path.mkdir(parents=True)

    categories: OrderedSet = reduce(lambda a, b: a | b, map(lambda x: OrderedSet(x.metrics.keys()), results))
    fields = tuple(map(lambda x: x.name, results))
    with (output_path / 'avg.csv').open('w') as fp:
        csv_writer = csv.DictWriter(fp, ('category', *fields))
        csv_writer.writeheader()

        runtime_dict = OrderedDict({'category': 'runtime'})
        for workload in results:
            runtime_dict[workload.name] = workload.runtime
        csv_writer.writerow(runtime_dict)

        for category in categories:
            row_dict = OrderedDict({'category': category})

            for workload in results:
                row_dict[workload.name] = mean(workload.metrics[category])

            csv_writer.writerow(row_dict)
