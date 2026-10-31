"""Transport-only DeepSeek compatibility around the unmodified author ClmAgent.

No heuristic summary or replacement context algorithm is implemented here.
The author ContextEnv, edit gate, rollback, nudges, and finish policy remain active.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, OpenAI

from clm_harness.clm_agent.harness import ClmAgent
from clm_harness.utils.tool_schemas import BASH_TOOL


def project_deepseek_messages(messages: list[dict[str, Any]]) -> tuple[list[dict], int]:
    """Keep real assistant reasoning; edited plain turns become attributed context notes."""
    result = []
    converted = 0
    for message in messages:
        allowed = {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"}
        item = {key: value for key, value in message.items() if key in allowed and value is not None}
        if item.get("role") == "assistant":
            if "reasoning_content" not in item and not item.get("tool_calls"):
                item = {"role": "user", "content":
                        "[CLM edited prior assistant context; retained as an attributed note]\n"
                        + str(item.get("content") or "")}
                converted += 1
            else:
                item.setdefault("reasoning_content", "")
                item.setdefault("content", "")
        result.append(item)
    return result, converted


class DeepSeekClmAgent(ClmAgent):
    """Original CLM loop with an explicit DeepSeek thinking-mode wire protocol."""

    def __init__(self, *args, max_total_tokens: int = 0, max_transport_attempts: int = 1, **kwargs):
        kwargs["temperature"] = None
        kwargs["send_chat_template_kwargs"] = False
        super().__init__(*args, **kwargs)
        self.port_max_total_tokens = int(max_total_tokens)
        self.port_max_transport_attempts = max(1, int(max_transport_attempts))
        self.port_total_tokens = 0
        self.port_request_count = 0

    def _port_record(self, event: dict) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        target = self.logs_dir / "deepseek_transport.jsonl"
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    async def _query_with_retry(self, model: str, messages: list[dict[str, Any]]) -> Any:
        model_name = model.removeprefix("openai/")
        if model_name != "deepseek-flash":
            raise ValueError("This compatibility wrapper requires canonical model deepseek-flash")
        api_base = self.api_base or os.environ.get("CLM_API_BASE", "https://api.deepseek.com")
        provider_direct = urlsplit(api_base).hostname == "api.deepseek.com"
        key_env = "DEEPSEEK_API_KEY" if provider_direct else "CALC_GATEWAY_KEY"
        api_key = os.environ.get(key_env)
        if not api_key:
            raise ValueError(f"{key_env} is required for the configured endpoint")
        if self.port_max_total_tokens and self.port_total_tokens >= self.port_max_total_tokens:
            self._port_record({"event": "task_token_budget", "reported_total_tokens": self.port_total_tokens})
            raise RuntimeError("Shared task token budget reached before the next model request")
        wire_messages, converted = project_deepseek_messages(messages)
        for attempt in range(1, self.port_max_transport_attempts + 1):
            started = perf_counter()
            self.port_request_count += 1
            event = {
                "event": "model_request", "request_index": self.port_request_count,
                "attempt": attempt, "model": model_name, "thinking": "enabled",
                "reasoning_effort": "high", "synthetic_assistant_notes": converted,
                "max_tokens": self.max_tokens, "messages": wire_messages,
                "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }
            def complete():
                with OpenAI(api_key=api_key, base_url=api_base, max_retries=0, timeout=600,
                            http_client=httpx.Client(trust_env=provider_direct, timeout=600)) as client:
                    return client.chat.completions.create(
                        model=model_name, messages=wire_messages, tools=[BASH_TOOL],
                        max_tokens=self.max_tokens, top_p=self.top_p or 0.95,
                        reasoning_effort="high", extra_body={"thinking": {"type": "enabled"}},
                    )
            try:
                response = await asyncio.to_thread(complete)
            except (APIConnectionError, APIStatusError) as exc:
                status = getattr(exc, "status_code", None)
                event.update(status="error", error_type=type(exc).__name__, status_code=status,
                             usage_reported=False, elapsed_seconds=perf_counter() - started)
                self._port_record(event)
                if attempt >= self.port_max_transport_attempts or status in {400, 401, 403, 404}:
                    raise RuntimeError(f"DeepSeek transport failed ({type(exc).__name__}, status={status})") from None
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            usage = response.usage.model_dump() if response.usage is not None else None
            total = int((usage or {}).get("total_tokens") or 0)
            self.port_total_tokens += total
            event.update(status="ok", response_id=response.id, usage=usage,
                         usage_reported=usage is not None, elapsed_seconds=perf_counter() - started)
            self._port_record(event)
            return response
        raise RuntimeError("Unreachable transport retry state")
