"""Scripted decisions verify contracts, not model quality or benchmark accuracy."""
import copy
import json

import pytest

from calc.adaptive import AdaptiveRuntime, function
from calc.llm import ChatResponse, Usage
from calc.progress import collection_facts


def batch(*calls, answer=None):
    message = {'role': 'assistant', 'content': answer}
    if calls:
        message['tool_calls'] = [{'id': f'c{i}', 'type': 'function', 'function':
            {'name': n, 'arguments': json.dumps(a)}} for i, (n, a) in enumerate(calls)]
    return ChatResponse(message, 'tool_calls' if calls else 'stop',
                        Usage.from_response({'prompt_tokens': 10, 'completion_tokens': 5}), 0)


class Scripted:
    model = 'scripted-contract-test'

    def __init__(self, items):
        self.items = iter(items)
        self.received = []

    def complete(self, messages, **kwargs):
        self.received.append(copy.deepcopy(messages))
        action = next(self.items)
        return action(messages) if callable(action) else action


def report_args(actor, **kwargs):
    return {'report_id': f'p{len(actor.progress_reports)}', 'summary': 'Known facts inspected',
            'next_step': 'Current owner checks the remaining source', 'evidence_ids': list(actor.evidence),
            'reason': 'A direct tool handles the remaining lookup', **kwargs}


def assessed(*calls, decision='continue', answer=None, **extra):
    def respond(messages):
        system = messages[0]['content']
        who = system.split('You are ')[1].split('.')[0]
        state = json.loads(system.split('Current team state: ')[1].split('\n')[0])
        actor = next(a for a in state if a['id'] == who)
        p = {'report_id': f'p{actor["event_version"]}', 'summary': 'Updated from current observations',
             'next_step': 'Current owner checks the remaining source', 'evidence_ids': actor['evidence_ids'],
             'reason': 'Independent work benefits from delegation' if decision == 'change' else 'Direct continuation is sufficient', **extra}
        if answer:
            p['answer'] = answer
        selected = []
        for name, args in calls:
            if name == 'collaborate' and args.get('operation') not in {'respond', 'wait'}:
                args = {'progress_ref': p['report_id'], 'reason': 'Distinct remaining work',
                        'proposed_next': 'Receiver performs remaining work', 'expected_savings': 'Less duplicated context',
                        'risks': 'May lose independent context', **args}
            selected.append((name, args))
        return batch(('report_progress', p), *selected)
    return respond


def runtime(strong=(), weak=(), **kw):
    return AdaptiveRuntime(strong=Scripted(strong), weak=Scripted(weak),
        tools=[function('read', 'read objects', {}, [])], invoke=kw.pop('invoke', lambda n, a: {'value': 1}), **kw)


def test_trivial_task_assesses_and_answers_in_one_normal_request():
    r = runtime([assessed(answer='answer')]).run('small request')
    assert r['answer'] == 'answer' and r['usage']['model_requests'] == 1
    assert r['metrics']['task_state_updates'] == 1 and len(r['loops']) == 1
    assert r['loops']['main']['work']['progress'].startswith('Local answer submitted')


def test_new_collection_gets_main_checkpoint_without_children_or_extra_judge():
    rt = runtime([assessed(('read', {})), assessed(('read', {})), batch(answer='done')],
                 invoke=lambda n, a: [{'object_id': 1}, {'object_id': 2}])
    r = rt.run('inspect objects')
    assert r['status'] == 'answered' and r['usage']['model_requests'] == 3
    assert r['metrics']['progress_checkpoints'] == 2  # initial + first collection, not every lookup
    assert 'collection_observed' in rt.clients['strong'].received[1][0]['content']
    assert r['metrics']['task_state_updates'] == 2 and len(r['loops']) == 1
    assert r['metrics']['decision_opportunities'] == 0  # no parent wakeups


def test_progress_and_delegation_in_same_call_can_expand_after_inline_work():
    rt = runtime([assessed(('read', {})), assessed(('collaborate', {'operation': 'delegate',
                    'pattern': 'parallel', 'branches': [{'goal': 'A'}, {'goal': 'B'}]}), decision='change'),
                  assessed(answer='combined')],
                 [assessed(answer='A done'), assessed(answer='B done')], concurrency=2,
                 invoke=lambda n, a: [{'id': 'A'}, {'id': 'B'}])
    r = rt.run('task with newly discovered branches')
    assert r['answer'] == 'combined' and r['usage']['model_requests'] == 5
    assert len(r['loops']) == 3 and r['metrics']['switches'] == 1
    assert r['metrics']['progress_protocol_errors'] == 0


