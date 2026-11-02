"""Delegation contracts use scripted clients only; never benchmark scores or APIs."""
import copy
import json
from dataclasses import asdict

import pytest

from calc.adaptive import AdaptiveRuntime, function
from calc.llm import ChatResponse, Usage


class Scripted:
    model = 'offline-scripted-not-a-benchmark-model'

    def __init__(self, items=()):
        self.items = iter(items)
        self.received = []

    def complete(self, messages, **kwargs):
        self.received.append(copy.deepcopy(messages))
        item = next(self.items)
        return item(messages) if callable(item) else item


def response(text='done', tool=None, args=None):
    message = {'role': 'assistant', 'content': text if tool is None else None}
    if tool:
        message['tool_calls'] = [{'id': 'call1', 'type': 'function', 'function': {
            'name': tool, 'arguments': json.dumps(args or {})}}]
    return ChatResponse(message, 'tool_calls' if tool else 'stop',
                        Usage.from_response({'prompt_tokens': 5, 'completion_tokens': 2}), 0)


def runtime(**kwargs):
    return AdaptiveRuntime(strong=kwargs.pop('strong', Scripted()),
        weak=kwargs.pop('weak', Scripted()), progress_checkpoints=False,
        tools=[function('lookup', 'Read one resource', {'product': {'type': 'string'}}, []),
               function('purchase', 'Commit a purchase', {}, [])],
        invoke=kwargs.pop('invoke', lambda n, a: {'tool': n, 'value': a}), **kwargs)


def proposal(rt, **kwargs):
    main = rt.loops['main']
    return {'operation': 'delegate', 'reason': 'independent shopping responsibility',
        'event_type': 'progress', 'event_version': main.version,
        'progress': asdict(main.work), 'evidence_ids': list(main.evidence),
        'baseline_next': 'Main performs both email and shopping work',
        'proposed_next': 'worker checks shopping while Main handles email',
        'expected_savings': 'independent information gathering may overlap',
        'risks': 'worker must not duplicate Main email work',
        'handoff': 'COMMON-HANDOFF: buy only after availability is verified',
        'pattern': 'parallel', 'branches': [{'goal': 'check product'}], **kwargs}


def retained():
    return {'current_scope': 'Send attendance emails', 'progress': 'Recipients identified',
        'completion_condition': 'Each recipient has one confirmed email send',
        'next_step': 'Send the first email', 'unresolved': ['Two recipients remain'],
        'failed_routes': ['Do not retry the obsolete address']}


def test_branch_handoff_progress_and_raw_evidence_reach_real_child_input():
    rt = runtime()
    main = rt._new('email and shopping', None, 'strong', [])
    main.work.unresolved = ['UNFINISHED: verify red variant']
    main.work.failed_routes = ['FAILED-ROUTE: old product is unavailable']
    evidence = rt._tool(main, 'lookup', {'product': 'red'})['evidence_id']
    result = rt.change('main', proposal(rt, branches=[{
        'goal': 'Verify shopping variant', 'completion_condition': 'Availability confirmed',
        'handoff': 'BRANCH-HANDOFF: red only', 'evidence_ids': [evidence], 'tools': ['lookup']}]))
    child = rt.loops[result['agents'][0]]
    actual_input = json.dumps(rt._messages(child), ensure_ascii=False)
    for fact in ['COMMON-HANDOFF', 'BRANCH-HANDOFF', 'UNFINISHED', 'FAILED-ROUTE',
                 'Availability confirmed', evidence, 'read_history']:
        assert fact in actual_input
    assert rt._tool(child, 'read_evidence', {'id': evidence})['arguments'] == {'product': 'red'}
    assert child.work.completion_condition == 'Availability confirmed'
    assert child.allowed_tools == ['lookup']


