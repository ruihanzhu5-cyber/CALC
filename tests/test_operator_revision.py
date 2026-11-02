"""Real state transitions with scripted decisions, never benchmark score claims."""
import copy
import json

import pytest

from calc.scheduling import snapshot, scoped_revision_tool
from calc.triggers import compile_candidate
from test_explicit_scheduling import runtime, native, compact, stage, Client, answer
from test_compiled_triggers import make, batch


def revision(operation='delegate', **arguments):
    proposal = compact(operation, **arguments)
    return {'reason': proposal.pop('reason'), 'next_work': proposal.pop('proposed_next'),
            'proposal': proposal}


def prepare(rt, actor):
    rt._tool(actor, 'north', {})
    rt._tool(actor, 'south', {})
    state = snapshot(rt, actor)
    assert rt._compile_opportunity(actor, state)
    return state


def test_keep_can_cover_the_actual_work_without_schema_rejection():
    rt = runtime()
    main = rt._new('task', None, 'strong', [])
    stage(rt, main, {'covered_work_ids': ['scope:main']})
    assert main.status == 'ready' and main.scheduling_feedback is None
    assert rt.events[-1]['event'] == 'scheduling_result'
    assert rt.events[-1]['decision'] == 'keep'


def test_compiled_candidate_can_be_replaced_and_executed_without_second_approval():
    class RevisingClient(Client):
        def complete(self, messages, **kw):
            if 'revise_collaboration' in [t['function']['name'] for t in kw['tools']]:
                body = json.loads(messages[-1]['content'].split('\n', 1)[1])
                if body['state']['actor'] == 'main' and body.get('trigger_kind') == 'multiple_read_sources':
                    self.requests.append((copy.deepcopy(messages), copy.deepcopy(kw)))
                    return native('revise_collaboration', revision(pattern='sequence', branches=[
                        {'goal': 'Investigate a prerequisite'}, {'goal': 'Test the resulting hypothesis'},
                        {'goal': 'Verify the residual requirement'}]))
                self.requests.append((copy.deepcopy(messages), copy.deepcopy(kw)))
                fields = kw['tools'][0]['function']['parameters']['properties']
                choice = {'selection': 'keep'} if 'selection' in fields else {'commit': False}
                return native('commit_collaboration', {**choice, 'reason': 'Continue this bounded scope'})
            return super().complete(messages, **kw)

    first = True
    reads = []
    def solve(messages):
        nonlocal first
        who = messages[0]['content'].split('You are ')[1].split('.')[0]
        if who == 'main':
            if first:
                first = False
                return batch(('north', 'south'))
            return answer()
        observed = any(m['role'] == 'tool' and 'evidence_id' in json.loads(m['content']) for m in messages)
        return answer('Goal done') if observed else native('north', {'page': int(who.split('_')[-1])})
    def invoke(name, args):
        reads.append(name)
        return [{'id': name + '-' + str(args.get('page', 0)) + '-a'},
                {'id': name + '-' + str(args.get('page', 0)) + '-b'}]
    result = make(RevisingClient(solve), invoke=invoke).run('Advance unfinished goals and verify the result')
    assert result['status'] == 'answered'
    assert result['metrics']['collaboration_revisions'] == 1
    assert result['metrics']['scheduling_commit_calls'] == 1
    assert result['metrics']['scheduling_rejections'] == 0
    assert result['metrics']['switches'] == 1
    assert len(result['loops']) == 4  # compiler suggested TWO; decision created THREE
    assert reads == ['north', 'south', 'north', 'north', 'north']
    delegates = [e for e in result['events'] if e['event'] == 'delegate']
    assert len(delegates) == 1 and delegates[0]['pattern'] == 'sequence'


def test_revision_rejection_is_atomic_and_preserves_original_session():
    rt = make()
    main = rt._new('original goal', None, 'strong', [])
    state = prepare(rt, main)
    before = (main.version, main.owner_epoch, copy.deepcopy(main.work))
    rt._accept_decision(main, native('revise_collaboration', revision(pattern='parallel', branches=[
        {'goal': 'valid'}, {'goal': 'invalid', 'tools': ['invented']}])) , None, state)
    assert set(rt.loops) == {'main'} and main.status == 'ready'
    assert (main.version, main.owner_epoch, main.work) == before
    assert not main.scheduling_candidate and main.scheduling_feedback
    assert not any(e['event'] == 'scheduling_revision' for e in rt.events)
    assert len(rt.calls) == 1  # rejected response recorded; no hidden repair request


def test_stale_revision_does_not_execute_and_reports_invalidation():
    rt = make()
    main = rt._new('goal', None, 'strong', [])
    state = prepare(rt, main)
    main.owner_epoch += 1
    rt._accept_decision(main, native('revise_collaboration', revision(pattern='parallel',
        branches=[{'goal': 'A'}, {'goal': 'B'}])), None, state)
    assert set(rt.loops) == {'main'}
    assert any(e['event'] == 'scheduling_invalidated' for e in rt.events)


