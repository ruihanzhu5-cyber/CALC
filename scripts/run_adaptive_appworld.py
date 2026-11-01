"""Official AppWorld train/dev runner. Default preflight makes zero model calls.

--lock-data writes an immutable asset lock; --execute opts into paid execution.
No implicit download, retry, resume, alternate evaluator, or simulated score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calc.benchmarks.session import adaptive_runtime  # noqa: E402
from calc.benchmarks.appworld import AppWorldAdapter, development_ids, verify_source, DATA_VERSION  # noqa: E402
from calc.llm import OpenAICompatibleClient, aggregate_usage  # noqa: E402
from calc.progress import MODES, allowed_operations  # noqa: E402


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def hash_assets(root: Path, split: str, ids: list[str]) -> dict:
    directories = [root / "data" / "api_docs", root / "data" / "base_dbs",
                   *[root / "data" / "tasks" / tid for tid in ids]]
    files = {root / "data" / "datasets" / f"{split}.txt"}
    for directory in directories:
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        files.update(p for p in directory.rglob("*") if p.is_file())
    # Development references are hashed as opaque bytes, never passed to actors.
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--execute", action="store_true")
    phase.add_argument("--lock-data", action="store_true")
    parser.add_argument("--mode", choices=sorted(MODES))
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if cfg["split"] not in {"train", "dev"}:
        raise ValueError("train/dev only")
    provenance = verify_source(Path(cfg["appworld_repo"]))
    # Set locations BEFORE importing AppWorld/IPython; defaults use the user profile.
    for key, value in cfg["storage"].items():
        if key not in {"APPWORLD_CACHE", "IPYTHONDIR", "TEMP", "TMP", "TMPDIR"}:
            raise ValueError("unsupported storage setting")
        Path(value).mkdir(parents=True, exist_ok=True)
        os.environ[key] = value
    import appworld
    if Path(appworld.__file__).resolve() != (Path(cfg["appworld_repo"]) / "src/appworld/__init__.py").resolve():
        raise ValueError("imported AppWorld differs from configured checkout")
    appworld.update_root(cfg["appworld_root"])
    ids = cfg["task_ids"]
    if not ids or len(ids) != len(set(ids)) or set(ids) - set(development_ids(cfg["split"])):
        raise ValueError("explicit unique train/dev task IDs required")
    hashes = hash_assets(Path(cfg["appworld_root"]), cfg["split"], ids)
    lock = {"data_version": DATA_VERSION, "split": cfg["split"], "task_ids": ids, "sha256": hashes}
    lock_path = Path(cfg["data_lock"])
    if args.lock_data:
        with lock_path.open("x", encoding="utf-8") as f:
            json.dump(lock, f, indent=2)
        print(json.dumps({"lock": str(lock_path), "files": len(hashes), "model_requests": 0}))
        return 0
    if json.loads(lock_path.read_text(encoding="utf-8-sig")) != lock:
        raise ValueError("development data lock mismatch")
    mode = args.mode or cfg["runtime"]["collaboration_mode"]
    output = Path(cfg["output_dir"]) / mode / ("execute" if args.execute else "preflight")
    output.mkdir(parents=True, exist_ok=False)
    options = {**cfg["runtime"], "collaboration_mode": mode}
    # Explicit Git directory supports a Windows-created worktree executed in WSL.
    git = ["git"] + (["--git-dir", cfg["calc_git_dir"]] if "calc_git_dir" in cfg else [])
    manifest = {"upstream": provenance, "data_lock": lock,
        "calc_commit": subprocess.check_output([*git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT / "src/calc/adaptive.py", ROOT / "src/calc/progress.py",
                      ROOT / "src/calc/benchmarks/appworld.py", ROOT / "src/calc/benchmarks/session.py",
                      ROOT / "src/calc/llm.py", Path(__file__)]},
        "config": cfg, "runtime": options,
        "allowed_initial_operations": sorted(allowed_operations(mode, True, True)),
        "allowed_later_operations": sorted(allowed_operations(mode, False, True)),
        "preflight": not args.execute}
    write_json(output / "manifest.json", manifest)
    clients, rows = {}, []
    try:
        if args.execute:
            for tier, spec in cfg["models"].items():
                clients[tier] = OpenAICompatibleClient(spec["base_url"], spec["model"],
                    os.environ[spec["key_env"]], temperature=spec["temperature"])
        for tid in (ids if args.execute else ids[:1]):
            started = perf_counter()
            task_dir = output / tid
            task_dir.mkdir()
            experiment = f"calc-{output.parent.parent.name}-{mode}-{'run' if args.execute else 'preflight'}"
            official_output = Path(cfg["appworld_root"]) / "experiments/outputs" / experiment / "tasks" / tid
            if official_output.exists():
                raise FileExistsError(f"refusing to overwrite official task output: {official_output}")
            adapter, runtime, session = None, None, None
            try:
                adapter = AppWorldAdapter(tid, experiment, cfg["environment"])
                session = adapter.session()
                if args.execute:
                    with (task_dir / "trace.jsonl").open("w", encoding="utf-8") as trace:
                        def emit(event):
                            trace.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                            trace.flush()
                        runtime = adaptive_runtime(session.actor_environment(), strong=clients['strong'],
                            weak=clients['weak'], event_sink=emit, options=options)
                        result = runtime.run(adapter.instruction)
                else:
                    observation = session.invoke("appworld_api", {"app": "api_docs",
                        "api": "show_app_descriptions", "arguments_json": "{}"})
                    if not observation.strip() or "Traceback" in observation:
                        raise RuntimeError("official documentation API preflight failed")
                    result = {"status": "preflight_only", "usage": {"model_requests": 0},
                              "note": "Documentation lookup only; not a model result or attempted solution"}
                write_json(task_dir / "result.json", result)
                session.finish()
                evaluation = session.evaluate(result.get('answer', ''))
                write_json(task_dir / "evaluation.json", evaluation)
            except Exception as exc:
                write_json(task_dir / "failure.json", {"error_type": type(exc).__name__, "detail": str(exc),
                    "calls": runtime.calls if runtime is not None else [],
                    "usage": aggregate_usage(runtime.calls) if runtime is not None else None})
                raise  # persist the failure; no substitute answer/score, no paid retry
            finally:
                if session is not None:
                    session.close()
                elif adapter is not None:
                    adapter.close()
            rows.append({"task_id": tid, "runtime_completed": result["status"] == "answered",
                         "success": evaluation["success"], "usage": result["usage"],
                         "metrics": result.get("metrics"), "wall_seconds": perf_counter() - started,
                         "preflight_only": not args.execute})
            write_json(output / "summary.json", {"tasks": rows, "denominator": len(ids) if args.execute else 1,
                "success_rate": sum(r["success"] for r in rows) / len(ids) if args.execute else None,
                "runtime_completion_rate": sum(r["runtime_completed"] for r in rows) / len(ids) if args.execute else None})
    finally:
        for client in clients.values():
            client.close()
    print(json.dumps({"output": str(output), "tasks": len(rows), "preflight": not args.execute}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
