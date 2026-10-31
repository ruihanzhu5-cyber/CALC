"""Verify the configured DeepSeek tool round trip without recording credentials."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="deepseek-flash")
    args = parser.parse_args()
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "requested_model": args.model,
        "previous_configured_alias": os.environ.get("DEEPSEEK_MODEL"),
        "documented_serving_version": "DeepSeek-V4.1-Flash-1017",
        "version_source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "calls": [],
        "status": "not_run",
    }
    messages = [{"role": "user", "content": "Call echo with value ready. After it returns, reply only READY."}]
    tools = [{"type": "function", "function": {
        "name": "echo", "description": "Return the provided value unchanged.",
        "parameters": {"type": "object", "properties": {"value": {"type": "string"}},
                       "required": ["value"], "additionalProperties": False},
    }}]
    with httpx.Client(timeout=180, headers={"Authorization": f"Bearer {key}"}) as client:
        for turn in range(2):
            response = client.post(f"{base}/chat/completions", json={
                "model": args.model, "messages": messages, "tools": tools,
                "tool_choice": "auto", "stream": False, "max_tokens": 4096,
                "thinking": {"type": "enabled"}, "reasoning_effort": "high",
            })
            report["calls"].append({"turn": turn, "http_status": response.status_code})
            if response.is_error:
                report["status"] = "http_error"
                break
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            report["calls"][-1].update({
                "response_model": data.get("model"), "usage": data.get("usage"),
                "finish_reason": choice.get("finish_reason"),
                "reasoning_present": bool(message.get("reasoning_content")),
                "tool_calls": len(message.get("tool_calls") or []),
            })
            # Keep the complete assistant message, including reasoning_content.
            messages.append(message)
            calls = message.get("tool_calls") or []
            if turn == 0:
                if len(calls) != 1 or calls[0]["function"]["name"] != "echo":
                    report["status"] = "tool_call_missing"
                    break
                call = calls[0]
                value = json.loads(call["function"]["arguments"])["value"]
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps({"value": value})})
            elif not calls and choice.get("finish_reason") == "stop":
                report["status"] = "ok" if (message.get("content") or "").strip() == "READY" else "unexpected_answer"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
