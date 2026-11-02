import copy
import json

import pytest

from calc.adaptive import AdaptiveRuntime, function
from calc.llm import ChatResponse, Usage


def response(name, args):
    return ChatResponse({'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'call1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]},
        'tool_calls', Usage.from_response({'prompt_tokens': 3, 'completion_tokens': 1}), 0)


class Capture:
    model = 'offline'

    def __init__(self):
        self.inputs = []

    def complete(self, messages, **kwargs):
        self.inputs.append(copy.deepcopy(kwargs))
        return ChatResponse({'role': 'assistant', 'content': 'done'}, 'stop', Usage(), 0)


def runtime(**kwargs):
    client = Capture()
    return AdaptiveRuntime(strong=client, weak=client,
        tools=[function('Calendar__read', 'Read calendar', {}, []),
               function('Shopping__buy', 'Buy a product', {'id': {'type': 'string'}}, ['id'])],
        invoke=lambda n, a: {'executed': n}, **kwargs)


def test_deferred_tools_change_actual_request_without_duplication_in_history():
    rt = runtime(tool_loading='deferred')
    main = rt._new('task', None, 'strong', [])
    rt._request(main)
    names = [t['function']['name'] for t in rt.clients['strong'].inputs[-1]['tools']]
    assert 'Calendar__read' not in names and 'discover_tools' in names
    found = rt._tool(main, 'discover_tools', {'query': 'calendar'})
    assert [f['name'] for f in found] == ['Calendar__read']
    result = rt._tool(main, 'load_tools', {'names': ['Calendar__read']})
    assert 'parameters' not in json.dumps(result)
    rt._request(main)
    names = [t['function']['name'] for t in rt.clients['strong'].inputs[-1]['tools']]
    assert 'Calendar__read' in names and 'Shopping__buy' not in names
    assert rt._tool(main, 'Calendar__read', {})['result']['executed'] == 'Calendar__read'


def test_unloaded_or_out_of_scope_tools_never_execute():
    rt = runtime(tool_loading='deferred')
    main = rt._new('task', None, 'strong', [])
    with pytest.raises(ValueError, match='not loaded'):
        rt._tool(main, 'Shopping__buy', {'id': 'x'})
    main.allowed_tools = ['Calendar__read']
    with pytest.raises(ValueError, match='outside'):
        rt._tool(main, 'load_tools', {'names': ['Shopping__buy']})


def test_loading_schema_and_guessing_business_call_in_same_batch_rejects_both():
    rt = runtime(tool_loading='deferred')
    main = rt._new('task', None, 'strong', [])
    batch = response('load_tools', {'names': ['Calendar__read']})
    call = copy.deepcopy(response('Calendar__read', {}).message['tool_calls'][0])
    call['id'] = 'call2'
    batch.message['tool_calls'].append(call)
    rt._accept(main, batch, None, [])
    assert main.loaded_tools == [] and rt.archive == {}


def test_skill_procedure_loads_declared_schemas_within_assigned_scope():
    rt = runtime(tool_loading='deferred', skills={'calendar': {
        'description': 'Read events', 'body': 'Inspect times', 'tools': ['Calendar__read']}})
    main = rt._new('task', None, 'strong', [])
    assert rt._tool(main, 'load_skill', {'name': 'calendar'}) == 'Inspect times'
    assert main.loaded_tools == ['Calendar__read']


def test_final_submission_rejects_worker_and_main_with_unfinished_children():
    rt = runtime(is_final_submission=lambda n, a: n == 'Shopping__buy')
    main = rt._new('task', None, 'strong', [])
    child = rt._new('task', main.id, 'weak', [])
    for actor in (main, child):
        with pytest.raises(ValueError, match='only Main'):
            rt._tool(actor, 'Shopping__buy', {'id': 'x'})
    assert rt.archive == {}
    child.status = 'done'
    assert rt._tool(main, 'Shopping__buy', {'id': 'x'})['result']['executed'] == 'Shopping__buy'


@pytest.mark.parametrize('key', ['events', 'contacts', 'emails', 'arbitrary_public_container'])
def test_primary_object_collections_are_not_tied_to_benchmark_field_names(key):
    from calc.progress import collection_facts
    facts = collection_facts({key: [{'id': 1}, {'id': 2}], 'total': 2})
    assert facts[0]['count'] == 2
