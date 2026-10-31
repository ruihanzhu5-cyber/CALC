"""Compile bounded model input views while retaining the original state."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Callable

from calc.state import TaskState


class ContextBudgetError(ValueError):
    """Required task state cannot fit the selected context budget."""


def estimate_tokens(text: str) -> int:
    """A conservative byte heuristic for packing, never used as billed usage."""
    return math.ceil(len(text.encode("utf-8")) / 3)


def _contains_fact(content: object, fact: str) -> bool:
    """Inspect retained tool payloads, including JSON-escaped document text."""
    if not fact:
        return False
    if isinstance(content, str):
        if fact in content:
            return True
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return False
        return not isinstance(parsed, str) and _contains_fact(parsed, fact)
    if isinstance(content, dict):
        return any(_contains_fact(value, fact) for value in content.values())
    if isinstance(content, list):
        return any(_contains_fact(value, fact) for value in content)
    return False


@dataclass
class ContextPacket:
    recipient: str
    content: str
    evidence_ids: list[str]
    work_ids: list[str]
    estimated_tokens: int
    omitted_evidence_ids: list[str] = field(default_factory=list)
    mode: str = "evidence"

    @property
    def text(self) -> str:
        return self.content


class ContextCompiler:
    def __init__(self, token_counter: Callable[[str], int] = estimate_tokens) -> None:
        self.count = token_counter

    def compile(
        self, state: TaskState, recipient: str, work_ids: list[str] | None = None,
        budget: int = 2048, mode: str = "evidence",
    ) -> ContextPacket:
        if mode not in {"evidence", "recent", "full", "state"}:
            raise ValueError(f"unknown packet mode: {mode}")
        if work_ids is None:
            work_ids = [work.id for work in state.work_items.values() if work.owner == recipient]
        works = [state.work_items[key] for key in work_ids]
        mandatory = {
            "task": state.instruction,
            "recipient": recipient,
            "work": [{"id": work.id, "goal": work.goal, "status": work.status,
                      "unresolved": work.unresolved, "result": work.result} for work in works],
        }
        content = json.dumps(mandatory, ensure_ascii=False, separators=(",", ":"))
        if self.count(content) > budget:
            raise ContextBudgetError(
                f"required task and obligations need {self.count(content)} estimated tokens; budget={budget}"
            )
        wanted = list(dict.fromkeys(key for work in works for key in work.evidence_ids))
        selected: list[str] = []

        # Each evidence block is indivisible: a citation without its fact is not a retained fact.
        if mode in {"evidence", "full"}:
            for key in reversed(wanted):
                evidence = state.evidence.get(key)
                if evidence is None:
                    continue
                block = "\n" + json.dumps({"evidence_id": key, "source": evidence.source,
                    "version": evidence.version, "content": evidence.content}, ensure_ascii=False)
                if self.count(content + block) <= budget:
                    content += block
                    selected.append(key)

        if mode in {"recent", "full"}:
            owners = list(dict.fromkeys([work.owner for work in works] + [recipient]))
            history = [message for owner in owners if owner in state.agents
                       for message in state.agents[owner].history if not message.get("context_view")]
            retained: list[str] = []
            for message in reversed(history):
                block = json.dumps(message, ensure_ascii=False, default=str)
                candidate = content + "\nRECENT HISTORY\n" + "\n".join(reversed([*retained, block]))
                if self.count(candidate) <= budget:
                    retained.append(block)
                    for key in message.get("evidence_ids", []):
                        fact = state.evidence.get(key)
                        if key in wanted and key not in selected and fact and _contains_fact(message.get("content"), fact.content):
                            selected.append(key)
            if retained:
                content += "\nRECENT HISTORY\n" + "\n".join(reversed(retained))
        return ContextPacket(recipient, content, selected, list(work_ids), self.count(content),
                             [key for key in wanted if key not in selected], mode)

    def messages(self, packet: ContextPacket) -> list[dict[str, str]]:
        """This view, rather than archived raw history, is passed to a chat model."""
        return [
            {"role": "system", "content": "Complete the assigned work using the supplied state and tools."},
            {"role": "user", "content": packet.content},
        ]
