"""State-machine tests: real control paths, no model/API or simulated scores."""
import copy
import json
import threading

import pytest

from calc.adaptive import AdaptiveRuntime, function
from calc.llm import ChatResponse, Usage
from calc.scheduling import snapshot, preview, cost_panel


def native(name, arguments, finish='tool_calls'):
    return ChatResponse({'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'native-call', 'type': 'function',
         'function': {'name': name, 'arguments': json.dumps(arguments)}}]},
        finish, Usage.from_response({'prompt_tokens': 8, 'completion_tokens': 3}), 0.01)


def keep(state, **changes):
    fields = {'decision': 'keep', 'reason': 'This work can continue without another loop',
            'next_work': 'Current owner executes its next unresolved step',
            **changes}
    if fields['decision'] == 'candidate' and 'covered_work_ids' not in fields:
        fields['covered_work_ids'] = [w['work_id'] for w in state['work']]
    return fields


class Client:
    model = 'offline-test-only'

    def __init__(self, solve, decide=None, commit=True):
        self.solve, self.decide, self.commit = solve, decide, commit
        self.requests = []

    def complete(self, messages, **kw):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(kw)))
        names = [t['function']['name'] for t in kw['tools']]
        if names == ['decide_collaboration']:
            state = json.loads(messages[-1]['content'].split('\n', 1)[1])
            return native(names[0], self.decide(state) if self.decide else keep(state))
        if names == ['commit_collaboration']:
            fields = kw['tools'][0]['function']['parameters']['properties']
            choice = {'selection': 'parallel' if self.commit else 'keep'} if 'selection' in fields else {'commit': self.commit}
            return native(names[0], {**choice, 'reason': 'Compared the same work and actual context transfer'})
        return self.solve(messages)


def answer(text='completed locally'):
    return ChatResponse({'role': 'assistant', 'content': text}, 'stop',
                        Usage.from_response({'prompt_tokens': 5, 'completion_tokens': 2}), 0.01)


def runtime(client=None, **kw):
    client = client or Client(lambda m: answer())
    return AdaptiveRuntime(strong=client, weak=kw.pop('weak', client), scheduling='explicit',
                           tools=kw.pop('tools', []), invoke=kw.pop('invoke', lambda n, a: a), **kw)


def compact(operation='delegate', **fields):
    return {'operation': operation, 'reason': 'Independent work exists',
            'proposed_next': 'Receiver executes the same remaining work',
            'expected_savings': 'Hypothesis only: avoid serial independent calls',
            'risks': 'Handoff can lose details', 'handoff': 'Keep sources and completion criteria', **fields}


def stage(rt, actor, data):
    state = snapshot(rt, actor)
    rt._accept_decision(actor, native('decide_collaboration', keep(state, **data)), None, state)
    return state


def test_mandatory_decision_and_no_control_for_every_scalar_tool_result():
    steps = iter([native('lookup', {'n': n}) for n in range(4)] + [answer()])
    c = Client(lambda m: next(steps))
    rt = runtime(c, tools=[function('lookup', 'read scalar', {'n': {'type': 'integer'}}, ['n'])],
                 invoke=lambda n, a: {'value': a['n']})
    result = rt.run('Read four scalar values')
    assert result['status'] == 'answered'
    assert result['metrics']['scheduling_decision_calls'] == 2  # start and first observation
    assert result['metrics']['explicit_keep_decisions'] == 2
    assert result['metrics']['switches'] == 0
    assert result['usage']['model_requests'] == 7
    assert len([e for e in rt.events if e['event'] == 'model_request_started']) == 7
    assert rt.calls[0]['purpose'] == 'collaboration_decision'


def test_collection_events_are_merged_and_do_not_require_progress_report():
    steps = iter([native('lookup', {}), answer()])
    c = Client(lambda m: next(steps))
    rt = runtime(c, tools=[function('lookup', 'read', {}, [])],
                 invoke=lambda n, a: {'items': [{'id': 1}, {'id': 2}]})
    result = rt.run('Inspect objects')
    assert result['metrics']['scheduling_decision_calls'] == 2
    batches = [e for e in rt.events if e['event'] == 'scheduling_started']
    assert len(batches[1]['event_ids']) == 2
    assert result['metrics']['progress_calls'] == 0


