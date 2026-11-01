"""An executable V0 joint scorer, with a small replaceable value-model interface."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from calc.context import ContextBudgetError, ContextCompiler, ContextPacket
from calc.state import Decision, TaskState


class ValueModel(Protocol):
    def score(self, state: TaskState, decision: Decision, packet: ContextPacket) -> float: ...


class HeuristicValueModel:
    """Conditional continuation/transfer value, not an oracle contribution estimate.

    Evidence coverage interacts with transfer because lost work must be reacquired.
    New observations and remaining unknowns support continued independent work.
    """

    def score(self, state: TaskState, decision: Decision, packet: ContextPacket) -> float:
        agent = state.agents[decision.agent_id]
        works = [state.work_items[key] for key in decision.work_ids]
        unfinished = sum(work.status != "done" for work in works)
        unknowns = sum(len(work.unresolved) for work in works)
        needed = {key for work in works for key in work.evidence_ids}
        coverage = len(needed.intersection(packet.evidence_ids)) / max(1, len(needed))
        if not needed:
            coverage = 1.0
        progress = min(2.0, agent.new_evidence_count / max(1, agent.stagnant_steps + 1))
        stagnation = min(3.0, float(agent.stagnant_steps))
        input_cost = packet.estimated_tokens / max(1, decision.context_budget)
        if decision.action == "transfer":
            return 0.9 + 0.75 * stagnation + 2.0 * (1 - unfinished / max(1, len(works))) \
                - 0.65 * progress - 0.12 * unknowns - 3.0 * (1 - coverage) - 0.25 * input_cost
        return 0.5 + 0.7 * progress + 0.12 * unknowns - 0.3 * stagnation - 0.25 * input_cost


class JointController:
    MODES = {"joint", "independent", "lifecycle", "context", "fixed"}

    def __init__(self, mode: str = "joint", context_budget: int = 2048, step_budget: int = 3,
                 value_model: ValueModel | None = None, compiler: ContextCompiler | None = None) -> None:
        if mode not in self.MODES:
            raise ValueError(f"unknown mode: {mode}")
        self.mode = mode
        self.context_budget = context_budget
        self.step_budget = step_budget
        self.value_model = value_model or HeuristicValueModel()
        self.compiler = compiler or ContextCompiler()

    def candidates(self, state: TaskState, agent_id: str) -> list[Decision]:
        agent = state.agents[agent_id]
        work_ids = [key for key in agent.work_ids if state.work_items[key].owner == agent_id]
        result = []
        for action in ("continue", "transfer"):
            if agent_id == "main" and action == "transfer":
                continue
            for mode in ("recent", "evidence"):
                decision = Decision(action, agent_id, "main" if action == "transfer" else agent_id,
                                    list(work_ids), context_budget=self.context_budget,
                                    step_budget=self.step_budget, packet_mode=mode)
                try:
                    view_work_ids = list(dict.fromkeys(
                        [work.id for work in state.work_items.values() if work.owner == decision.recipient]
                        + work_ids
                    ))
                    packet = self.compiler.compile(state, decision.recipient, view_work_ids,
                                                   decision.context_budget, mode)
                except ContextBudgetError:
                    continue
                decision.evidence_ids = packet.evidence_ids
                decision.score = self.value_model.score(state, decision, packet)
                result.append(decision)
        if not result:
            raise ContextBudgetError("no candidate can retain required task state; increase context budget")
        return result

    def decide(self, state: TaskState, agent_id: str) -> Decision:
        candidates = self.candidates(state, agent_id)
        if self.mode == "joint":
            selected = max(candidates, key=lambda item: item.score)
            reason = "joint action/context conditional value"
        elif self.mode in {"fixed", "context"}:
            candidates = [item for item in candidates if item.action == "continue"]
            if self.mode == "fixed":
                selected = next((item for item in candidates if item.packet_mode == "recent"), candidates[0])
            else:
                selected = max(candidates, key=lambda item: len(item.evidence_ids))
            reason = "fixed lifecycle; " + ("adaptive context" if self.mode == "context" else "fixed recent context")
        else:
            # Lifecycle-only sees a standard recent packet. Independent then selects context separately.
            standard = [item for item in candidates if item.packet_mode == "recent"]
            selected = max(standard or candidates, key=lambda item: item.score)
            if self.mode == "independent":
                same_action = [item for item in candidates if item.action == selected.action]
                selected = max(same_action, key=lambda item: (len(item.evidence_ids), -item.context_budget))
            reason = "lifecycle chosen on standard packet; context selected independently"
        return replace(selected, rationale=reason)