@pytest.mark.parametrize('operation', ['fold', 'merge'])
def test_revision_transfer_preserves_history_and_successor_completion_semantics(operation):
    rt = make()
    main = rt._new('parent', None, 'strong', [])
    child = rt._new('unfinished investigation', main.id, 'weak', [])
    receiver = main if operation == 'fold' else rt._new('combine investigations', main.id, 'weak', [])
    epoch = child.owner_epoch
    child.messages.append({'role': 'user', 'content': 'original source history'})
    successor = rt._new('consume investigation', main.id, 'weak', [])
    successor.dependencies = [child.id]
    state = prepare(rt, main)
    rt._accept_decision(main, native('revise_collaboration', revision(operation,
        sources=[child.id], receiver=receiver.id)), None, state)
    assert child.status == ('folded' if operation == 'fold' else 'merged') and not child.resolved
    assert child.transferred_to == receiver.id and not rt._satisfied(child.id)
    rt._accept(child, native('south', {'page': 9}), None, [], request_epoch=epoch)
    assert rt.events[-1]['event'] == 'stale_response_discarded'
    assert 'original source history' in json.dumps(rt._tool(receiver, 'read_history', {'agent': child.id, 'offset': 0}))
    rt._tool(receiver, 'north', {})  # receiver actually executes later work
    rt._tool(receiver, 'complete_transferred_work', {'source': child.id, 'result': 'investigation checked'})
    rt._unblock()
    assert rt._satisfied(child.id) and child.id in successor.completed_dependencies


def test_worker_revision_preserves_parent_authority_and_can_continue_after_denial():
    rt = make()
    parent = rt._new('parent', None, 'strong', [])
    child = rt._new('worker', parent.id, 'weak', [])
    state = prepare(rt, child)
    rt._accept_decision(child, native('revise_collaboration', revision('fold',
        sources=[child.id], receiver=parent.id)), None, state)
    assert child.status == 'review' and child.transferred_to is None
    request_id = next(iter(rt.requests))
    rt.change(parent.id, {'operation': 'respond', 'request_id': request_id,
                        'approve': False, 'reason': 'Worker still has useful independent work'})
    assert child.status == 'ready' and child.transferred_to is None
    rt._tool(child, 'north', {'page': 2})
    assert any(e['event'] == 'tool_result' and e['agent'] == child.id for e in rt.events)


def test_revision_still_obeys_experimental_operation_mask():
    rt = make(collaboration_mode='no_merge_fold')
    main = rt._new('parent', None, 'strong', [])
    child = rt._new('child', main.id, 'weak', [])
    state = prepare(rt, main)
    tool = scoped_revision_tool(rt, main, state)
    assert 'fold' not in tool['function']['parameters']['properties']['proposal']['properties']['operation']['enum']
    rt._accept_decision(main, native('revise_collaboration', revision('fold',
        sources=[child.id], receiver=main.id)), None, state)
    assert child.status == 'ready' and child.transferred_to is None


def test_continuation_panel_keeps_future_usage_unknown_and_displays_join_work():
    rt = make()
    main = rt._new('parent', None, 'strong', [])
    prepare(rt, main)
    panel = main.scheduling_candidate['cost_panel']
    future = panel['continuation']
    assert future['candidate'][0]['owner'] == 'main'
    assert future['candidate'][0]['status'] == 'waiting'
    assert len(future['candidate']) == 3
    assert panel['candidate']['sum_ready_input_utf8_bytes'] < panel['candidate']['sum_next_input_utf8_bytes']
    expression = future['conditional_readout']
    assert 'NOT assigned' in expression['variable']
    assert expression['keep_expression']['coefficient_k'] == 2 * panel['keep']['owners'][0]['input_utf8_bytes']
    assert panel['candidate']['remaining_model_calls'] is None
    assert panel['candidate']['remaining_wall_seconds'] is None


def test_fresh_reported_goal_frontier_works_without_benchmark_metadata():
    rt = make(tool_traits=None)
    main = rt._new('task', None, 'strong', [])
    main.subgoals = [
        {'id': 'a', 'goal': 'Investigate A', 'status': 'open', 'dependencies': []},
        {'id': 'b', 'goal': 'Investigate B', 'status': 'open', 'dependencies': []},
        {'id': 'c', 'goal': 'Integrate A and B', 'status': 'open', 'dependencies': ['a', 'b']}]
    main.latest_report = 'reported'
    main.progress_reports['reported'] = {'version': main.version}
    plan = compile_candidate(rt, main, snapshot(rt, main))
    assert plan['kind'] == 'reported_work_frontier'
    assert [b['goal'] for b in plan['proposal']['branches']] == ['Investigate A', 'Investigate B']
    assert plan['facts']['origin'] == 'model_report_not_runtime_verified'
    main.compiled_triggers.append(plan['signature'])
    assert compile_candidate(rt, main, snapshot(rt, main)) is None
    main.version += 1
    assert compile_candidate(rt, main, snapshot(rt, main)) is None  # stale report


def test_continuation_does_not_hide_unresolved_failed_work():
    rt = make()
    main = rt._new('parent', None, 'strong', [])
    failed = rt._new('unfinished failed obligation', main.id, 'weak', [])
    failed.status = 'failed'
    prepare(rt, main)
    future = main.scheduling_candidate['cost_panel']['continuation']
    assert any(row['owner'] == failed.id and row['status'] == 'failed' for row in future['keep'])
    assert any(row['owner'] == failed.id and row['status'] == 'failed' for row in future['candidate'])


@pytest.mark.parametrize('read_only', [False, True])
def test_takeover_opportunity_is_about_unfinished_work_not_reader_label(read_only):
    rt = make()
    main = rt._new('parent', None, 'strong', [])
    child = rt._new('child', main.id, 'weak', [])
    child.read_only = read_only
    rt._checkpoint(child, 'resource_pressure', 'one-pressure', {'cause': 'incomplete_output'})
    candidate = compile_candidate(rt, child, snapshot(rt, child))
    assert candidate['kind'] == 'loop_takeover_review'
    assert child.status == 'ready' and child.transferred_to is None  # opportunity, never forced fold