@pytest.mark.parametrize('mutate', [
    lambda d: d.update(snapshot_id='invented'),
    lambda d: d.update(event_ids=[]),
    lambda d: d.update(covered_work_ids=[]),
    lambda d: d.update(evidence_ids=['unavailable']),
    lambda d: d.update(decision='unknown'),
    lambda d: d.update(extra_field=True),
])
def test_invalid_decision_fails_visibly_without_automatic_keep(mutate):
    def bad(s):
        data = keep(s)
        mutate(data)
        return data
    c = Client(lambda m: pytest.fail('Business tools must not run'), decide=bad)
    result = runtime(c).run('Task')
    assert result['status'] == 'blocked_or_failed'
    assert result['metrics']['scheduling_errors'] == 1
    assert result['metrics']['explicit_keep_decisions'] == 0
    assert result['usage']['model_requests'] == 1


@pytest.mark.parametrize('arguments,finish', [('{"decision":', 'length'),
    ('{"snapshot_id":"a","snapshot_id":"b"}', 'tool_calls')])
def test_truncation_and_duplicate_keys_do_not_repair_or_execute(arguments, finish):
    rt = runtime()
    main = rt._new('task', None, 'strong', [])
    msg = native('decide_collaboration', {}).message
    msg['tool_calls'][0]['function']['arguments'] = arguments
    rt._accept_decision(main, ChatResponse(msg, finish, Usage(), 0), None, snapshot(rt, main))
    assert main.status == 'failed'
    assert len(rt.calls) == 1 and rt.calls[0]['usage']['reported'] is False
    assert not any(e['event'] == 'scheduling_result' for e in rt.events)


def test_candidate_preview_and_rejection_preserve_original_session():
    rt = runtime(invoke=lambda n, a: pytest.fail('preview invoked environment'))
    main = rt._new('original', None, 'strong', [])
    proposal = compact(pattern='parallel', branches=[{'goal': 'A'}, {'goal': 'B'}])
    state = stage(rt, main, {'decision': 'candidate', 'proposal': proposal})
    assert list(rt.loops) == ['main']
    assert main.status == 'ready' and main.scheduling_candidate
    panel = main.scheduling_candidate['cost_panel']
    assert len(panel['candidate']['owners']) == 3  # waiting parent + two children
    assert panel['candidate']['remaining_wall_seconds'] is None
    rt._accept_decision(main, native('commit_collaboration', {
        'commit': False, 'reason': 'Handoff dominates'}), None, state)
    assert list(rt.loops) == ['main'] and main.status == 'ready'
    assert main.messages[0]['content'] == 'original'
    assert main.scheduling_candidate is None and not main.checkpoints
    assert rt.calls[-1]['purpose'] == 'collaboration_commit'


def test_parallel_delegation_remains_concurrent_and_parent_decides_completion():
    barrier = threading.Barrier(2)
    def solve(m):
        who = m[0]['content'].split('You are ')[1].split('.')[0]
        if who != 'main':
            barrier.wait(timeout=3)
        return answer()
    def decision(s):
        if s['actor'] == 'main' and s['events'][0]['type'] == 'task_start':
            return keep(s, decision='candidate', proposal=compact(pattern='parallel',
                        branches=[{'goal': 'A'}, {'goal': 'B'}]))
        return keep(s)
    c = Client(solve, decision)
    result = runtime(c, concurrency=2).run('Independent A and B')
    assert result['status'] == 'answered'
    assert len(result['loops']) == 3
    assert result['metrics']['switches'] == 1
    assert result['metrics']['scheduling_commit_calls'] == 1
    assert result['metrics']['scheduling_errors'] == 0
    assert any(e['event'] == 'scheduling_started' and e['agent'] == 'main' and len(e['event_ids']) == 2
               for e in result['events'])


def test_defer_is_released_by_completion_not_repeated_tool_versions():
    rt = runtime()
    parent = rt._new('parent', None, 'strong', [])
    child = rt._new('child', parent.id, 'weak', [])
    stage(rt, parent, {'decision': 'defer', 'dependencies': [child.id]})
    assert parent.status == 'waiting'
    child.version += 3
    rt._unblock()
    assert parent.status == 'waiting' and not parent.checkpoints
    rt._finish_actor(child, 'done')
    rt._unblock()
    assert parent.status == 'ready' and not parent.scheduling_wait
    rt._deliver_notices(parent)
    assert any(c['type'] == 'completed' for c in parent.checkpoints.values())


