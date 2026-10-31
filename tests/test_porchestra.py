from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from calc.adapters import porchestra
from calc.state import Decision, Evidence, TaskState, WorkItem


def worker_state():
    state = TaskState("dev-1", "Read the report and prepare an answer.")
    state.add_work(WorkItem("investigate", "Verify the second claim", owner="worker-1",
                            unresolved=["Check source version"]))
    state.add_evidence(Evidence("source-1", "Report version 2 says 42.", "tool:report", ["investigate"]))
    return state


def test_local_stop_preserves_evidence_pending_and_task_semantics():
    state = worker_state()
    bridge = porchestra.POrchestraBridge(state)
    bridge.ingest_result("worker-1", SimpleNamespace(
        task="Verify the second claim", steps=3, logs=[], control="stop",
        sae={"state": "Found the report", "evidence": {"summary": "Report says 42"}},
    ))
    packet = bridge.retire("worker-1")
    assert state.work_items["investigate"].owner == "main"
    assert state.work_items["investigate"].status == "pending"
    assert state.work_items["investigate"].unresolved == ["Check source version"]
    assert state.agents["worker-1"].status == "archived"
    assert "Report version 2" in packet.content
    assert not any(event.get("task_success_evaluated") for event in state.events)


def test_partial_transfer_does_not_end_remaining_worker():
    state = worker_state()
    state.add_work(WorkItem("another", "Independently check arithmetic", owner="worker-1"))
    bridge = porchestra.POrchestraBridge(state)
    bridge.apply(Decision("transfer", "worker-1", recipient="main", work_ids=["investigate"]))
    assert state.work_items["investigate"].owner == "main"
    assert state.work_items["another"].owner == "worker-1"
    assert state.agents["worker-1"].status == "active"


def test_native_finish_is_not_automatically_official_completion():
    state = worker_state()
    bridge = porchestra.POrchestraBridge(state)
    result = SimpleNamespace(task="Investigate", steps=2, logs=[], control="finish",
                             sae={"state": "A local answer", "evidence": {}})
    bridge.ingest_result("worker-1", result)
    assert state.work_items["investigate"].status == "pending"
    result.sae.update(status="done", unresolved_items=[])
    bridge.ingest_result("worker-1", result)
    assert state.work_items["investigate"].status == "done"

    plain = TaskState("native-finish", "Answer the question")
    plain.add_work(WorkItem("worker-1:task", "Investigate", owner="worker-1"))
    plain_bridge = porchestra.POrchestraBridge(plain)
    result.sae = {"state": "Local investigation complete", "evidence": {}}
    plain_bridge.ingest_result("worker-1", result)
    assert plain.work_items["worker-1:task"].status == "done"
    assert not any(event.get("task_success_evaluated") for event in plain.events)


def test_model_boundary_projection_archives_and_supports_recall():
    state = worker_state()
    bridge = porchestra.POrchestraBridge(state)
    messages = [{"role": "system", "content": "Use the tools."}]
    messages.extend({"role": "user", "content": f"observation-{index}: " + "x" * 300}
                    for index in range(20))
    original = deepcopy(messages)
    projected = bridge.archive_and_project("worker-1", messages, budget=500, keep_last=2)
    assert messages == original
    assert bridge.request_archive[0]["messages"] == original
    assert len(str(projected)) < len(str(original))
    assert projected[0] == original[0]
    assert projected[-1] == original[-1]
    catalog = bridge.read_evidence("")
    evidence_id = next(item["id"] for item in catalog["evidence"] if item["chars"] > 300)
    first = bridge.read_evidence(evidence_id, limit=10)
    assert first["has_more"]
    assert len(first["content"]) == 10
    with pytest.raises(ValueError):
        bridge.read_evidence(evidence_id, offset=-1)


def test_projected_memory_keeps_native_storage_separate():
    state = worker_state()
    bridge = porchestra.POrchestraBridge(state)
    bridge.retire("worker-1")
    native = SimpleNamespace(items=[], add=lambda value: native.items.append(value))
    memory = porchestra.ProjectedMemory(native, bridge)
    memory.add("original native event")
    assert native.items == ["original native event"]
    assert "Check source version" in memory.format()
    assert "Report version 2" in memory.format()