def test_delegation_parent_history_is_an_immutable_snapshot():
    rt = runtime()
    main = rt._new('ORIGINAL-PARENT-TASK', None, 'strong', [])
    main.messages.append({'role': 'user', 'content': 'PRIOR-EVIDENCE'})
    result = rt.change('main', proposal(rt))
    child = rt.loops[result['agents'][0]]
    main.messages[0]['content'] = 'MUTATED-ORIGINAL'
    main.messages.append({'role': 'user', 'content': 'LATER-PRIVATE-WORK'})
    history = rt._tool(child, 'read_history', {'agent': 'main', 'offset': 0})
    text = json.dumps(history)
    assert 'ORIGINAL-PARENT-TASK' in text and 'PRIOR-EVIDENCE' in text
    assert 'MUTATED-ORIGINAL' not in text and 'LATER-PRIVATE-WORK' not in text
    with pytest.raises(ValueError):
        rt._tool(child, 'read_history', {'agent': 'unknown', 'offset': 0})


def test_retained_work_keeps_main_ready_but_does_not_allow_global_early_answer():
    executed = []
    rt = runtime(invoke=lambda n, a: executed.append(n))
    main = rt._new('email and shopping', None, 'strong', [])
    rt.change('main', proposal(rt, retained_work=retained()))
    assert main.status == 'ready' and asdict(main.work) == retained()
    rt._accept(main, response(tool='lookup'), None, [])
    assert executed == ['lookup']
    rt._accept(main, response('premature overall completion'), None, [])
    assert not rt.final and main.status != 'done'
    assert any('Unfinished children' in (m.get('content') or '') for m in main.messages)


def test_delegate_without_retained_work_preserves_waiting_semantics():
    rt = runtime()
    main = rt._new('delegate task', None, 'strong', [])
    rt.change('main', proposal(rt))
    assert main.status == 'waiting'


def test_explicit_branch_tools_are_enforced_before_external_execution():
    executed = []
    rt = runtime(invoke=lambda n, a: executed.append(n))
    rt._new('delegate task', None, 'strong', [])
    result = rt.change('main', proposal(rt, branches=[{'goal': 'read only', 'tools': ['lookup']}]))
    child = rt.loops[result['agents'][0]]
    rt._tool(child, 'lookup', {})
    with pytest.raises(ValueError):
        rt._tool(child, 'purchase', {})
    assert executed == ['lookup']


@pytest.mark.parametrize('bad_branch', [
    {'goal': 'bad', 'tools': ['nonexistent']},
    {'goal': 'bad', 'evidence_ids': ['e-does-not-exist']},
    {'goal': 'bad', 'completion_condition': ''},
])
def test_invalid_branch_does_not_create_a_partial_team(bad_branch):
    rt = runtime()
    main = rt._new('delegate task', None, 'strong', [])
    before = copy.deepcopy(main)
    with pytest.raises(ValueError):
        rt.change('main', proposal(rt, branches=[{'goal': 'valid first'}, bad_branch]))
    assert list(rt.loops) == ['main'] and main == before


def test_merge_preserves_two_different_parent_snapshot_identities():
    rt = runtime()
    main = rt._new('original context', None, 'strong', [])
    rt.change('main', proposal(rt))
    first = rt.loops['agent_1']
    first_ref = next(ref for ref in first.history_refs if '@' in ref)
    main.messages.append({'role': 'user', 'content': 'NEW_INDEPENDENT_FACT'})
    rt._tool(main, 'lookup', {})
    rt.change('main', proposal(rt))
    second = rt.loops['agent_2']
    second_ref = next(ref for ref in second.history_refs if '@' in ref)
    assert first_ref != second_ref
    rt.change('main', proposal(rt, operation='merge', sources=[second.id], receiver=first.id))
    old = json.dumps(rt._tool(first, 'read_history', {'agent': first_ref, 'offset': 0}))
    new = json.dumps(rt._tool(first, 'read_history', {'agent': second_ref, 'offset': 0}))
    assert 'NEW_INDEPENDENT_FACT' not in old and 'NEW_INDEPENDENT_FACT' in new
    assert 'NEW_INDEPENDENT_FACT' not in json.dumps(rt._tool(first, 'read_history', {'agent': 'main', 'offset': 0}))
