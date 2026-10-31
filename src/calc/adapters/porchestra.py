"""Optional POrchestra/ARE integration, with a dependency-free state bridge.

The upstream package remains external and unmodified. Importing this module does
not import ARE, configure credentials, or make model calls.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from importlib import import_module, metadata, util
import json
import os
import sys
from typing import Any, Callable

from calc.state import AgentState, Decision, Evidence, TaskState, WorkItem


class POrchestraDependencyError(RuntimeError):
    """The optional, separately installed upstream runtime is unavailable."""


def dependency_status() -> dict[str, bool]:
    """Check top-level modules without importing the model/runtime stack."""
    return {name: util.find_spec(name) is not None for name in ("are", "porchestra")}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _text_content(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(part, dict) and part.get("type") in {"text", "input_text", "output_text"}
        for part in content
    ):
        return "\n".join(str(part.get("text", "")) for part in content)
    return None


def project_messages(
    messages: list[dict[str, Any]], packet: Any, *, keep_last: int = 6
) -> list[dict[str, Any]]:
    """Replace older text turns with a compiled packet at the actual LLM boundary.

    System instructions and structured/multimodal messages are preserved. A tail
    starting inside tool results is expanded back to its assistant tool call.
    This bounds the selected *history*, not mandatory instructions or attachments.
    The caller archives the complete original request separately.
    """
    if keep_last < 1:
        raise ValueError("keep_last must be positive")
    if not messages:
        return [{"role": "user", "content": packet.content}]
    start = max(0, len(messages) - keep_last)
    while start > 0 and messages[start].get("role") == "tool":
        start -= 1
    selected: set[int] = set()
    for index, message in enumerate(messages):
        content = message.get("content")
        mandatory = message.get("role") in {"system", "developer"}
        structured = content is not None and _text_content(content) is None
        if mandatory or structured or index >= start:
            selected.add(index)
    # Native tool-call conversations must keep complete call/result groups.
    for index, message in enumerate(messages):
        if not message.get("tool_calls"):
            continue
        group = [index]
        cursor = index + 1
        while cursor < len(messages) and messages[cursor].get("role") == "tool":
            group.append(cursor)
            cursor += 1
        if any(item in selected for item in group):
            selected.update(group)
    retained = [deepcopy(messages[index]) for index in sorted(selected)]
    insertion = 0
    while insertion < len(retained) and retained[insertion].get("role") in {"system", "developer"}:
        insertion += 1
    retained.insert(insertion, {
        "role": "user",
        "content": "[CALC selected context; full execution logs remain archived]\n" + packet.content,
    })
    return retained


class POrchestraBridge:
    """Translate native session results into CALC work/evidence without a judge.

    A worker's finish/stop is local. It never marks the whole task successful.
    Pending work survives retirement and is assigned to its receiving agent.
    """

    def __init__(self, state: TaskState, *, compiler: Any = None, runtime: Any = None) -> None:
        if compiler is None:
            from calc.context import ContextCompiler
            compiler = ContextCompiler()
        if runtime is None:
            from calc.lifecycle import LifecycleRuntime
            runtime = LifecycleRuntime(state, compiler=compiler)
        self.state = state
        self.compiler = compiler
        self.runtime = runtime
        self.request_archive: list[dict[str, Any]] = []
        self.context_options: dict[str, tuple[int, str]] = {}

    def ensure_worker(self, worker_id: str, task: str, *, work_id: str | None = None) -> str:
        self.state.agents.setdefault(worker_id, AgentState(worker_id))
        if work_id is None and self.state.agents[worker_id].work_ids:
            return self.state.agents[worker_id].work_ids[0]
        work_id = work_id or f"{worker_id}:task"
        if work_id not in self.state.work_items:
            self.state.add_work(WorkItem(work_id, task, owner=worker_id))
        return work_id

    def compile(self, recipient: str, *, budget: int = 2048, mode: str = "evidence") -> Any:
        return self.compiler.compile(self.state, recipient, budget=budget, mode=mode)

    def archive_and_project(
        self, worker_id: str, messages: list[dict[str, Any]], *, budget: int = 2048, keep_last: int = 6
    ) -> list[dict[str, Any]]:
        original = deepcopy(messages)
        self.state.agents.setdefault(worker_id, AgentState(worker_id))
        work_ids = list(self.state.agents[worker_id].work_ids)
        # ARE sends observations as user turns. Keep them available to the
        # internal recall tool before shortening the model-visible history.
        for message in original:
            if message.get("role") not in {"user", "tool"}:
                continue
            content = _text_content(message.get("content"))
            if not content:
                continue
            digest = sha256(content.encode("utf-8")).hexdigest()[:20]
            self.state.add_evidence(Evidence(
                f"{worker_id}:input:{digest}", content,
                source=f"porchestra:{worker_id}:input_observation", work_ids=work_ids,
            ))
        selected_budget, selected_mode = self.context_options.get(worker_id, (budget, "evidence"))
        packet = self.compile(worker_id, budget=selected_budget, mode=selected_mode)
        projected = project_messages(original, packet, keep_last=keep_last)
        if packet.omitted_evidence_ids:
            projected.insert(0 if projected[0].get("role") not in {"system", "developer"} else 1, {
                "role": "user",
                "content": "Older observations can be retrieved with CALC__read_evidence; "
                           "use evidence_id='' to list IDs. Omitted IDs: "
                           + ", ".join(packet.omitted_evidence_ids[-12:]),
            })
        self.request_archive.append({"agent_id": worker_id, "messages": original})
        self.state.agents.setdefault(worker_id, AgentState(worker_id)).history.append({
            "kind": "model_request", "messages": original,
        })
        self.state.record(
            "porchestra_context_projection", agent_id=worker_id,
            input_messages=len(original), projected_messages=len(projected),
            evidence_ids=list(packet.evidence_ids), work_ids=list(packet.work_ids),
            selected_context_tokens=packet.estimated_tokens,
            original_chars=len(_text(original)), projected_chars=len(_text(projected)),
        )
        return projected

    def read_evidence(self, evidence_id: str = "", *, offset: int = 0, limit: int = 8000) -> dict[str, Any]:
        """Read archived text in bounded chunks, or list IDs without dumping text."""
        if offset < 0 or limit < 1 or limit > 16000:
            raise ValueError("offset must be nonnegative; limit must be in 1..16000")
        if not evidence_id:
            records = list(self.state.evidence.values())
            return {"evidence": [{"id": item.id, "source": item.source, "chars": len(item.content)}
                                 for item in records[offset:offset + min(limit, 100)]],
                    "total": len(records)}
        evidence = self.state.evidence[evidence_id]
        content = evidence.content[offset:offset + limit]
        self.state.record("porchestra_evidence_read", evidence_id=evidence_id,
                          offset=offset, returned_chars=len(content))
        return {"evidence_id": evidence.id, "source": evidence.source, "content": content,
                "offset": offset, "total_chars": len(evidence.content),
                "has_more": offset + len(content) < len(evidence.content)}

    def ingest_result(self, worker_id: str, result: Any) -> None:
        work_id = self.ensure_worker(worker_id, str(result.task))
        worker = self.state.agents[worker_id]
        previous_steps = worker.step_count
        worker.new_evidence_count = 0
        worker.step_count = max(worker.step_count, int(result.steps))
        work = self.state.work_items[work_id]
        sae = result.sae or {}
        for log in result.logs:
            log_type = log.get_type() if callable(getattr(log, "get_type", None)) else ""
            if log_type not in {"observation", "error", "environment_notifications"}:
                continue
            get_content = getattr(log, "get_content_for_llm", None)
            content = get_content() if callable(get_content) else getattr(log, "content", "")
            if not content:
                continue
            text = _text(content)
            digest = sha256(text.encode("utf-8")).hexdigest()[:20]
            evidence = Evidence(
                f"{worker_id}:{log_type}:{digest}", text,
                source=f"porchestra:{worker_id}:{log_type}", work_ids=[work_id],
            )
            if self.state.add_evidence(evidence):
                worker.new_evidence_count += 1
        worker.stagnant_steps = (
            worker.stagnant_steps + 1
            if worker.new_evidence_count == 0 and worker.step_count > previous_steps else 0
        )
        # A model-authored handoff is kept as such, never labelled a raw tool fact.
        summary = str(sae.get("evidence", {}).get("summary") or "")
        if summary:
            digest = sha256(summary.encode("utf-8")).hexdigest()[:20]
            self.state.add_evidence(Evidence(
                f"{worker_id}:handoff:{digest}", summary,
                source=f"porchestra:{worker_id}:model_handoff", work_ids=[work_id],
            ))
        work.result = str(sae.get("result") or sae.get("state") or work.result)
        pending = sae.get("unresolved_items")
        if isinstance(pending, list):
            work.unresolved = [str(item) for item in pending if str(item).strip()]
        declared_status = sae.get("status")
        if result.control == "finish" and not work.unresolved:
            work.status = "done"
        elif result.control in {"finish", "stop"}:
            work.status = "pending"
            if not work.unresolved:
                work.unresolved = [f"Continue unfinished assigned work: {work.goal}"]
        self.state.record(
            "porchestra_local_handoff", agent_id=worker_id, control=result.control,
            declared_status=declared_status, work_status=work.status,
            unresolved=list(work.unresolved), task_success_evaluated=False,
        )

    def apply(self, decision: Decision) -> Any:
        packet = self.runtime.apply(decision)
        self.context_options[packet.recipient] = (decision.context_budget, decision.packet_mode)
        return packet

    def retire(self, worker_id: str, *, recipient: str = "main", budget: int = 2048) -> Any:
        return self.apply(Decision(
            action="merge", agent_id=worker_id, recipient=recipient,
            work_ids=list(self.state.agents[worker_id].work_ids), context_budget=budget,
            rationale="Native session ended locally; preserve evidence and pending obligations.",
        ))


class ProjectedMemory:
    """Native memory operations remain intact; only the rendered input is changed."""

    def __init__(self, native: Any, bridge: POrchestraBridge, *, budget: int = 2048) -> None:
        self.native = native
        self.bridge = bridge
        self.budget = budget

    def format(self) -> str:
        # Native inspections and external notification observations must survive
        # changing the renderer. They are evidence, not completed user duties.
        items = getattr(self.native, "items", [])
        if items:
            work_id = "main:native_observations"
            if work_id not in self.bridge.state.work_items:
                self.bridge.state.add_work(WorkItem(
                    work_id, "Coordinator observations and native handoffs", status="done",
                ))
            for item in items:
                content = _text(item)
                digest = sha256(content.encode("utf-8")).hexdigest()[:20]
                self.bridge.state.add_evidence(Evidence(
                    f"native-memory:{digest}", content, "porchestra:main:native_memory", [work_id],
                ))
        budget, mode = self.bridge.context_options.get("main", (self.budget, "evidence"))
        return self.bridge.compile("main", budget=budget, mode=mode).content

    def __getattr__(self, name: str) -> Any:
        return getattr(self.native, name)


def build_calc_are_agent_class() -> type:
    """Build the optional native subclass lazily, without importing ARE at startup."""
    try:
        native_module = import_module("porchestra.gaia2_agent.agent")
        engine_module = import_module("are.simulation.agents.llm.llm_engine")
        tool_class = import_module("are.simulation.tools").Tool
    except ImportError as exc:
        raise POrchestraDependencyError(
            "Install the pinned POrchestra checkout and its separate ARE environment. "
            "See docs/PORCHESTRA.md; the CALC core works without these optional dependencies."
        ) from exc

    class ProjectionEngine(engine_module.LLMEngine):
        def __init__(self, engine: Any, owner: Any) -> None:
            super().__init__(engine.model_name)
            self.engine = engine
            self.owner = owner

        def chat_completion(self, messages: list[dict[str, Any]], stop_sequences=None, **kwargs: Any):
            worker_id = self.owner.calc_current_worker_id or f"worker-{self.owner.active_attempt}"
            projected = self.owner.calc_bridge.archive_and_project(
                worker_id, messages, budget=self.owner.calc_context_budget,
                keep_last=self.owner.calc_keep_last,
            )
            return self.engine.chat_completion(
                projected, stop_sequences=stop_sequences or [], **kwargs,
            )

        def simple_call(self, prompt: str) -> str:
            response, _ = self.chat_completion([{"role": "user", "content": prompt}])
            return response

        def __getattr__(self, name: str) -> Any:
            return getattr(self.engine, name)

    class RecallEvidenceTool(tool_class):
        name = "CALC__read_evidence"
        description = "Read archived observations by evidence ID; use empty ID to list available records."
        inputs = {
            "evidence_id": {"type": "string", "description": "Evidence ID, or empty string to list IDs."},
            "offset": {"type": "integer", "description": "Nonnegative text or list offset."},
            "limit": {"type": "integer", "description": "Maximum characters (1..16000), or up to 100 IDs."},
        }
        output_type = "any"

        def __init__(self, owner: Any) -> None:
            self.owner = owner
            super().__init__()

        def forward(self, evidence_id: str, offset: int, limit: int) -> dict[str, Any]:
            return self.owner.calc_bridge.read_evidence(evidence_id, offset=offset, limit=limit)

    class CalcAREAgent(native_module.POrchestraAREAgent):
        """Use native tools, timing and session execution with CALC state/projection.

        v0 retains one native active session and defaults to JointController.
        ``projection`` is an explicitly named integration ablation. A custom
        policy may replace the V0 heuristic scorer without replacing tools/ARE.
        """

        def __init__(
            self, *args: Any, calc_policy: Callable | None = None,
            calc_context_budget: int = 2048, calc_keep_last: int = 6,
            calc_control_mode: str | None = None, calc_slice_steps: int = 3, **kwargs: Any,
        ) -> None:
            kwargs.setdefault("poll_period", calc_slice_steps)
            super().__init__(*args, **kwargs)
            from calc.controller import JointController
            self.calc_control_mode = calc_control_mode or os.environ.get("CALC_CONTROL_MODE", "joint")
            if self.calc_control_mode not in JointController.MODES | {"projection"}:
                raise ValueError(f"unknown CALC control mode: {self.calc_control_mode}")
            self.calc_controller = (
                None if self.calc_control_mode == "projection" else
                JointController(self.calc_control_mode, calc_context_budget, calc_slice_steps)
            )
            self.calc_policy = calc_policy
            self.calc_context_budget = calc_context_budget
            self.calc_keep_last = calc_keep_last
            self.calc_bridge: POrchestraBridge | None = None
            self.calc_current_worker_id: str | None = None
            self.calc_next_worker_id: str | None = None

        @property
        def agent_framework(self) -> str:
            return "CalcAREAgent"

        def _prepare(self, scenario: Any, notification_system: Any) -> None:
            super()._prepare(scenario, notification_system)
            state = TaskState(str(scenario.scenario_id), "Awaiting native user notification")
            self.calc_bridge = POrchestraBridge(state)
            self.memory = ProjectedMemory(self.memory, self.calc_bridge, budget=self.calc_context_budget)
            self.sub_llm_engine = ProjectionEngine(self.sub_llm_engine, self)
            self.all_tools["CALC__read_evidence"] = RecallEvidenceTool(self)

        def _main_decision(self) -> dict[str, Any]:
            self.calc_bridge.state.instruction = self.original_task or self.current_task
            proposal = super()._main_decision()
            if proposal.get("action") == "finalize_task":
                return proposal
            worker_id = self.calc_current_worker_id
            worker = self.calc_bridge.state.agents.get(worker_id) if worker_id else None
            if self.calc_policy is not None:
                decision = self.calc_policy(self.calc_bridge.state, deepcopy(proposal))
            elif (self.calc_controller is not None and worker is not None
                  and worker.status == "active" and self.active_session is not None):
                decision = self.calc_controller.decide(self.calc_bridge.state, worker_id)
            else:
                decision = None
            if decision is None:
                return proposal
            if not isinstance(decision, Decision):
                raise TypeError("calc_policy must return Decision or None")
            packet = self.calc_bridge.apply(decision)
            if decision.action in {"merge", "retire", "transfer", "reassign"}:
                worker = self.calc_bridge.state.agents[decision.agent_id]
                if not worker.work_ids or worker.status in {"archived", "retired"}:
                    self.active_session = None
                    self.active_status = "stopped"
                return super()._main_decision()
            params = dict(proposal.get("params") or {})
            params.update(context=packet.content, step_budget=decision.step_budget)
            if decision.action == "spawn":
                self.calc_next_worker_id = decision.agent_id
                params["task_instruction"] = "\n".join(
                    self.calc_bridge.state.work_items[key].goal for key in decision.work_ids
                ) or self.current_task
                return {"action": "delegate_task", "params": params}
            if decision.action in {"continue", "resume"} and self.active_session is not None:
                if decision.agent_id != self.calc_current_worker_id:
                    raise ValueError("CALC v0 can continue only the native active session")
                self.active_status = "revise_requested"
                return {"action": "revise_task", "params": {
                    "context": packet.content, "step_budget": decision.step_budget,
                }}
            return proposal

        def _revise(self, params: dict[str, Any]) -> None:
            revised = dict(params)
            if self.active_session is not None and "context" in revised:
                # Native revise appends context. CALC selects a replacement view,
                # with the old observations retained in its evidence archive.
                self.active_session.context = str(revised.pop("context"))
                self.active_session.revision_notes = []
                self.active_session._needs_refresh = True
            super()._revise(revised)

        def _delegate(self, params: dict[str, Any]) -> None:
            old_worker = self.calc_current_worker_id or f"worker-{self.active_attempt}"
            if self.active_session is not None and old_worker in self.calc_bridge.state.agents:
                self.calc_bridge.retire(old_worker, budget=self.calc_context_budget)
            worker_id = self.calc_next_worker_id or f"worker-{self.active_attempt + 1}"
            self.calc_next_worker_id = None
            self.calc_current_worker_id = worker_id
            instruction = str(params.get("task_instruction") or self.current_task)
            self.calc_bridge.ensure_worker(worker_id, instruction)
            new_params = dict(params)
            supplied = str(params.get("context") or "")
            if supplied:
                digest = sha256(supplied.encode("utf-8")).hexdigest()[:20]
                self.calc_bridge.state.add_evidence(Evidence(
                    f"delegation:{digest}", supplied, "main:delegation",
                    work_ids=list(self.calc_bridge.state.agents[worker_id].work_ids),
                ))
            new_params["context"] = self.calc_bridge.compile(
                worker_id, budget=self.calc_context_budget,
            ).content
            if isinstance(new_params.get("tools"), list):
                new_params["tools"] = list(dict.fromkeys([*new_params["tools"], "CALC__read_evidence"]))
            super()._delegate(new_params)

        def _record_result(self, event: str, result: Any) -> None:
            worker_id = self.calc_current_worker_id or f"worker-{self.active_attempt}"
            self.calc_bridge.ingest_result(worker_id, result)
            super()._record_result(event, result)
            if result.control in {"finish", "stop"}:
                self.calc_bridge.retire(worker_id, budget=self.calc_context_budget)

    return CalcAREAgent


def register_calc_are_agent(*, policy: Callable | None = None, control_mode: str | None = None) -> None:
    """Register ``--agent calc`` alongside upstream agents in the current process."""
    calc_class = build_calc_are_agent_class()
    registration = import_module("porchestra.gaia2_agent.registration")
    registration.patch_are_builders()
    builder_class = import_module("are.simulation.agents.agent_builder").AgentBuilder
    config_class = import_module("are.simulation.agents.agent_config_builder").AgentConfigBuilder
    if getattr(builder_class, "_calc_registered", False):
        return
    previous_build = builder_class.build
    previous_list = builder_class.list_agents
    previous_config = config_class.build

    def config_build(self: Any, agent_name: str):
        config = previous_config(self, "porchestra" if agent_name == "calc" else agent_name)
        if agent_name == "calc":
            config.agent_name = "calc"
        return config

    def list_agents(self: Any):
        return list(dict.fromkeys([*previous_list(self), "calc"]))

    def build(self: Any, agent_config: Any, env=None, mock_responses=None):
        if agent_config.get_agent_name() != "calc":
            return previous_build(self, agent_config, env, mock_responses)
        native_config = deepcopy(agent_config)
        native_config.agent_name = "porchestra"
        native = previous_build(self, native_config, env, mock_responses)
        fields = (
            "log_callback", "llm_engine", "sub_llm_engine", "time_manager", "env", "max_turns",
            "pause_env", "resume_env", "simulated_generation_time_config", "max_main_decisions_per_turn",
            "max_total_steps", "default_subagent_steps",
        )
        agent = calc_class(
            **{name: getattr(native, name) for name in fields},
            poll_period=int(os.environ.get("CALC_SLICE_STEPS", "3")),
            calc_slice_steps=int(os.environ.get("CALC_SLICE_STEPS", "3")),
            calc_policy=policy, calc_control_mode=control_mode,
        )
        for engine in (agent.llm_engine, agent.sub_llm_engine):
            if hasattr(engine, "context_provider"):
                engine.context_provider = agent.llm_trace_context
        return agent

    config_class.build = config_build
    builder_class.list_agents = list_agents
    builder_class.build = build
    builder_class._calc_registered = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or run the optional CALC/POrchestra adapter.")
    parser.add_argument("command", choices=("check", "run"), nargs="?", default="check")
    parser.add_argument("--mode", choices=("joint", "independent", "lifecycle", "context", "fixed", "projection"))
    parser.add_argument("are_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "check":
        status = dependency_status()
        print(json.dumps({"optional_dependencies": status, "ready": all(status.values())}))
        return 0 if all(status.values()) else 2
    try:
        register_calc_are_agent(control_mode=args.mode)
        entries = metadata.entry_points(group="console_scripts", name="are-benchmark")
        entry = next(iter(entries), None)
        if entry is None:
            raise POrchestraDependencyError("The ARE environment has no are-benchmark console entry point.")
    except POrchestraDependencyError as exc:
        parser.exit(2, str(exc) + "\n")
    forwarded = args.are_args[1:] if args.are_args[:1] == ["--"] else args.are_args
    sys.argv = ["are-benchmark", *forwarded]
    result = entry.load()()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
