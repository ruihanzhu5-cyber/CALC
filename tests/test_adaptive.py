import copy
import json
import threading
from dataclasses import asdict

import pytest

from calc.adaptive import AdaptiveRuntime, function
from calc.llm import ChatResponse, Usage
from calc.progress import allowed_operations


def response(text='done', tool=None, args=None, finish=None, usage=True):
    message = {'role': 'assistant', 'content': text if tool is None else None}
    if tool:
        message['tool_calls'] = [{'id': 'call1', 'type': 'function', 'function': {
            'name': tool, 'arguments': json.dumps(args or {})}}]
    return ChatResponse(message, finish or ('tool_calls' if tool else 'stop'),
                        Usage.from_response({'prompt_tokens': 5, 'completion_tokens': 2} if usage else None), 0)


def envelope(version, work, **kw):
    return {'operation': 'continue', 'reason': 'test evidence', 'event_type': 'progress',
            'event_version': version, 'progress': work, 'evidence_ids': [],
            'baseline_next': 'current owner performs next lookup', 'proposed_next': 'receiver performs remaining lookup',
            'expected_savings': 'hypothesis: avoid repeated lookup', 'risks': 'may lose independent context',
            'handoff': 'retain evidence and original history', **kw}


def proposal(rt, actor='main', **kw):
    a = rt.loops[actor]
    return envelope(a.version, asdict(a.work), **kw)


def change(**kw):
    def step(messages):
        system = messages[0]['content']
        actor = system.split('You are ')[1].split('.')[0]
        state = json.loads(system.split('Current team state: ')[1].split('\n')[0])
        a = next(a for a in state if a['id'] == actor)
        return response(tool='collaborate', args=envelope(a['event_version'], a['work'], **kw))
    return step


class Scripted:
    model = 'offline-scripted-not-a-benchmark-model'

    def __init__(self, items):
        self.items = iter(items)
        self.received = []

    def complete(self, messages, **kwargs):
        self.received.append(copy.deepcopy(messages))
        item = next(self.items)
        if isinstance(item, Exception):
            raise item
        return item(messages) if callable(item) else item


def runtime(strong=None, weak=None, **kw):
    # Isolate existing topology contracts; test_progress_checkpoints covers the enabled protocol end to end.
    return AdaptiveRuntime(strong=strong or Scripted([]), weak=weak or Scripted([]),
                           progress_checkpoints=kw.pop('progress_checkpoints', False),
                           tools=kw.pop('tools', []), invoke=kw.pop('invoke', lambda n, a: a), **kw)


def setup_three(**kwargs):
    rt = runtime(**kwargs)
    m = rt._new('task', None, 'strong', [])
    a = rt._new('first', m.id, 'weak', [])
    b = rt._new('second', m.id, 'weak', [])
    return rt, m, a, b


def test_ordinary_tool_results_do_not_wake_parent():
    strong = Scripted([change(operation='delegate', pattern='parallel', branches=[{'goal': 'lookup'}]), response('global')])
    weak = Scripted([response(tool='lookup', args={'n': n}) for n in range(4)] + [response('found')])
    rt = runtime(strong, weak, tools=[function('lookup', 'read', {}, [])])
    result = rt.run('task')
    assert result['answer'] == 'global'
    assert len(strong.received) == 2
    notices = [e for e in result['events'] if e['event'] == 'decision_opportunity']
    assert [e['notice']['type'] for e in notices] == ['completed']
    assert result['usage']['model_requests'] == 7
    assert result['metrics']['execution_calls'] + result['metrics']['control_calls'] == 7


def test_parent_premature_answer_does_not_deadlock_child_awaiting_decision():
    rt, main, child, _ = setup_three()
    rt.change(child.id, proposal(rt, child.id, operation='escalate'))
    assert child.status == 'review'
    rt._accept(main, response('premature answer'), None, [])
    assert main.status == 'ready' and rt.final == ''
    rt.change(main.id, {'operation': 'respond', 'request_id': 'r0', 'approve': False, 'reason': 'continue inline'})
    assert child.status == 'ready'


def test_parallel_workers_run_concurrently():
    barrier = threading.Barrier(2)
    class Workers:
        def complete(self, messages, **kw):
            barrier.wait(timeout=3)
            return response('source checked')
    strong = Scripted([change(operation='delegate', pattern='parallel', branches=[{'goal': 'A'}, {'goal': 'B'}]), response('final')])
    result = runtime(strong, Workers(), concurrency=2).run('question')
    assert result['status'] == 'answered' and result['usage']['model_requests'] == 4
    assert len(result['loops']) == 3


def test_sequence_passes_previous_result_and_notifies_dependency_once():
    strong = Scripted([change(operation='delegate', pattern='sequence', branches=[{'goal': 'find ID'}, {'goal': 'use ID'}]),
                       change(operation='wait'), response('global')])
    weak = Scripted([response('ID=123'), response('used 123')])
    rt = runtime(strong, weak)
    result = rt.run('task')
    assert result['status'] == 'answered'
    assert 'ID=123' not in json.dumps(weak.received[0])
    assert 'ID=123' in json.dumps(weak.received[1])
    events = [e for e in rt.events if e['event'] == 'decision_opportunity' and e['notice']['type'] == 'dependency_changed']
    assert len(events) == 1


