"""Real _accept integration contracts, with no API or benchmark invocation."""
import json

import pytest

from calc.adaptive import AdaptiveRuntime, function
from calc.llm import ChatResponse, Usage


class NoModel:
    model = 'offline-no-model'

    def complete(self, *args, **kwargs):
        raise AssertionError('these integration tests must not call a model')


def setup_runtime():
    executed = []
    rt = AdaptiveRuntime(strong=NoModel(), weak=NoModel(),
        tools=[function('lookup', 'Read one record', {'index': {'type': 'integer'}}, ['index'])],
        invoke=lambda name, args: executed.append((name, args)) or {'found': True},
        progress_checkpoints=False)
    main = rt._new('Find the record', None, 'strong', [])
    return rt, main, executed


def call(args='{"index":1}', name='lookup', call_id='c1'):
    return {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': args}}


def response(calls):
    return ChatResponse({'role': 'assistant', 'content': None, 'tool_calls': calls},
        'tool_calls', Usage.from_response({'prompt_tokens': 5, 'completion_tokens': 2}), 0)


def assert_wire_pairing(messages):
    """Every forwarded assistant call is structurally legal and has one reply."""
    pending = set()
    for message in messages:
        if message['role'] == 'assistant' and message.get('tool_calls') is not None:
            assert not pending, 'prior batch has unpaired calls'
            calls = message['tool_calls']
            assert isinstance(calls, list)
            for item in calls:
                assert isinstance(item, dict)
                assert item.get('type') == 'function'
                assert isinstance(item.get('id'), str) and item['id'].strip()
                assert item['id'] not in pending
                fn = item.get('function')
                assert isinstance(fn, dict)
                assert isinstance(fn.get('name'), str) and fn['name'].strip()
                assert isinstance(fn.get('arguments'), str)
                pending.add(item['id'])
        elif message['role'] == 'tool':
            assert message['tool_call_id'] in pending
            pending.remove(message['tool_call_id'])
        elif pending:
            pytest.fail('tool result pairing interrupted by another message')
    assert pending == set()


@pytest.mark.parametrize('calls', [{}, {'function': {}}, 'not a list', False, 7,
    [{'type': 'function', 'function': {'name': 'lookup', 'arguments': '{}'}}],
    [call(), call(call_id='c1')],
    [{'id': 'c1', 'type': 'function', 'function': None}],
    [{'id': 'c1', 'type': 'function', 'function': []}],
    [{'id': 'c1', 'type': 'function', 'function': {}}],
    [call(name=' ')], [call(args={'index': 1})],
    [{'id': 'c1', 'type': 'custom', 'function': {'name': 'lookup', 'arguments': '{}'}}],
    [None],
])
def test_broken_wire_envelopes_do_not_crash_or_poison_next_input(calls):
    rt, main, executed = setup_runtime()
    rt._accept(main, response(calls), None, [])
    assert executed == []
    assert main.status == 'ready'
    assert any(e['event'] == 'progress_protocol_error' for e in rt.events)
    assert_wire_pairing(rt._messages(main))
    # Recovery is in the same conversation, without making an API call.
    rt._accept(main, response([call(call_id='next')]), None, [])
    assert executed == [('lookup', {'index': 1})]
    assert_wire_pairing(rt._messages(main))


@pytest.mark.parametrize('bad', ['{', '{"index":1,}', '{"index":1,"index":2}',
    '{"index":NaN}', '{"index":Infinity}', '{"index":-Infinity}', '{"index":1e999}'])
def test_pairable_bad_json_returns_error_to_every_call_without_dispatch(bad):
    rt, main, executed = setup_runtime()
    rt._accept(main, response([call(call_id='ok'), call(bad, call_id='bad')]), None, [])
    assert executed == []
    replies = [m for m in main.messages if m['role'] == 'tool']
    assert [m['tool_call_id'] for m in replies] == ['ok', 'bad']
    assert all(json.loads(m['content'])['error'] == 'ValueError' for m in replies)
    assert_wire_pairing(rt._messages(main))


@pytest.mark.parametrize('bad', ['{"index":true}', '{"index":false}',
    '{"index":1,"extra":"unallowed"}', '{}', '{"index":"1"}', '{"index":1.5}'])
def test_one_invalid_business_argument_blocks_whole_business_batch(bad):
    rt, main, executed = setup_runtime()
    rt._accept(main, response([call(call_id='first'), call(bad, call_id='second')]), None, [])
    assert executed == []
    replies = [m for m in main.messages if m['role'] == 'tool']
    assert len(replies) == 2
    assert all(json.loads(m['content'])['error'] == 'ValueError' for m in replies)
    assert_wire_pairing(rt._messages(main))


def test_boolean_event_version_is_rejected_before_collaboration_is_queued():
    rt, main, executed = setup_runtime()
    pending = []
    rt._accept(main, response([call(json.dumps({'operation': 'continue', 'reason': 'inspect',
        'event_version': True}), 'collaborate')]), None, pending)
    assert pending == [] and executed == []
    assert not any(e['event'] == 'collaboration_request' for e in rt.events)
    replies = [m for m in main.messages if m['role'] == 'tool']
    assert 'event_version' in json.loads(replies[0]['content'])['detail']
    assert_wire_pairing(rt._messages(main))


def report(**updates):
    return {'report_id': 'r1', 'summary': 'Record lookup remains to be done',
        'next_step': 'Look up record 1', 'evidence_ids': [],
        'reason': 'Record current work before lookup', **updates}


@pytest.mark.parametrize('report_first', [True, False])
def test_valid_progress_and_business_can_share_one_response(report_first):
    rt, main, executed = setup_runtime()
    progress = call(json.dumps(report()), 'report_progress', 'progress')
    business = call(call_id='business')
    rt._accept(main, response([progress, business] if report_first else [business, progress]), None, [])
    assert executed == [('lookup', {'index': 1})]
    assert main.latest_report == 'r1'
    assert len(rt.archive) == 1
    assert not any(e['event'] in {'progress_protocol_error', 'progress_report_error'} for e in rt.events)
    assert_wire_pairing(rt._messages(main))


@pytest.mark.parametrize('invalid_report', [report(extra='unknown'), report(summary=4),
    report(evidence_ids=[True]), report(signal='unknown'), {'report_id': 'r1'}])
def test_optional_report_schema_error_does_not_cancel_valid_business(invalid_report):
    rt, main, executed = setup_runtime()
    rt._accept(main, response([call(json.dumps(invalid_report), 'report_progress', 'progress'),
                              call(call_id='business')]), None, [])
    assert executed == [('lookup', {'index': 1})]
    assert main.latest_report is None
    replies = {m['tool_call_id']: json.loads(m['content']) for m in main.messages if m['role'] == 'tool'}
    assert replies['progress']['error'] == 'ValueError'
    assert replies['business']['result'] == {'found': True}
    assert sum(e['event'] == 'progress_report_error' for e in rt.events) == 1
    assert_wire_pairing(rt._messages(main))
