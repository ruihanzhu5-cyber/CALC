"""Transport parsing contracts; no model requests or benchmark simulation."""
import copy

import pytest

from calc.protocol import parse_tool_calls


def call(arguments='{}', name='lookup', call_id='c1'):
    return {'id': call_id, 'type': 'function',
            'function': {'name': name, 'arguments': arguments}}


def test_empty_batch():
    assert parse_tool_calls([]) == []


def test_preserves_original_envelope_and_json_values():
    original = call('{"城市":"北京","嵌套":{"消息":"你好\\n世界"},"项目":[1,true,null]}')
    original['provider_metadata'] = {'opaque': 'kept'}
    before = copy.deepcopy(original)
    parsed = parse_tool_calls([original])
    assert parsed == [(original, 'lookup', {'城市': '北京', '嵌套': {'消息': '你好\n世界'},
                                          '项目': [1, True, None]})]
    assert parsed[0][0] is original
    assert original == before


def test_version_bool_is_business_validation_not_json_parsing():
    assert parse_tool_calls([call('{"event_version":true}')])[0][2] == {'event_version': True}


@pytest.mark.parametrize('arguments', [
    '', '{', '{"x":1,}', '{"x":}', '```json\n{}\n```', '{} trailing',
    '{"x":"unterminated}', '{"x":"raw\nnewline"}',
])
def test_malformed_json_is_rejected_without_repair(arguments):
    with pytest.raises(ValueError, match=r'tool call\[0\].*lookup.*invalid JSON'):
        parse_tool_calls([call(arguments)])


@pytest.mark.parametrize('arguments', ['null', '[]', '"text"', '3', 'true', 'false'])
def test_only_object_arguments(arguments):
    with pytest.raises(ValueError, match='JSON must be an object'):
        parse_tool_calls([call(arguments)])


@pytest.mark.parametrize('arguments', [
    '{"x":1,"x":2}', '{"nested":{"x":1,"x":2}}',
    '{"array":[{"x":1,"x":2}]}', '{"a":1,"\\u0061":2}',
])
def test_duplicate_keys_at_any_depth_are_rejected(arguments):
    with pytest.raises(ValueError, match='duplicate JSON object key'):
        parse_tool_calls([call(arguments)])


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity', '1e999', '-1e999'])
def test_nonfinite_numbers_are_rejected(constant):
    with pytest.raises(ValueError, match='non-finite JSON number'):
        parse_tool_calls([call('{"nested":[' + constant + ']}')])


@pytest.mark.parametrize('arguments', [{}, [], None, 3, True, b'{}'])
def test_arguments_must_be_a_serialized_string(arguments):
    with pytest.raises(ValueError, match='JSON string'):
        parse_tool_calls([call(arguments)])


@pytest.mark.parametrize('name', ['', '  ', None, 1, [], {}])
def test_invalid_function_name(name):
    with pytest.raises(ValueError, match='function name required'):
        parse_tool_calls([call(name=name)])


@pytest.mark.parametrize('invalid', [None, {}, (), 'calls', 1])
def test_invalid_batch_shape(invalid):
    with pytest.raises(ValueError, match='tool_calls must be a list'):
        parse_tool_calls(invalid)


@pytest.mark.parametrize('invalid', [None, [], 'call', 1])
def test_invalid_call_shape(invalid):
    with pytest.raises(ValueError, match=r'tool call\[0\].*call must be an object'):
        parse_tool_calls([invalid])


@pytest.mark.parametrize('field,value,error', [
    ('id', None, 'call ID required'), ('id', '', 'call ID required'),
    ('id', 3, 'call ID required'), ('type', None, 'type must be function'),
    ('type', 'custom', 'type must be function'), ('function', None, 'function must be an object'),
    ('function', [], 'function must be an object'),
])
def test_required_call_fields(field, value, error):
    invalid = call()
    invalid[field] = value
    with pytest.raises(ValueError, match=error):
        parse_tool_calls([invalid])


def test_duplicate_call_ids_even_for_different_functions():
    with pytest.raises(ValueError, match=r'tool call\[1\].*other.*duplicate call ID'):
        parse_tool_calls([call(), call(name='other')])


def test_second_invalid_call_does_not_mutate_first():
    batch = [call('{"x":1}'), call('{', call_id='c2')]
    before = copy.deepcopy(batch)
    with pytest.raises(ValueError, match=r'tool call\[1\]'):
        parse_tool_calls(batch)
    assert batch == before


def test_errors_do_not_echo_argument_secrets_or_duplicate_key_names():
    for arguments in ['{"private-secret-key":1,"private-secret-key":2}',
                      '{"secret":"credential-do-not-echo",}']:
        with pytest.raises(ValueError) as error:
            parse_tool_calls([call(arguments)])
        assert 'private-secret-key' not in str(error.value)
        assert 'credential-do-not-echo' not in str(error.value)


def test_valid_batch_preserves_order():
    calls = [call('{"x":1}', call_id='c1'), call('{"x":2}', name='other', call_id='c2')]
    assert [(name, args) for _, name, args in parse_tool_calls(calls)] == [
        ('lookup', {'x': 1}), ('other', {'x': 2})]