def test_blocked_event_allows_parent_fold_and_actual_takeover():
    strong = Scripted([
        change(operation='delegate', pattern='parallel', branches=[{'goal': 'investigate', 'skills': ['lookup']}]),
        change(operation='fold', sources=['agent_1'], receiver='main'),
        response(tool='read_history', args={'agent': 'agent_1', 'offset': 0}),
        response(tool='load_skill', args={'name': 'lookup'}),
        response(tool='lookup', args={'id': '43'}),
        response(tool='complete_transferred_work', args={'source': 'agent_1', 'result': 'found 43'}), response('global')])
    weak = Scripted([response(tool='lookup', args={'id': '41'}), change(event_type='blocked'), response(tool='lookup', args={'id': '42'})])
    executed = []
    rt = runtime(strong, weak, max_waves=12, tools=[function('lookup', 'read', {}, [])],
                 invoke=lambda n, a: executed.append(a['id']) or a,
                 skills={'lookup': {'description': 'procedure', 'body': 'read IDs exactly'}})
    result = rt.run('task')
    assert result['answer'] == 'global'
    assert executed == ['41', '42', '43']  # returned tools commit once before migration
    assert [e['agent'] for e in rt.events if e['event'] == 'tool_result'] == ['agent_1', 'agent_1', 'main']
    assert rt.loops['agent_1'].resolved and rt.loops['agent_1'].status == 'folded'
    assert 'lookup' in rt.loops['main'].skills
    capsule = next(e for e in rt.events if e['event'] == 'fold')['capsules'][0]
    assert capsule['evidence_sources']['e0']['agent'] == 'agent_1'
    assert capsule['work']['completion_condition'] == 'investigate'


def test_rejection_resumes_original_conversation_and_deduplicates():
    rt, m, a, b = setup_three()
    outcome = rt.change(a.id, proposal(rt, a.id, operation='fold', sources=[a.id], receiver=m.id))
    original = copy.deepcopy(a.messages)
    assert a.status == 'review' and m.status == 'ready'
    rt.change(m.id, {'operation': 'respond', 'request_id': outcome['request_id'], 'approve': False, 'reason': 'keep independent'})
    assert a.status == 'ready' and a.messages[:len(original)] == original
    duplicate = rt.change(a.id, proposal(rt, a.id, operation='fold', sources=[a.id], receiver=m.id, reason='same request reworded'))
    assert duplicate['duplicate'] is True
    assert len(rt.requests) == 1 and rt.calls == []


def test_stale_proposal_and_unknown_evidence_rejected():
    rt, m, a, b = setup_three()
    with pytest.raises(ValueError, match='event_version'):
        rt.change(m.id, proposal(rt, event_version=999))
    with pytest.raises(ValueError, match='evidence'):
        rt.change(m.id, proposal(rt, evidence_ids=['gold-does-not-exist']))


def test_identical_tool_retry_is_not_new_support():
    rt, m, a, b = setup_three(tools=[function('read', 'read', {}, [])])
    rt._tool(a, 'read', {})
    version = a.version
    rt._tool(a, 'read', {})
    assert a.version == version
    assert not [e for e in rt.events if e['event'] == 'decision_opportunity']


def test_worker_recursively_delegates_via_normal_parent_decision():
    rt, m, a, b = setup_three()
    request = rt.change(a.id, proposal(rt, a.id, operation='delegate', pattern='parallel', branches=[{'goal': 'nested'}]))
    rt.change(m.id, {'operation': 'respond', 'request_id': request['request_id'], 'approve': True, 'reason': 'useful subgoal'})
    assert rt.loops['agent_3'].parent == a.id and a.status == 'waiting'
    assert rt.calls == []


def test_merge_then_fold_keeps_history_and_executes_receiver_tools():
    rt, m, a, b = setup_three(tools=[function('lookup', 'read', {}, [])])
    rt._accept(a, response(tool='lookup', args={'id': 'original'}), None, [])
    rt.change(m.id, proposal(rt, operation='merge', sources=[a.id], receiver=b.id))
    rt.change(m.id, proposal(rt, operation='fold', sources=[b.id], receiver=m.id))
    assert a.transferred_to == b.transferred_to == m.id
    assert 'original' in json.dumps(rt._tool(m, 'read_history', {'agent': a.id, 'offset': 0}))
    rt._tool(m, 'lookup', {'id': 'remaining'})
    for source in (a, b):
        rt._tool(m, 'complete_transferred_work', {'source': source.id, 'result': 'finished here'})
    assert a.resolved and b.resolved and rt.archive['e1']['agent'] == m.id


