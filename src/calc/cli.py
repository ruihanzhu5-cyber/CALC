"""Small reproducible entry points for CALC development and experiments."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

from calc.demo import run_demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calc")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run a deterministic offline lifecycle/context integration example")
    demo.add_argument("--output", type=Path)
    commands.add_parser("doctor", help="Inspect local dependencies without requesting models")
    bcp = commands.add_parser("run-browsecomp", help="Run tasks against a real model and BC+ retrieval server")
    bcp.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "demo":
        result = run_demo()
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        print(text)
    elif args.command == "doctor":
        result = {"httpx": importlib.util.find_spec("httpx") is not None,
                  "are": importlib.util.find_spec("are") is not None,
                  "porchestra": importlib.util.find_spec("porchestra") is not None,
                  "model_key_present": bool(os.getenv("OPENAI_API_KEY")),
                  "model_requests_made": 0}
        print(json.dumps(result, indent=2))
    elif args.command == "run-browsecomp":
        from calc.adapters.browsecomp import run_browsecomp

        result = run_browsecomp(args.config)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0