def test_optional_report_never_gates_business_tool():
    executed = []
    rt = runtime([batch(('read', {})), assessed(('read', {})), batch(answer='done')],
                 invoke=lambda n, a: executed.append(n) or {'value': 1})
    r = rt.run('task')
    assert executed == ['read', 'read'] and r['usage']['model_requests'] == 3
    assert r['metrics']['progress_protocol_errors'] == 0


def test_business_tool_listed_first_cannot_create_evidence_for_its_report():
    rt = runtime()
    main = rt._new('task', None, 'strong', [])
    p = report_args(main, evidence_ids=['e0'])
    rt._accept(main, batch(('read', {}), ('report_progress', p)), None, [])
    assert len(rt.archive) == 1 and main.progress_reports == {}
    rt._accept(main, batch(('read', {}), ('report_progress', report_args(main))), None, [])
    assert len(rt.archive) == 2 and main.latest_report == 'p0'
    assert main.progress_reports['p0']['evidence_ids'] == ['e0']


def test_multiple_ledger_writes_reject_reports_but_not_business_tool():
    executed = []
    rt = runtime(invoke=lambda n, a: executed.append(n))
    main = rt._new('task', None, 'strong', [])
    p = report_args(main)
    rt._accept(main, batch(('report_progress', p), ('read', {}), ('report_progress', {**p, 'report_id': 'other'})), None, [])
    assert executed == ['read'] and main.latest_report is None
    assert sum(e['event'] == 'progress_report_error' for e in rt.events) == 1


def test_progress_reporting_is_independent_and_ordinary_updates_do_not_wake_parent():
    rt = runtime()
    parent = rt._new('task', None, 'strong', [])
    child = rt._new('child', parent.id, 'weak', [])
    parent.status = 'waiting'
    rt._report_progress(child, report_args(child))
    rt._tool(child, 'read', {})
    rt._report_progress(child, report_args(child, summary='New facts inspected'))
    assert child.work.progress == 'New facts inspected' and parent.status == 'waiting'
    assert parent.notices == []
    rt._report_progress(child, report_args(child, signal='blocked', summary='Missing dependency'))
    assert parent.status == 'ready' and parent.notices[-1]['type'] == 'blocked'


def test_subgoal_dependency_change_assessed_without_changing_topology():
    rt = runtime()
    main = rt._new('task', None, 'strong', [])
    goals = [{'id': 'a', 'goal': 'read A', 'status': 'open', 'dependencies': []},
             {'id': 'b', 'goal': 'read B', 'status': 'open', 'dependencies': ['a']}]
    rt._report_progress(main, report_args(main, subgoals=goals))
    goals[1]['dependencies'] = []
    rt._report_progress(main, report_args(main, subgoals=goals))
    assert len(rt.loops) == 1 and main.checkpoints == {}
    assert len([e for e in rt.events if e['event'] == 'progress_checkpoint' and e['checkpoint']['type'] == 'plan_changed']) == 2


def test_repeated_report_is_idempotent_and_cannot_assess_later_events():
    rt = runtime(invoke=lambda n, a: [{'id': 1}, {'id': 2}])
    main = rt._new('task', None, 'strong', [])
    p = report_args(main)
    rt._report_progress(main, p)
    assert rt._report_progress(main, p)['duplicate'] is True
    rt._tool(main, 'read', {})
    assert rt._report_progress(main, p)['duplicate'] is True
    assert len(main.checkpoints) == 1  # retransmission alone consumes no new event
    rt._accept(main, batch(('report_progress', p), ('read', {})), None, [])
    assert len(rt.archive) == 2 and main.checkpoints == {}


def test_stale_progress_reference_rejects_topology_change():
    rt = runtime()
    main = rt._new('task', None, 'strong', [])
    rt._report_progress(main, report_args(main))
    rt._tool(main, 'read', {})
    with pytest.raises(ValueError, match='stale'):
        rt.change(main.id, {'operation': 'delegate', 'progress_ref': 'p0', 'reason': 'split'})
    assert len(rt.loops) == 1


