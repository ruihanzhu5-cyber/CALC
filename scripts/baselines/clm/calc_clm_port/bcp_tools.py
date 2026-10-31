#!/usr/bin/env python3
"""Shared BCP gateway commands. No independent retrieval or truncation policy."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


def gateway_call(action: str, value: str, base_url: str | None = None) -> dict:
    base = (base_url or os.environ.get("BCP_BASE_URL", "http://127.0.0.1:8765")).rstrip("/")
    if action not in {"search", "get_document"}:
        raise ValueError("Only search and get_document are supported")
    path, body = ("/retrieve", {"query": value}) if action == "search" else ("/document", {"docid": value})
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"BCP gateway request failed ({type(exc).__name__})") from None
    if not isinstance(result, dict):
        raise ValueError("BCP gateway returned a non-object")
    if action == "search" and not isinstance(result.get("result"), list):
        raise ValueError("search response requires result list")
    if action == "get_document" and not isinstance(result.get("document"), dict):
        raise ValueError("get_document response requires document object")
    log_path = os.environ.get("BCP_TOOL_LOG")
    if log_path:
        target = Path(log_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        event = {"action": action, "argument": value, "elapsed_seconds": time.monotonic() - started}
        if action == "search":
            event["docids"] = [str(doc.get("docid")) for doc in result["result"]]
        else:
            event["docid"] = str(result["document"].get("docid"))
            event["truncated"] = result.get("truncated")
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    return result


def main(argv: list[str] | None = None) -> None:
    executable = Path(sys.argv[0]).name
    parser = argparse.ArgumentParser(description=__doc__)
    if executable in {"search", "get_document"}:
        action = executable
    else:
        parser.add_argument("action", choices=["search", "get_document"])
        action = None
    parser.add_argument("value", help="Search query or document ID")
    args = parser.parse_args(argv)
    try:
        result = gateway_call(action or args.action, args.value)
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
