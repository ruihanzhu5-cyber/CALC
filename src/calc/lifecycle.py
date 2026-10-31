"""Apply lifecycle decisions together with work and evidence transfer."""

from __future__ import annotations

from dataclasses import asdict

from calc.context import ContextCompiler, ContextPacket
from calc.state import AgentState, Decision, TaskState


class LifecycleRuntime:
    def __init__(self, state: TaskState, compiler: ContextCompiler | None = None) -> None:
        self.state = state
        self.compiler = compiler or ContextCompiler()
        self.packets: dict[str, ContextPacket] = {}

    def apply(self, decision: Decision) -> ContextPacket:
        state = self.state
        action = decision.action
        if action not in {"spawn", "continue", "transfer", "merge", "retire", "resume", "reassign"}:
            raise ValueError(f"unknown lifecycle action: {action}")
        if decision.agent_id == "main" and action in {"retire", "transfer", "merge"}:
            raise ValueError("Main remains the task coordinator")
        source = state.agents.get(decision.agent_id)
        if source is None and action != "spawn":
            raise KeyError(decision.agent_id)
        owned = [work.id for work in state.work_items.values() if work.owner == decision.agent_id]
        work_ids = list(decision.work_ids or owned)
        for key in work_ids:
            if key not in state.work_items:
                raise KeyError(key)
        transferring = action in {"transfer", "merge", "retire", "reassign"}
        recipient = decision.recipient if transferring else decision.agent_id
        if action in {"merge", "retire"}:
            work_ids = owned
        if action in {"transfer", "merge", "retire"}:
            for key in work_ids:
                if state.work_items[key].owner != decision.agent_id:
                    raise ValueError(f"{decision.agent_id} does not own {key}")
        if action == "spawn" and source is not None:
            raise ValueError(f"agent already exists; use resume: {decision.agent_id}")
        # Compile before mutating ownership: insufficient budgets leave a resumable source.
        view_work_ids = list(dict.fromkeys(
            [work.id for work in state.work_items.values() if work.owner == recipient] + work_ids
        ))
        packet = self.compiler.compile(state, recipient, view_work_ids, decision.context_budget, decision.packet_mode)
        if action == "continue" and source is not None and source.status != "active":
            raise ValueError(f"cannot continue {source.status} agent; use resume")
        target = state.agents.setdefault(recipient, AgentState(recipient))
        if action in {"spawn", "resume", "reassign", "transfer", "merge", "retire"}:
            for key in work_ids:
                work = state.work_items[key]
                old_owner = state.agents.get(work.owner)
                if old_owner and key in old_owner.work_ids:
                    old_owner.work_ids.remove(key)
                work.owner = recipient
                if key not in target.work_ids:
                    target.work_ids.append(key)
            target.status = "active"
        if transferring and source is not None:
            source.status = "active" if any(work.owner == source.id for work in state.work_items.values()) else "archived"
            # A terminal retire of completed work can keep archived assignments while preventing scheduling.
            if action == "retire":
                source.status = "archived"
        elif action == "resume":
            target.status = "active"
        self.packets[recipient] = packet
        state.record("lifecycle", decision=asdict(decision), recipient=recipient,
                     transferred_work_ids=work_ids, packet=asdict(packet))
        return packet