def test_tool_pairs_and_multimodal_inputs_remain_valid():
    messages = [
        {"role": "system", "content": "Instructions"},
        {"role": "assistant", "content": [{"type": "image", "image": "asset"}],
         "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current"},
    ]
    packet = SimpleNamespace(content="Selected evidence")
    projected = porchestra.project_messages(messages, packet, keep_last=1)
    assert messages[1] in projected and messages[2] in projected
    assert messages[3] not in projected
    assert projected[-1] == messages[-1]


def test_text_blocks_can_be_projected_but_attachments_survive():
    packet = SimpleNamespace(content="Current state")
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "old text"}]},
        {"role": "user", "content": [{"type": "image_url", "image_url": "attachment"}]},
        {"role": "user", "content": "new"},
    ]
    projected = porchestra.project_messages(messages, packet, keep_last=1)
    assert messages[0] not in projected
    assert messages[1] in projected


def test_missing_optional_dependencies_have_actionable_error(monkeypatch):
    monkeypatch.setattr(porchestra, "import_module", lambda _: (_ for _ in ()).throw(ImportError("missing ARE")))
    with pytest.raises(porchestra.POrchestraDependencyError, match="docs/PORCHESTRA.md"):
        porchestra.build_calc_are_agent_class()


def test_native_subclass_uses_actual_projection_engine_and_local_finish(monkeypatch):
    calls = []

    class Engine:
        model_name = "test-engine"

        def __init__(self, model_name="test-engine"):
            self.model_name = model_name

        def chat_completion(self, messages, **kwargs):
            calls.append(deepcopy(messages))
            return "response", {"tokens": 1}

    class Native:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.active_attempt = 0
            self.active_session = None
            self.current_task = "Read the source"
            self.original_task = "Read the source"
            self.native_decisions = 0

        def _main_decision(self):
            self.native_decisions += 1
            return {"action": "delegate_task", "params": {"task_instruction": "Continue research"}}

        def _prepare(self, scenario, notification_system):
            self.all_tools = {}
            self.memory = SimpleNamespace(items=[])

        def _delegate(self, params):
            self.active_attempt += 1
            self.active_session = object()
            self.sub_llm_engine.chat_completion([
                {"role": "system", "content": "Native tool instructions"},
                *[{"role": "user", "content": "observation " + "z" * 600} for _ in range(10)],
                {"role": "user", "content": "latest tool result"},
            ])

        def _record_result(self, event, result):
            if result.control in {"finish", "stop"}:
                self.active_session = None

    class Tool:
        def __init__(self):
            return None

    modules = {
        "porchestra.gaia2_agent.agent": SimpleNamespace(POrchestraAREAgent=Native),
        "are.simulation.agents.llm.llm_engine": SimpleNamespace(LLMEngine=Engine),
        "are.simulation.tools": SimpleNamespace(Tool=Tool),
    }
    monkeypatch.setattr(porchestra, "import_module", modules.__getitem__)
    cls = porchestra.build_calc_are_agent_class()
    agent = cls(sub_llm_engine=Engine(), calc_keep_last=1)
    agent._prepare(SimpleNamespace(scenario_id="scenario-1"), None)
    agent._delegate({"task_instruction": "Read source", "tools": []})
    assert agent.calc_controller.mode == "joint"
    assert "CALC selected context" in str(calls[0])
    assert len(agent.calc_bridge.request_archive[0]["messages"]) > len(calls[0])
    agent._record_result("delegate", SimpleNamespace(
        task="Read source", steps=2, logs=[], control="stop", sae={"state": "Need another check"},
    ))
    assert agent.active_session is None
    assert agent.calc_bridge.state.work_items["worker-1:task"].owner == "main"
    assert agent.calc_bridge.state.work_items["worker-1:task"].status == "pending"
    assert "CALC__read_evidence" in agent.all_tools

    # Default JointController actually changes lifecycle, rather than merely
    # projecting context behind the native policy's unchanged decisions.
    agent._delegate({"task_instruction": "Another investigation", "tools": []})
    worker = agent.calc_bridge.state.agents["worker-2"]
    worker.stagnant_steps = 3
    worker.new_evidence_count = 0
    before = agent.native_decisions
    agent._main_decision()
    assert worker.status == "archived"
    assert agent.calc_bridge.state.work_items["worker-2:task"].owner == "main"
    assert agent.native_decisions == before + 2
    assert any(event["event"] == "lifecycle" and event["decision"]["action"] == "transfer"
               for event in agent.calc_bridge.state.events)


