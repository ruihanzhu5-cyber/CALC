"""Contract tests with explicit fixtures, not benchmark scores."""
import ast
import json
import sys
from types import SimpleNamespace

import pytest

from calc.benchmarks.appworld import AppWorldAdapter, development_ids, public_instruction


class PublicTask:
    instruction = "update a note"
    datetime = "2023-05-18"
    supervisor = {"first_name": "Test", "last_name": "Person", "email": "test@example.org", "phone_number": "123"}
    db_version = "0.2.0"
    api_docs = SimpleNamespace(function_calling=lambda: [
        {"function": {"name": "notes__set"}}, {"function": {"name": "notes__get"}}])

    @property
    def ground_truth(self):
        raise AssertionError("actor path read ground truth")

    @property
    def difficulty(self):
        raise AssertionError("actor path read difficulty")


@pytest.fixture
def official_contract(monkeypatch):
    instances, evaluations = [], []
    class World:
        def __init__(self, **kwargs):
            assert kwargs["load_ground_truth"] is False
            self.task, self.value = PublicTask(), None
            self.closed = False
            self.saved = False
            instances.append(self)

        def execute(self, code):
            tree = ast.parse(code)
            assert len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)
            call = tree.body[0].value.args[0]
            params = ast.literal_eval(call.keywords[0].value)
            if call.func.attr == "set":
                self.value = params["text"]
            return str(self.value)

        def save_state(self):
            self.saved = True

        def save_logs(self):
            pass

        def close(self):
            self.closed = True

    def evaluate_task(*args, **kwargs):
        assert instances[0].saved
        evaluations.append((args, kwargs))
        return SimpleNamespace(to_dict=lambda: {"success": False, "fixture_only": True})
    monkeypatch.setitem(sys.modules, "appworld", SimpleNamespace(AppWorld=World, evaluate_task=evaluate_task,
                        load_task_ids=lambda **kw: ["train_task"]))
    return instances, evaluations


def test_model_input_allowlist_never_reads_hidden_fields():
    text = public_instruction(PublicTask())
    assert set(json.loads(text)) == {"instruction", "datetime", "supervisor"}
    assert "ground_truth" not in text and "difficulty" not in text


def test_shared_environment_and_variable_free_calls(official_contract):
    adapter = AppWorldAdapter("train_task", "test", {})
    text = "x'); __import__('os').system('not executed') #"
    adapter.invoke("appworld_api", {"app": "notes", "api": "set", "arguments": {"text": text}})
    assert adapter.invoke("appworld_api", {"app": "notes", "api": "get", "arguments": {}}) == text
    assert len(official_contract[0]) == 1 and adapter.tool_calls == 2
    with pytest.raises(RuntimeError, match="during actor"):
        adapter.evaluate()
    assert official_contract[1] == []
    adapter.finish()
    adapter.evaluate()
    assert len(official_contract[1]) == 1
    with pytest.raises(RuntimeError, match="ended"):
        adapter.invoke("appworld_api", {"app": "notes", "api": "get", "arguments": {}})
    adapter.close()


@pytest.mark.parametrize("api", ["evaluate", "__dict__", "get); evil()"])
def test_nonpublic_or_code_api_rejected(official_contract, api):
    adapter = AppWorldAdapter("train_task", "test", {})
    with pytest.raises(ValueError):
        adapter.invoke("appworld_api", {"app": "notes", "api": api, "arguments": {}})
    assert adapter.tool_calls == 0


def test_only_development_splits(official_contract):
    assert development_ids("train") == ["train_task"]
    for split in ("test_normal", "test_challenge", "all"):
        with pytest.raises(ValueError, match="train/dev"):
            development_ids(split)


def test_reference_loading_cannot_be_enabled_in_config(official_contract):
    with pytest.raises(ValueError, match="isolation"):
        AppWorldAdapter("train_task", "test", {"load_ground_truth": True})


