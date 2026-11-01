"""An offline integration example. This is not a benchmark evaluation."""

from __future__ import annotations

from calc.context import ContextCompiler
from calc.controller import JointController
from calc.lifecycle import LifecycleRuntime
from calc.state import Decision, Evidence, TaskState, WorkItem


def run_demo() -> dict:
    state = TaskState("offline-handoff", "Find the release date and verify the project alias.")
    state.add_work(WorkItem("investigate", "Verify project alias and release date",
                            unresolved=["Confirm the alias refers to the same project"]))
    runtime = LifecycleRuntime(state)
    runtime.apply(Decision("spawn", "researcher", work_ids=["investigate"]))
    state.add_evidence(Evidence("doc-1", "Project Aurora was also called Dawn; release: 2026-09-18.",
                                "fixture://project-history", ["investigate"]))
    worker = state.agents["researcher"]
    worker.history.append({"role": "tool", "content": "Read project history", "evidence_ids": ["doc-1"]})
    worker.step_count = 4
    worker.stagnant_steps = 2
    worker.new_evidence_count = 0
    controller = JointController(context_budget=1024)
    candidates = controller.candidates(state, "researcher")
    decision = controller.decide(state, "researcher")
    packet = runtime.apply(decision)
    return {"kind": "offline_integration_demo", "benchmark_score": None,
            "selected_action": decision.action, "selected_context": decision.packet_mode,
            "owner_after": state.work_items["investigate"].owner,
            "source_status": worker.status, "archived_history_length": len(worker.history),
            "candidate_scores": [{"action": item.action, "packet": item.packet_mode,
                                  "score": item.score} for item in candidates],
            "next_model_messages": ContextCompiler().messages(packet), "state": state.to_dict()}
