from copy import deepcopy
import json
import pytest
from calc.benchmarks.manta_transport import close_native_cancelled_calls


def test_native_early_stop_marks_only_unexecuted_call_without_changing_results():
    messages = [
        {'role': 'assistant', 'tool_calls': [
            {'id': 'a', 'function': {'name': 'read', 'arguments': '{}'}},
            {'id': 'b', 'function': {'name': 'write', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'a', 'content': 'Repeated identical tool call detected.'},
        {'role': 'user', 'content': 'Based only on the information already gathered, provide your best final answer now. Do not call any more tools.'}]
    original = deepcopy(messages)
    wire, cancelled = close_native_cancelled_calls(messages)
    assert messages == original
    assert wire[:2] == messages[:2]
    assert wire[-1] == messages[-1]
    assert json.loads(wire[2]['content'])['status'] == 'not_executed'
    assert [c['tool_call_id'] for c in cancelled] == ['b']
    assert close_native_cancelled_calls(wire) == (wire, [])


def test_normal_valid_history_unchanged_and_invalid_history_rejected():
    valid = [{'role': 'user', 'content': 'hello'}]
    assert close_native_cancelled_calls(valid) == (valid, [])
    with pytest.raises(ValueError, match='Unmatched'):
        close_native_cancelled_calls([{'role': 'assistant', 'tool_calls': [
            {'id': 'a', 'function': {'name': 'read', 'arguments': '{}'}}]}])
