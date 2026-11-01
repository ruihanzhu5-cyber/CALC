"""Pinned MANTA WorkBench adapter; actor inputs exclude task metadata and targets."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

from calc.benchmarks.session import EvaluationSession

PIN = '3da40879d690a25459cc401292e5c6f0cc366d84'
CONTEXT = ("Today's date is Thursday, 2023-11-30 and the current time is 00:00:00. "
           "Meetings must not start before 9am or end after 6pm. Use workplace tools to complete the task. "
           "After using tools, provide a brief natural-language confirmation. All tools act on a local sandbox. ")


def load_benchmark(repo: Path, data: Path):
    commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != PIN:
        raise ValueError(f'expected pinned MANTA commit {PIN}')
    if subprocess.call(['git', '-c', 'core.autocrlf=true', '-c', 'core.filemode=false',
                        '-C', str(repo), 'diff', '--quiet', 'HEAD']):
        raise ValueError('pinned MANTA tracked files have local modifications')
    sys.path.insert(0, str(repo.resolve()))
    from benchmark.workbench import WorkBenchBenchmark, WorkBenchSandbox, DATA_FILES, QUERY_FILE_NAMES
    from benchmark.workbench import _format_function_call
    files = [*DATA_FILES, *[f'data/processed/tasks_and_outcomes/v1/{f}' for f in QUERY_FILE_NAMES.values()]]
    missing = [f for f in files if not (data / f).is_file()]
    if missing:
        raise FileNotFoundError(f'local assets missing (no auto-download): {missing}')
    benchmark = WorkBenchBenchmark({'data_dir': str(data), 'domain': 'multi_domain',
                                    'tasks_version': 'v1', 'tool_selection': 'domains'})
    hashes = {f: hashlib.sha256((data / f).read_bytes()).hexdigest() for f in files}
    return benchmark, WorkBenchSandbox, _format_function_call, hashes


class WorkBenchAdapter:
    def __init__(self, benchmark, sandbox_type, format_call, data: Path, task):
        self._benchmark, self._task, self._format_call = benchmark, task, format_call
        self.sandbox = sandbox_type(data)
        tools = benchmark._build_tools(self.sandbox, list(task.metadata['domains']))
        self._mapping = {t['name'].replace('.', '__'): t for t in tools}
        if len(self._mapping) != len(tools):
            raise ValueError('tool name normalization collision')
        self.tools = [{'type': 'function', 'function': {'name': name,
            'description': t['description'], 'parameters': t['parameters']}}
            for name, t in self._mapping.items()]
        self.instruction, self.actions = str(task.prompt), []

    def invoke(self, name, arguments):
        tool = self._mapping[name]
        self.actions.append(self._format_call(tool['name'], arguments))
        return tool['handler'](arguments)

    def evaluate(self, answer):
        return self._benchmark.evaluate(self._task, answer,
            run_metadata={'function_calls': self.actions, 'error': ''})

    def session(self) -> EvaluationSession:
        # This sandbox is in-memory; the pinned implementation has no close hook.
        return EvaluationSession(tools=self.tools, invoke=self.invoke, context=CONTEXT,
                                 evaluate=self.evaluate, close=None)