@pytest.mark.parametrize('dependency', ['main', 'unknown'])
def test_defer_cannot_self_deadlock(dependency):
    rt = runtime()
    main = rt._new('main', None, 'strong', [])
    stage(rt, main, {'decision': 'defer', 'dependencies': [dependency]})
    assert main.status == 'failed'


def test_changed_owner_epoch_invalidates_candidate_without_transition():
    rt = runtime()
    main = rt._new('parent', None, 'strong', [])
    state = stage(rt, main, {'decision': 'candidate', 'proposal': compact(
        pattern='parallel', branches=[{'goal': 'A'}])})
    main.owner_epoch += 1
    rt._accept_decision(main, native('commit_collaboration', {
        'commit': True, 'reason': 'commit'}), None, state)
    assert list(rt.loops) == ['main']
    assert main.status == 'ready' and main.scheduling_candidate is None
    assert any(e['event'] == 'scheduling_invalidated' for e in rt.events)


def test_fold_preview_and_commit_use_real_capsule_and_complete_transferred_work():
    rt = runtime(tools=[function('lookup', 'read', {}, [])], invoke=lambda n, a: {'found': True})
    main = rt._new('parent', None, 'strong', [])
    child = rt._new('unfinished', main.id, 'weak', [])
    child.messages.append({'role': 'user', 'content': 'source history'})
    state = stage(rt, main, {'decision': 'candidate', 'proposal': compact(
        'fold', sources=[child.id], receiver=main.id)})
    assert child.status == 'ready'  # preview does not migrate the live owner
    assert [row['agent'] for row in main.scheduling_candidate['cost_panel']['candidate']['owners']] == ['main']
    rt._accept_decision(main, native('commit_collaboration', {
        'commit': True, 'reason': 'Parent can finish using shared evidence'}), None, state)
    assert child.status == 'folded' and child.transferred_to == main.id
    assert 'source history' in json.dumps(rt._tool(main, 'read_history', {'agent': child.id, 'offset': 0}))
    rt._tool(main, 'lookup', {})
    successor = rt._new('dependent', main.id, 'weak', [])
    successor.dependencies = [child.id]
    rt._tool(main, 'complete_transferred_work', {'source': child.id, 'result': 'found'})
    rt._unblock()
    assert rt._satisfied(child.id) and child.id in successor.completed_dependencies


def test_preview_isolation_and_operation_mask():
    rt = runtime(collaboration_mode='no_merge_fold')
    main = rt._new('parent', None, 'strong', [])
    child = rt._new('child', main.id, 'weak', [])
    state = stage(rt, main, {'decision': 'candidate', 'proposal': compact(
        'fold', sources=[child.id], receiver=main.id)})
    assert 'fold' not in state['allowed_operations']
    assert child.status == 'ready' and main.status == 'failed'


def test_missing_frontier_units_cannot_be_saved_by_a_cheaper_candidate():
    rt = runtime()
    main = rt._new('parent', None, 'strong', [])
    child = rt._new('hard task', main.id, 'weak', [])
    stage(rt, main, {'decision': 'candidate', 'covered_work_ids': ['scope:main'],
                     'proposal': compact('fold', sources=[child.id], receiver=main.id)})
    assert main.status == 'failed' and child.status == 'ready'


def test_normal_solver_suggestion_enters_same_decision_gateway():
    calls = 0
    def solve(m):
        nonlocal calls
        calls += 1
        return native('collaborate', {'operation': 'wait', 'reason': 'suggestion only'}) if calls == 1 else answer()
    rt = runtime(Client(solve))
    result = rt.run('task')
    assert result['status'] == 'answered'
    assert result['metrics']['scheduling_decision_calls'] == 2
    assert result['metrics']['collaboration_requests'] == 0  # suggestion did not directly change team