def test_invalid_migration_changes_no_ownership_or_history():
    rt, m, a, b = setup_three()
    rt._new('nested', a.id, 'weak', [])
    before = copy.deepcopy(rt.loops)
    with pytest.raises(ValueError, match='child scopes'):
        rt.change(m.id, proposal(rt, operation='fold', sources=[a.id], receiver=m.id))
    assert before == rt.loops and rt.calls == []


def test_folded_predecessor_releases_successor_before_parent_final():
    rt, m, a, b = setup_three()
    b.dependencies = [a.id]
    rt.change(m.id, proposal(rt, operation='fold', sources=[a.id], receiver=m.id))
    assert not rt._satisfied(a.id)
    rt._tool(m, 'complete_transferred_work', {'source': a.id, 'result': 'ID=123'})
    rt._unblock()
    rt._unblock()
    assert rt._satisfied(a.id) and m.status != 'done'
    assert 'ID=123' in json.dumps(b.messages) and len(b.completed_dependencies) == 1


def test_failure_wakes_parent_and_failed_child_can_be_taken_over():
    rt, m, a, b = setup_three()
    rt._accept(a, None, 'TimeoutError', [])
    assert m.notices[-1]['type'] == 'failed'
    rt.change(m.id, proposal(rt, operation='fold', sources=[a.id], receiver=m.id))
    assert a.status == 'folded' and rt.calls[0]['usage'] == {}


def test_missing_usage_truncation_transport_error_not_retried():
    for item in [response('partial', finish='length', usage=False), TimeoutError('not logged')]:
        result = runtime(Scripted([item])).run('task')
        assert result['answer'] == '' and result['status'] == 'blocked_or_failed'
        assert result['usage']['model_requests'] == 1
        assert result['usage']['unreported_usage_requests'] == 1
        assert result['correctness'] == 'not_evaluated'


@pytest.mark.parametrize('mode', ['single', 'initial_static', 'no_merge_fold', 'full'])
def test_mode_masks_are_enforced(mode):
    rt, m, a, b = setup_three(collaboration_mode=mode)
    if mode != 'full':
        with pytest.raises(ValueError, match='disabled'):
            rt.change(m.id, proposal(rt, operation='fold', sources=[a.id], receiver=m.id))
    else:
        rt.change(m.id, proposal(rt, operation='fold', sources=[a.id], receiver=m.id))
        assert a.status == 'folded'
    assert 'continue' in allowed_operations(mode, False, False)


def test_initial_static_closes_after_first_business_step():
    rt = runtime(collaboration_mode='initial_static', tools=[function('read', 'read', {}, [])])
    m = rt._new('task', None, 'strong', [])
    rt._accept(m, response(tool='read'), None, [])
    with pytest.raises(ValueError, match='disabled'):
        rt.change(m.id, proposal(rt, operation='delegate', pattern='parallel', branches=[{'goal': 'late'}]))


def test_stale_pending_migration_is_not_applied():
    rt, m, a, b = setup_three(tools=[function('read', 'read', {}, [])])
    request = rt.change(a.id, proposal(rt, a.id, operation='merge', sources=[a.id], receiver=b.id))
    rt._tool(b, 'read', {'new': 'evidence'})
    outcome = rt.change(m.id, {'operation': 'respond', 'request_id': request['request_id'], 'approve': True, 'reason': 'merge'})
    assert outcome == {'approved': False, 'reason': 'scope_changed'}
    assert a.status == 'ready' and a.transferred_to is None and len(rt.archive) == 1


def test_same_blocked_report_does_not_wake_parent_again():
    rt, m, a, b = setup_three()
    rt.change(a.id, proposal(rt, a.id, event_type='blocked'))
    m.status = 'waiting'
    assert rt.change(a.id, proposal(rt, a.id, event_type='blocked'))['duplicate']
    assert m.status == 'waiting' and len(m.notices) == 1


def test_late_response_after_migration_cannot_execute_source_or_receiver_tools():
    executed = []
    rt, m, a, b = setup_three(tools=[function('read', 'read', {}, [])],
                              invoke=lambda n, args: executed.append(args))
    source_epoch, receiver_epoch = a.owner_epoch, b.owner_epoch
    rt.change(m.id, proposal(rt, operation='merge', sources=[a.id], receiver=b.id))
    for actor, epoch in [(a, source_epoch), (b, receiver_epoch)]:
        rt._accept(actor, response(tool='read', args={'stale': actor.id}), None, [], request_epoch=epoch)
    assert executed == []
    assert sum(e['event'] == 'stale_response_discarded' for e in rt.events) == 2
    rt._accept(b, response(tool='read', args={'current': b.id}), None, [], request_epoch=b.owner_epoch)
    assert executed == [{'current': b.id}]


def test_new_completion_notice_requires_parent_to_observe_it_before_final():
    rt, m, a, b = setup_three()
    a.status = b.status = 'done'
    rt._notice(m.id, 'completed', a, {'result': 'new evidence'})
    rt._finish_actor(m, 'answer based on old input')
    assert m.status == 'ready' and rt.final == ''
    rt._deliver_notices(m)
    rt._finish_actor(m, 'answer using new evidence')
    assert rt.final == 'answer using new evidence'