def test_boundary_contribution_is_incremental_not_lifetime_total():
    state = worker_state()
    bridge = porchestra.POrchestraBridge(state)
    log = SimpleNamespace(get_type=lambda: "observation", get_content_for_llm=lambda: "new tool fact")
    result = SimpleNamespace(task="Investigate", steps=1, logs=[log], control="poll", sae=None)
    bridge.ingest_result("worker-1", result)
    assert state.agents["worker-1"].new_evidence_count == 1
    result.steps = 2
    bridge.ingest_result("worker-1", result)
    assert state.agents["worker-1"].new_evidence_count == 0
    assert state.agents["worker-1"].stagnant_steps == 1


def test_native_inspection_is_preserved_in_main_projection():
    bridge = porchestra.POrchestraBridge(TaskState("t", "Inspect the calendar"))
    native = SimpleNamespace(items=[{"kind": "inspection", "content": "Meeting moved to Tuesday"}])
    memory = porchestra.ProjectedMemory(native, bridge)
    assert "Meeting moved to Tuesday" in memory.format()
    assert any(evidence.source == "porchestra:main:native_memory" for evidence in bridge.state.evidence.values())


def test_registration_defaults_to_joint_and_preserves_native_name(monkeypatch):
    class Engine:
        model_name = "test-engine"

        def __init__(self, model_name="test-engine"):
            self.model_name = model_name

    class Native:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Config:
        def __init__(self, name):
            self.agent_name = name

        def get_agent_name(self):
            return self.agent_name

    class ConfigBuilder:
        def build(self, name):
            return Config(name)

    class Builder:
        def list_agents(self):
            return ["porchestra"]

        def build(self, config, env=None, mock_responses=None):
            return Native(
                log_callback=lambda *_: None, llm_engine=Engine(), sub_llm_engine=Engine(),
                time_manager=None, env=env, max_turns=1, pause_env=None, resume_env=None,
                simulated_generation_time_config=None, max_main_decisions_per_turn=8,
                max_total_steps=300, default_subagent_steps=30, _e2e_poll_period=0,
            )

    modules = {
        "porchestra.gaia2_agent.agent": SimpleNamespace(POrchestraAREAgent=Native),
        "are.simulation.agents.llm.llm_engine": SimpleNamespace(LLMEngine=Engine),
        "are.simulation.tools": SimpleNamespace(Tool=object),
        "porchestra.gaia2_agent.registration": SimpleNamespace(patch_are_builders=lambda: None),
        "are.simulation.agents.agent_builder": SimpleNamespace(AgentBuilder=Builder),
        "are.simulation.agents.agent_config_builder": SimpleNamespace(AgentConfigBuilder=ConfigBuilder),
    }
    monkeypatch.setattr(porchestra, "import_module", modules.__getitem__)
    monkeypatch.delenv("CALC_CONTROL_MODE", raising=False)
    porchestra.register_calc_are_agent()
    config = ConfigBuilder().build("calc")
    agent = Builder().build(config)
    assert agent.calc_controller.mode == "joint"
    assert agent.poll_period == 3
    assert config.get_agent_name() == "calc"
    assert type(Builder().build(ConfigBuilder().build("porchestra"))) is Native
    assert Builder().list_agents() == ["porchestra", "calc"]


def _bootstrap_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_baselines.py"
    spec = importlib.util.spec_from_file_location("calc_baseline_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_lock_pins_three_sources():
    module = _bootstrap_module()
    locked = module.load_lock(module.DEFAULT_LOCK)
    assert {repo["name"] for repo in locked} == {"POrchestra", "CLM", "BrowseComp-Plus"}
    assert all(len(repo["commit"]) == 40 for repo in locked)
    assert "http.sslBackend" not in " ".join(module.git_command("git", None, "status"))
    assert "http.sslBackend=openssl" in module.git_command("git", "openssl", "status")


def test_bootstrap_check_does_not_fetch_or_mutate(monkeypatch):
    module = _bootstrap_module()
    monkeypatch.setattr(module, "run_git", lambda *args, **kwargs: pytest.fail("must not call git for missing dir"))
    destination = Path(__file__).resolve().parents[1] / ".never-created-by-check-test"
    assert not destination.exists()
    result = module.bootstrap(
        [{"name": "missing", "url": "https://github.com/test/repo.git", "commit": "a" * 40}],
        destination, "git", check_only=True,
    )
    assert result[0]["status"] == "missing"
    assert not destination.exists()
