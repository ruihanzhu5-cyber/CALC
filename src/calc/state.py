"""Task and evidence state, independent of any particular agent harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import time
from typing import Any


@dataclass
class Evidence:
    id: str
    content: str
    source: str
    work_ids: list[str] = field(default_factory=list)
    version: str = "1"


@dataclass
class WorkItem:
    id: str
    goal: str
    owner: str = "main"
    status: str = "pending"
    evidence_ids: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    result: str = ""


@dataclass
class AgentState:
    id: str
    work_ids: list[str] = field(default_factory=list)
    status: str = "active"
    history: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0
    stagnant_steps: int = 0
    new_evidence_count: int = 0


@dataclass
class Decision:
    action: str
    agent_id: str
    recipient: str = "main"
    work_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    context_budget: int = 2048
    step_budget: int = 3
    packet_mode: str = "evidence"
    rationale: str = ""
    score: float = 0.0


@dataclass
class TaskState:
    task_id: str
    instruction: str
    work_items: dict[str, WorkItem] = field(default_factory=dict)
    agents: dict[str, AgentState] = field(default_factory=lambda: {"main": AgentState("main")})
    evidence: dict[str, Evidence] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def add_work(self, work: WorkItem) -> None:
        if work.id in self.work_items:
            raise ValueError(f"work already exists: {work.id}")
        self.work_items[work.id] = work
        self.agents.setdefault(work.owner, AgentState(work.owner)).work_ids.append(work.id)

    def add_evidence(self, evidence: Evidence) -> bool:
        """Keep immutable IDs; a new resource version needs a new evidence ID."""
        previous = self.evidence.get(evidence.id)
        if previous is not None:
            if previous != evidence:
                raise ValueError(f"evidence ID reused for different content: {evidence.id}")
            return False
        self.evidence[evidence.id] = evidence
        for work_id in evidence.work_ids:
            work = self.work_items.get(work_id)
            if work and evidence.id not in work.evidence_ids:
                work.evidence_ids.append(evidence.id)
        return True

    def record(self, event: str, **details: Any) -> None:
        self.events.append({"event": event, "timestamp": time(), **details})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        return cls(
            task_id=data["task_id"], instruction=data["instruction"],
            work_items={key: WorkItem(**value) for key, value in data.get("work_items", {}).items()},
            agents={key: AgentState(**value) for key, value in data.get("agents", {}).items()},
            evidence={key: Evidence(**value) for key, value in data.get("evidence", {}).items()},
            events=data.get("events", []),
        )
