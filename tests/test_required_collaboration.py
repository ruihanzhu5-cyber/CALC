"""Explicit collaboration requirement, separately from autonomous evaluation."""
import json
import threading

import pytest

from calc.scheduling import snapshot, scoped_revision_tool
from test_compiled_triggers import make, batch
from test_explicit_scheduling import Client, answer, native, compact


def required(client=None, **options):
    return make(client, collaboration_requirement='required_parallel', concurrency=2, **options)


def frontier(rt):
    main = rt._new('original work', None, 'strong', [])
    rt._tool(main, 'north', {})
    rt._tool(main, 'south', {})
    state = snapshot(rt, main)
    assert rt._compile_opportunity(main, state)
    assert state == snapshot(rt, main)  # activation refreshed the immutable decision state
    return main, state


def test_requirement_is_explicit_and_default_does_not_force_delegation():
    rt = make(Client(lambda messages: answer()))
    result = rt.run('simple task')
    assert result['status'] == 'answered' and len(result['loops']) == 1
    assert result['collaboration_requirement'] == 'none'


@pytest.mark.parametrize('options', [{'concurrency': 1}, {'collaboration_mode': 'single'},
                                  {'compiled_triggers': False}])
def test_incompatible_required_profile_is_rejected(options):
    from calc.adaptive import AdaptiveRuntime
    client = Client(lambda m: answer())
    cfg = dict(strong=client, weak=client, tools=[], invoke=lambda n,a:a,
               scheduling='explicit', compiled_triggers=True, concurrency=2,
               collaboration_requirement='required_parallel')
    with pytest.raises(ValueError):
        AdaptiveRuntime(**(cfg | options))


def test_frontier_masks_keep_and_sequence_but_allows_parallel_revision():
    rt = required()
    main, state = frontier(rt)
    assert rt._commit_schema(main)['function']['parameters']['properties']['selection']['enum'] == ['parallel']
    revision = scoped_revision_tool(rt, main, state)['function']['parameters']['properties']['proposal']
    assert revision['properties']['operation']['enum'] == ['delegate']
    assert revision['properties']['pattern']['enum'] == ['parallel']
    assert revision['properties']['branches']['minItems'] == 2
    assert revision['properties']['branches']['items']['properties']['read_only']['const'] is True
    rt._accept_decision(main, native('commit_collaboration', {'selection':'keep', 'reason':'Prefer inline'}), None, state)
    assert main.scheduling_feedback and len(rt.loops) == 1
    with pytest.raises(PermissionError):
        rt._tool(main, 'north', {'page': 1})  # cannot bypass gate by ignoring the control schema


def test_final_submission_is_guarded_before_any_external_side_effect():
    executed = []
    rt = required(invoke=lambda n,a: executed.append(n) or [], is_final_submission=lambda n,a: n == 'save')
    main = rt._new('task', None, 'strong', [])
    with pytest.raises(PermissionError):
        rt._tool(main, 'save', {})
    assert executed == []
    rt._finish_actor(main, 'I say done without workers')
    assert not rt.final and main.status == 'failed'
    assert any(e['event'] == 'collaboration_requirement_failed' for e in rt.events)


def test_documentation_only_or_claimed_worker_success_cannot_satisfy_requirement():
    def traits(name, args):
        return {'effect':'read','family':name,'label':name,'category':'capability'}
    rt = required(tool_traits=traits)
    main = rt._new('task', None, 'strong', [])
    rt._apply_change(main.id, compact(pattern='parallel', branches=[{'goal':'A'}, {'goal':'B'}]))
    for child in rt._live_children(main.id):
        rt._tool(child, 'north', {})
        rt._finish_actor(child, 'Completed')
    assert rt.collaboration_receipts() == []


def test_shared_capability_reads_do_not_trigger_task_splitting_or_takeover():
    from calc.triggers import compile_candidate
    rt = required(tool_traits=lambda n,a:{'effect':'read','family':n,'label':n,'category':'capability'})
    main = rt._new('task', None, 'strong', [])
    rt._tool(main, 'north', {})
    rt._tool(main, 'south', {})
    assert not main.read_sources
    assert compile_candidate(rt, main, snapshot(rt, main)) is None
    child = rt._new('different work using shared docs', main.id, 'weak', [])
    child.read_only = True
    rt._tool(child, 'north', {})
    assert any(e['event'] == 'repeated_access' for e in rt.events)
    assert not any(e['type'] == 'overlap' for e in child.checkpoints.values())
    assert compile_candidate(rt, child, snapshot(rt, child)) is None


def test_required_plan_cannot_be_changed_to_inline_or_unrestricted_readers():
    rt = required()
    main, _ = frontier(rt)
    for proposal in [compact(pattern='sequence', branches=[{'goal':'A'},{'goal':'B'}]),
                     compact(pattern='parallel', branches=[{'goal':'A'},{'goal':'B'}])]:
        with pytest.raises(ValueError):
            rt._apply_change(main.id, proposal)
    assert list(rt.loops) == ['main']


def test_real_parallel_workers_deliver_task_evidence_then_main_writes_and_finishes():
    barrier = threading.Barrier(2)
    first = True
    saved = []
    def solve(messages):
        nonlocal first
        who = messages[0]['content'].split('You are ')[1].split('.')[0]
        if who == 'main':
            if first:
                first = False
                return batch(('north', 'south'))
            return answer() if saved else native('save', {})
        observed = any(m['role']=='tool' and 'evidence_id' in json.loads(m['content']) for m in messages)
        if observed:
            return answer('Task records collected')
        barrier.wait(timeout=5)
        return native('north' if who=='agent_1' else 'south', {'page':1})
    def invoke(name, args):
        if name == 'save':
            saved.append(True)
            return {'saved':True}
        return [{'id':name+str(args.get('page',0))+'-a'}, {'id':name+str(args.get('page',0))+'-b'}]
    result = required(Client(solve), invoke=invoke).run('Collect independent records then save')
    assert result['status'] == 'answered' and saved == [True]
    assert result['metrics']['switches'] == 1
    assert result['collaboration_requirement'] == 'required_parallel'
    assert len(result['collaboration_receipts'][0]['deliveries']) == 2
    assert result['metrics']['scheduling_rejections'] == 0
    last_child = max(e['index'] for e in result['events'] if e['event']=='local_answer' and e['agent']!='main')
    parent_write = next(e['index'] for e in result['events'] if e['event']=='tool_result' and e['tool']=='save')
    assert last_child < parent_write


def test_shared_capability_context_is_an_index_not_a_copy_of_raw_documents():
    rt = required(tool_traits=lambda n,a:{'effect':'read','family':n,'label':n,'category':'capability'},
                  invoke=lambda n,a:'PUBLIC_DOC_' * 2000)
    main = rt._new('task', None, 'strong', [])
    observation = rt._tool(main, 'north', {})
    main.messages.extend([native('north', {}).message,
                          {'role':'tool','tool_call_id':'native-call','content':json.dumps(observation)}])
    rt._apply_change(main.id, compact(pattern='parallel', branches=[{'goal':'A'},{'goal':'B'}]))
    child = rt.loops['agent_1']
    assignment = json.loads(child.messages[1]['content'].split('\n',1)[1])
    assert assignment['shared_context_index'][0]['evidence_id'] == 'e0'
    assert 'PUBLIC_DOC_' not in child.messages[1]['content']
    assert 'PUBLIC_DOC_' in str(rt._tool(child, 'read_evidence', {'id':'e0'}))
    assert 'PUBLIC_DOC_' in str(rt._tool(child, 'read_history', {'agent':main.id,'offset':0}))
