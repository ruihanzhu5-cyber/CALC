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
    adapter.invoke("appworld_api", {"app": "notes", "api": "set", "arguments_json": json.dumps({"text": text})})
    assert adapter.invoke("appworld_api", {"app": "notes", "api": "get", "arguments_json": "{}"}) == text
    assert len(official_contract[0]) == 1 and adapter.tool_calls == 2
    with pytest.raises(RuntimeError, match="during actor"):
        adapter.evaluate()
    assert official_contract[1] == []
    adapter.finish()
    adapter.evaluate()
    assert len(official_contract[1]) == 1
    with pytest.raises(RuntimeError, match="ended"):
        adapter.invoke("appworld_api", {"app": "notes", "api": "get", "arguments_json": "{}"})
    adapter.close()


@pytest.mark.parametrize("api", ["evaluate", "__dict__", "get); evil()"])
def test_nonpublic_or_code_api_rejected(official_contract, api):
    adapter = AppWorldAdapter("train_task", "test", {})
    with pytest.raises(ValueError):
        adapter.invoke("appworld_api", {"app": "notes", "api": api, "arguments_json": "{}"})
    assert adapter.tool_calls == 0


def test_only_development_splits(official_contract):
    assert development_ids("train") == ["train_task"]
    for split in ("test_normal", "test_challenge", "all"):
        with pytest.raises(ValueError, match="train/dev"):
            development_ids(split)


def test_reference_loading_cannot_be_enabled_in_config(official_contract):
    with pytest.raises(ValueError, match="isolation"):
        AppWorldAdapter("train_task", "test", {"load_ground_truth": True})