def test_fold_after_progress_request_transfers_execution_and_checkpoints():
    executed = []
    main = [assessed(('collaborate', {'operation': 'delegate', 'pattern': 'parallel', 'branches': [{'goal': 'inspect'}]}), decision='change'),
            assessed(('collaborate', {'operation': 'respond', 'request_id': 'r0', 'approve': True, 'reason': 'take over'})),
            assessed(('read', {'owner': 'main'})),
            batch(('complete_transferred_work', {'source': 'agent_1', 'result': 'finished'})), batch(answer='done')]
    worker = [assessed(('read', {'owner': 'worker'})),
              assessed(('collaborate', {'operation': 'fold', 'sources': ['agent_1'], 'receiver': 'main'}), decision='change')]
    rt = runtime(main, worker, invoke=lambda n, a: executed.append(a['owner']) or {'value': 1})
    r = rt.run('task')
    assert r['answer'] == 'done' and executed == ['worker', 'main']
    assert rt.loops['agent_1'].status == 'folded' and rt.loops['agent_1'].resolved
    assert r['metrics']['progress_protocol_errors'] == 0
    assert any(e['event'] == 'progress_checkpoint' and e['checkpoint']['type'] == 'work_transferred' for e in rt.events)


@pytest.mark.parametrize('mode', ['single', 'initial_static', 'no_merge_fold', 'full'])
def test_all_modes_share_progress_protocol_without_forced_delegation(mode):
    r = runtime([assessed(answer='answer')], collaboration_mode=mode).run('small task')
    assert r['answer'] == 'answer' and len(r['loops']) == 1


def test_collection_facts_are_order_invariant_and_not_a_semantic_independence_test():
    rows = [{'item_id': 2, 'value': 'coupled'}, {'item_id': 1, 'value': 'coupled'}]
    assert collection_facts(rows) == collection_facts(list(reversed(rows)))
    assert collection_facts('not structured JSON') == []
    assert collection_facts([{'api_name': 'read'}, {'api_name': 'write'}]) == []
    assert collection_facts([{'id': 1}, {'id': 1}]) == []
    assert collection_facts(json.dumps({'results': rows}))[0]['count'] == 2


def test_invalid_plan_is_atomic():
    rt = runtime()
    main = rt._new('task', None, 'strong', [])
    before = copy.deepcopy(main)
    with pytest.raises(ValueError, match='cyclic'):
        rt._report_progress(main, report_args(main, subgoals=[{'id': 'a', 'goal': 'A', 'status': 'open', 'dependencies': ['a']}]))
    assert main == before


def test_concurrent_notice_is_delivered_at_next_request_boundary():
    executed = []
    rt = runtime(invoke=lambda n, a: executed.append(n))
    main = rt._new('task', None, 'strong', [])
    child = rt._new('child', main.id, 'weak', [])
    old = report_args(main)
    request_version = main.version
    seen_checkpoints = list(main.checkpoints)
    rt._notice(main.id, 'dependency_changed', child, {'dependency': 'new'})
    rt._accept(main, batch(('report_progress', old), ('read', {})), None, [], seen_checkpoints, request_version)
    assert main.latest_report == 'p0' and executed == ['read']
    assert main.checkpoints == {} and len(main.inbox) == 1
    rt._deliver_notices(main)
    assert len(main.checkpoints) == 1 and main.inbox == []
    rt._notice(main.id, 'dependency_changed', child, {'dependency': 'new'})
    assert main.inbox == []  # identical notice cannot wake the parent twice
    rt._accept(main, batch(('report_progress', report_args(main)), ('read', {})), None, [])
    assert executed == ['read', 'read'] and main.checkpoints == {}


def test_nested_record_metadata_is_not_a_new_work_collection():
    result = {'song_id': 78, 'artists': [{'id': 1}, {'id': 2}], 'tags': [{'id': 3}, {'id': 4}]}
    assert collection_facts(result) == []
    assert collection_facts({'results': [result, {**result, 'song_id': 36}]})[0]['count'] == 2


def test_correctable_tool_argument_error_does_not_force_reorganization_assessment():
    def invoke(name, args):
        raise ValueError('missing argument')
    rt = runtime(invoke=invoke)
    main = rt._new('task', None, 'strong', [])
    rt._accept(main, batch(('report_progress', report_args(main)), ('read', {})), None, [])
    assert len(main.work.failed_routes) == 1 and main.checkpoints == {}
    assert [e['event'] for e in rt.events].count('tool_error') == 1
