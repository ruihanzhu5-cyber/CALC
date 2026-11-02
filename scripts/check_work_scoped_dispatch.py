"""Scripted models + real WorkBench: scoped dispatch, retained Main, deferred schemas.

This checks execution plumbing, never claims model quality or a solved task.
No API credentials or network model client is constructed.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from calc.benchmarks.workbench import load_benchmark, WorkBenchAdapter
from calc.benchmarks.session import adaptive_runtime
from calc.llm import ChatResponse, Usage


NAME = 'company_directory__find_email_address'


def call(name, arguments):
    return ChatResponse({'role': 'assistant', 'content': None, 'tool_calls': [{
        'id': 'check1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]},
        'tool_calls', Usage(), 0)


class Scripted:
    model = 'offline-contract-check'

    def __init__(self, main):
        self.main, self.step, self.schemas = main, 0, []

    def complete(self, messages, **kwargs):
        self.schemas.append([t['function']['name'] for t in kwargs['tools']])
        system = messages[0]['content']
        states = json.loads(system.split('Current team state: ')[1].split('\n')[0])
        actor_id = 'main' if self.main else 'agent_1'
        actor = next(a for a in states if a['id'] == actor_id)
        self.step += 1
        if self.main and self.step == 1:
            work = dict(actor['work'])
            work.update(current_scope='Read directory for Sam', completion_condition='Directory read returned',
                        next_step='Load directory schema and read Sam')
            return call('collaborate', {'operation': 'delegate', 'reason': 'Independent named directory lookup',
                'event_type': 'task_start', 'event_version': actor['event_version'], 'progress': actor['work'],
                'evidence_ids': [], 'baseline_next': 'Main reads both names',
                'proposed_next': 'Main reads Sam; worker reads Alex', 'expected_savings': 'Test independent ownership',
                'risks': 'No measured benefit; read-only plumbing', 'handoff': 'Read only assigned name',
                'pattern': 'parallel', 'retained_work': work,
                'branches': [{'goal': 'Read directory for Alex', 'tools': [NAME],
                              'completion_condition': 'Directory read returned'}]})
        offset = 1 if self.main else 0
        if self.step == offset + 1:
            return call('load_tools', {'names': [NAME]})
        if self.step == offset + 2:
            return call(NAME, {'name': 'Sam' if self.main else 'Alex'})
        return ChatResponse({'role': 'assistant', 'content': 'Assigned read complete'}, 'stop', Usage(), 0)


def main():
    repo = Path('D:/CALC-experiments/upstreams/MANTA-native')
    data = Path('D:/CALC-experiments/data/workbench')
    benchmark, sandbox_type, format_call, _ = load_benchmark(repo, data)
    task = benchmark.load_tasks()[0]
    adapter = WorkBenchAdapter(benchmark, sandbox_type, format_call, data, task)
    strong, weak = Scripted(True), Scripted(False)
    with_session = adapter.session()
    try:
        rt = adaptive_runtime(with_session.actor_environment(), strong=strong, weak=weak,
            options={'tool_loading': 'deferred', 'concurrency': 2})
        result = rt.run(adapter.instruction)
        with_session.finish()
        evaluation = with_session.evaluate(result['answer'])
    finally:
        with_session.close()
    assert result['status'] == 'answered'
    reads = [e for e in result['events'] if e['event'] == 'tool_result']
    assert [e['agent'] for e in reads] == ['main', 'agent_1']
    assert result['metrics']['progress_protocol_errors'] == 0
    assert NAME not in strong.schemas[0] and NAME not in weak.schemas[0]
    assert NAME in strong.schemas[2] and NAME in weak.schemas[1]
    assert evaluation.success is False
    print(json.dumps({'check': 'passed', 'model_api_calls': 0,
        'real_environment_reads': len(reads), 'retained_main_executed': True,
        'deferred_schema_visible_on_next_request': True, 'task_success': False,
        'note': 'scripted interface check, not a model benchmark result'}, indent=2))


if __name__ == '__main__':
    main()