def test_compilation_is_state_only_and_missing_future_usage_stays_unknown():
    rt = runtime(invoke=lambda n, a: pytest.fail('must not execute'))
    main = rt._new('task', None, 'strong', [])
    p = {**compact(pattern='parallel', branches=[{'goal': 'A'}]),
         'progress': {'current_scope': 'task', 'progress': 'initial', 'completion_condition': 'task',
                      'unresolved': [], 'failed_routes': [], 'next_step': 'inspect'}, 'evidence_ids': []}
    shadow = preview(rt, main.id, p)
    panel = cost_panel(rt, shadow, snapshot(rt, main))
    assert list(rt.loops) == ['main'] and list(shadow.loops) == ['main', 'agent_1']
    assert panel['candidate']['future_output_tokens'] is None


def test_progress_update_does_not_consume_undecided_events():
    rt = runtime()
    main = rt._new('task', None, 'strong', [])
    before = list(main.checkpoints)
    rt._report_progress(main, {'report_id': 'p1', 'summary': 'Observed two goals',
        'next_step': 'Check whether they are independent', 'evidence_ids': [], 'reason': 'new task understanding'})
    assert list(main.checkpoints) == before
    assert snapshot(rt, main)['event_ids'] == before


def test_pending_child_request_can_be_rejected_inside_the_same_gateway():
    rt = runtime()
    parent = rt._new('parent', None, 'strong', [])
    child = rt._new('child', parent.id, 'weak', [])
    request = {**compact('escalate'), 'event_type': 'progress', 'event_version': child.version,
               'progress': {'current_scope': child.goal, 'progress': 'initial',
                   'completion_condition': child.goal, 'unresolved': [], 'failed_routes': [], 'next_step': 'inspect'},
               'evidence_ids': [], 'baseline_next': 'inspect'}
    rt.change(child.id, request)
    rt._deliver_notices(parent)
    state = stage(rt, parent, {'decision': 'candidate', 'proposal': compact('respond',
        request_id='r0', approve=False)})
    rt._accept_decision(parent, native('commit_collaboration', {
        'commit': True, 'reason': 'Reject escalation, keep original session'}), None, state)
    assert child.status == 'ready' and rt.requests['r0']['status'] == 'decided'
    assert child.messages[0]['content'] == 'child'
    assert any('Parent decision' in str(m.get('content')) for m in child.messages)


def test_explicit_requires_events_and_has_no_hidden_limits():
    with pytest.raises(ValueError, match='requires progress_checkpoints'):
        runtime(progress_checkpoints=False)
    rt = runtime()
    assert rt.max_waves is None


def test_snapshot_and_event_identity_are_bound_without_model_echo():
    rt = runtime()
    main = rt._new('task', None, 'strong', [])
    state = snapshot(rt, main)
    data = {'decision': 'keep', 'reason': 'One dependent chain using existing source evidence',
            'next_work': 'Main checks the next prerequisite'}
    rt._accept_decision(main, native('decide_collaboration', data), None, state)
    assert main.status == 'ready' and not main.checkpoints
    recorded = next(e for e in rt.events if e['event'] == 'scheduling_result')
    assert recorded['snapshot_id'] == state['snapshot_id']
    assert recorded['covered_work_ids'] == ['scope:main']


def test_decision_protocol_has_no_model_generated_evidence_identity():
    rt = runtime()
    parameters = rt.decide_tool['function']['parameters']
    assert 'evidence_ids' not in parameters['properties']
    assert parameters['additionalProperties'] is False
    main = rt._new('task', None, 'strong', [])
    state = snapshot(rt, main)
    # This is the actual class of failed pilot response, not an ID to repair.
    bad = keep(state, evidence_ids=[state['event_ids'][0]])
    rt._accept_decision(main, native('decide_collaboration', bad), None, state)
    assert main.status == 'failed'
    assert any(e['event']=='scheduling_error' and 'Additional properties' in e['detail'] for e in rt.events)


def test_candidate_binds_real_snapshot_evidence_without_echo_or_environment_call():
    rt = runtime(tools=[function('read','read source',{},[])], invoke=lambda n,a:{'value':1})
    main = rt._new('task',None,'strong',[])
    rt._tool(main,'read',{})
    state = snapshot(rt,main)
    data = keep(state,decision='candidate',proposal=compact(pattern='parallel',branches=[{'goal':'inspect'}]))
    assert 'evidence_ids' not in data
    rt._accept_decision(main,native('decide_collaboration',data),None,state)
    assert main.scheduling_candidate['proposal']['evidence_ids']==['e0']
    assert len(rt.archive)==1 and set(rt.loops)=={'main'}
