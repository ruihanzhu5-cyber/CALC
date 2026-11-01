"""Public actor capabilities and host-only evaluation lifecycle.

Design references: Inspect's narrow AgentState and task/solver/scorer separation,
and Deep Agents' explicit backend protocols. This is CALC code, not a source port.
Adapters own official semantics; this layer owns dispatch and lifecycle boundaries.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Protocol


class ToolInvoker(Protocol):
    def __call__(self, name: str, arguments: dict) -> Any: ...


@dataclass(frozen=True)
class ActorEnvironment:
    """Only this view is wired into an actor; no evaluator or private task data."""
    tools: list[dict]
    invoke: ToolInvoker
    context: str
    events: Callable[[], list[dict]] | None


class EvaluationSession:
    """One shared world per task, serial tool commits, host-only final scoring.

    No retries, score conversion, simulated results, or environment cloning.
    A failed finalization/scoring remains failed and cannot be automatically repeated.
    Model concurrency belongs to the agent runtime, not this dispatch lock.
    """
    def __init__(self, *, tools: list[dict], invoke: ToolInvoker, context: str,
                 evaluate: Callable[[str], Any], close: Callable[[], None] | None,
                 finish: Callable[[], None] | None = None,
                 events: Callable[[], list[dict]] | None = None):
        names = [t['function']['name'] for t in tools]
        if len(names) != len(set(names)):
            raise ValueError('duplicate public tool names')
        self._tools, self._names = deepcopy(tools), frozenset(names)
        self._invoke, self._events = invoke, events
        self._evaluate, self._finish, self._close = evaluate, finish, close
        self._context, self._lock = context, RLock()
        self.phase = 'execute'

    def actor_environment(self) -> ActorEnvironment:
        return ActorEnvironment(deepcopy(self._tools), self.invoke, self._context,
                                self.poll if self._events is not None else None)

    def invoke(self, name: str, arguments: dict) -> Any:
        with self._lock:
            if self.phase != 'execute':
                raise RuntimeError('task execution has ended')
            if name not in self._names:
                raise ValueError('tool not in public catalog')
            if not isinstance(arguments, dict):
                raise TypeError('tool arguments must be an object')
            return self._invoke(name, deepcopy(arguments))

    def poll(self) -> list[dict]:
        with self._lock:
            if self.phase != 'execute':
                raise RuntimeError('task execution has ended')
            if self._events is None:
                raise RuntimeError('environment does not expose asynchronous events')
            return self._events()

    def finish(self) -> None:
        with self._lock:
            if self.phase != 'execute':
                raise RuntimeError('finish may only be called once')
            self.phase = 'finalizing'
            if self._finish is not None:
                self._finish()
            self.phase = 'evaluation'

    def evaluate(self, answer: str) -> Any:
        with self._lock:
            if self.phase != 'evaluation':
                raise RuntimeError('official scoring is unavailable during actor execution or after scoring')
            self.phase = 'scoring'
            result = self._evaluate(answer)
            self.phase = 'evaluated'
            return result

    def close(self) -> None:
        with self._lock:
            if self.phase == 'closed':
                return
            self.phase = 'closed'
            if self._close is not None:
                self._close()


def adaptive_runtime(environment: ActorEnvironment, *, strong, weak, options: dict,
                     event_sink=None, skills: dict | None = None):
    """Same wiring for every benchmark and ablation; runtime never receives scores."""
    from calc.adaptive import AdaptiveRuntime
    return AdaptiveRuntime(strong=strong, weak=weak, tools=environment.tools,
        invoke=environment.invoke, external_events=environment.events,
        environment_context=environment.context, event_sink=event_sink,
        skills=skills, **options)