def test_shared_session_keeps_official_save_then_evaluate_order(official_contract):
    adapter = AppWorldAdapter('train_task', 'test-session', {})
    session = adapter.session()
    port = session.actor_environment()
    assert port.events is None
    port.invoke('appworld_api', {'app': 'notes', 'api': 'set', 'arguments': {'text': 'hello'}})
    assert adapter.world.saved is False
    session.finish()
    assert session.evaluate('done')['fixture_only'] is True
    assert adapter.phase == 'evaluated'
    session.close()
    assert adapter.world.closed


def test_official_execution_failure_remains_a_failure_with_original_text(official_contract):
    adapter = AppWorldAdapter('train_task', 'execution-failure', {})
    failure = 'Execution failed. Traceback:\nValueError: official API rejected the request'
    adapter.world.execute = lambda code: failure
    with pytest.raises(RuntimeError) as caught:
        adapter.session().actor_environment().invoke('appworld_api', {
            'app': 'notes', 'api': 'get', 'arguments': {}})
    assert str(caught.value) == failure
    assert adapter.tool_calls == 1
    assert official_contract[1] == []


def test_official_failure_is_recorded_as_runtime_tool_error(official_contract):
    from calc.adaptive import AdaptiveRuntime
    from calc.llm import ChatResponse, Usage
    adapter = AppWorldAdapter('train_task', 'runtime-failure', {})
    failure = 'Execution failed. Traceback:\nKeyError: missing record'
    adapter.world.execute = lambda code: failure
    rt = AdaptiveRuntime(strong=object(), weak=object(), tools=adapter.tools,
                         invoke=adapter.session().actor_environment().invoke,
                         progress_checkpoints=False, tool_loading='all')
    actor = rt._new('read the note', None, 'strong', [])
    message = {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'failure1', 'type': 'function', 'function': {'name': 'appworld_api',
         'arguments': json.dumps({'app': 'notes', 'api': 'get', 'arguments': {}})}}]}
    rt._accept(actor, ChatResponse(message, 'tool_calls', Usage(), 0), None, [])
    errors = [event for event in rt.events if event['event'] == 'tool_error']
    assert len(errors) == 1 and errors[0]['error'] == 'RuntimeError'
    output = json.loads(actor.messages[-1]['content'])
    assert output == {'error': 'RuntimeError', 'detail': failure}
    assert not actor.evidence  # The failed call is not archived as successful evidence.
    assert official_contract[1] == []


def test_appworld_completion_classification_uses_public_api_only(official_contract):
    adapter = AppWorldAdapter('train_task', 'submission-classification', {})
    classifier = adapter.session().actor_environment().is_final_submission
    assert classifier('appworld_api', {'app': 'supervisor', 'api': 'complete_task'}) is True
    assert classifier('appworld_api', {'app': 'notes', 'api': 'complete_task'}) is False
    assert classifier('appworld_api', {'app': 'supervisor', 'api': 'show_profile'}) is False
    assert classifier('other', {'app': 'supervisor', 'api': 'complete_task'}) is False
    assert official_contract[1] == [] and adapter.tool_calls == 0


@pytest.mark.parametrize('arguments', ['{}', '{"text":"hello"}', [], None])
def test_arguments_require_direct_object_without_second_json_decode(official_contract, arguments):
    adapter = AppWorldAdapter('train_task', 'direct-arguments', {})
    with pytest.raises(ValueError, match='arguments must be a JSON object'):
        adapter.invoke('appworld_api', {'app': 'notes', 'api': 'set', 'arguments': arguments})
    assert adapter.tool_calls == 0


def test_legacy_double_encoded_parameter_name_is_rejected(official_contract):
    adapter = AppWorldAdapter('train_task', 'no-legacy-interface', {})
    with pytest.raises(ValueError, match='documented AppWorld API interface'):
        adapter.invoke('appworld_api', {'app': 'notes', 'api': 'set', 'arguments_json': '{}'})
    assert adapter.tool_calls == 0


def test_tool_schema_declares_direct_arbitrary_api_arguments():
    from calc.benchmarks.appworld import API_TOOL
    parameters = API_TOOL['function']['parameters']
    assert parameters['required'] == ['app', 'api', 'arguments']
    assert parameters['properties']['arguments'] == {'type': 'object', 'additionalProperties': True}
    assert 'arguments_json' not in parameters['properties']
