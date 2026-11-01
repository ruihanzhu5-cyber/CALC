"""Small synchronous OpenAI-compatible client with explicit usage accounting.

No retries are hidden here: a timeout can already have consumed provider tokens.
Cached input and reasoning output are subsets, never additions to total tokens.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any, Callable

import httpx


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    reported: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, value: dict[str, Any] | None) -> Usage:
        raw = dict(value or {})
        prompt = int(raw.get("prompt_tokens", raw.get("input_tokens", 0)) or 0)
        completion = int(raw.get("completion_tokens", raw.get("output_tokens", 0)) or 0)
        prompt_details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
        output_details = raw.get("completion_tokens_details") or raw.get("output_tokens_details") or {}
        cached = int(prompt_details.get("cached_tokens", raw.get("prompt_cache_hit_tokens", 0)) or 0)
        reasoning = int(output_details.get("reasoning_tokens", raw.get("reasoning_tokens", 0)) or 0)
        total = int(raw.get("total_tokens", prompt + completion) or 0)
        return cls(prompt, completion, cached, reasoning, total, bool(value), raw)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatResponse:
    message: dict[str, Any]
    finish_reason: str | None
    usage: Usage
    elapsed_seconds: float
    response_id: str | None = None


class OpenAICompatibleClient:
    """Chat-completions transport. Inject an httpx client for offline HTTP tests."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        *,
        timeout: float = 120,
        client: httpx.Client | None = None,
        output_token_field: str = "max_tokens",
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        extra_body: dict[str, Any] | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        if output_token_field not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("output_token_field must be max_tokens or max_completion_tokens")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.output_token_field = output_token_field
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.extra_body = dict(extra_body or {})
        self.clock = clock
        if {"model", "messages", "tools", "stream", "max_tokens", "max_completion_tokens"} & self.extra_body.keys():
            raise ValueError("extra_body cannot override protocol or budget fields")
        self.client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_output_tokens: int = 1024,
    ) -> ChatResponse:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        body: dict[str, Any] = {
            **self.extra_body, "model": self.model, "messages": messages,
            "stream": False, self.output_token_field: max_output_tokens,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        if tools:
            body.update(tools=tools, tool_choice="auto")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        started = self.clock()
        response = self.client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("chat response has no choices")
        choice = choices[0]
        message = dict(choice.get("message") or {})
        if message.get("role", "assistant") != "assistant":
            raise ValueError("chat response message must have assistant role")
        message["role"] = "assistant"
        return ChatResponse(
            message, choice.get("finish_reason"), Usage.from_response(data.get("usage")),
            self.clock() - started, data.get("id"),
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()


def aggregate_usage(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum inclusive counters; expose missing reports instead of inventing usage."""
    keys = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "total_tokens")
    usage = {key: sum(int(r.get("usage", {}).get(key, 0)) for r in records) for key in keys}
    usage["model_requests"] = len(records)
    usage["unreported_usage_requests"] = sum(not r.get("usage", {}).get("reported", False) for r in records)
    usage["accounting"] = "cached_input_tokens and reasoning_tokens are subsets, not added to totals"
    return usage
