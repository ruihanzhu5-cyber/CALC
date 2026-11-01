"""Official AppWorld API bridge: one shared world, no model-written Python.

Each call executes a generated variable-free expression in the official interpreter.
Model arguments are JSON; loops share app state, not per-loop Python variables.
"""
from __future__ import annotations

import json
import hashlib
import re
import subprocess
import threading
from pathlib import Path

from calc.adaptive import function
from calc.benchmarks.session import EvaluationSession

UPSTREAM_COMMIT = "42b5bcf3cd334fee33f0c37c02070a9f5807add5"
DATA_VERSION = "0.2.0"
PUBLIC_CONTEXT = ("All APIs operate in one shared local task environment. "
    "Use official API documentation; do not invent APIs. Only Main calls "
    "supervisor.complete_task after resolving all delegated work. "
    "Read API schemas and pagination parameters; do not claim all records were checked "
    "after reading only a default first page. When the user asks for a specific value, "
    "put that value alone in complete_task's answer; explanations belong in the final message.")
API_TOOL = function("appworld_api", "Call an official API in the shared task environment. "
    "Discover APIs with api_docs.show_app_descriptions, show_api_descriptions(app_name), "
    "show_api_doc(app_name, api_name). Only Main should use supervisor.complete_task, when finished. "
    "arguments_json is a JSON object string; no Python code or persistent variables.", {
        "app": {"type": "string"}, "api": {"type": "string"},
        "arguments_json": {"type": "string"}}, ["app", "api", "arguments_json"])


def verify_source(repo: Path) -> dict:
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if head != UPSTREAM_COMMIT:
        raise ValueError(f"AppWorld checkout must be {UPSTREAM_COMMIT}, found {head}")
    diff = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--"], check=False)
    if diff.returncode != 0:
        raise ValueError("AppWorld tracked source is modified")
    # Official install decrypts the LFS bundle into untracked app implementation files.
    # Preserve their actual content hashes as well as the bundle's pinned Git commit.
    apps = repo / "src/appworld/apps"
    extracted = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(apps.rglob("*.py"))}
    if not extracted:
        raise ValueError("official AppWorld app bundle has not been installed")
    return {"commit": head, "data_version": DATA_VERSION, "installed_app_sources_sha256": extracted}


def development_ids(split: str) -> list[str]:
    if split not in {"train", "dev"}:
        raise ValueError("This development runner permits train/dev only")
    from appworld import load_task_ids
    return load_task_ids(dataset_name=split)  # no difficulty/reference-based filtering


def public_instruction(task) -> str:
    supervisor = {k: task.supervisor[k] for k in ("first_name", "last_name", "email", "phone_number")}
    return json.dumps({"instruction": task.instruction, "datetime": str(task.datetime),
                       "supervisor": supervisor}, ensure_ascii=False)


class AppWorldAdapter:
    def __init__(self, task_id: str, experiment_name: str, environment: dict):
        from appworld import AppWorld
        forbidden = {"load_ground_truth", "ground_truth_mode", "remote_environment_url",
                     "remote_apis_url", "remote_mcp_url", "experiment_name", "task_id"}
        if forbidden.intersection(environment):
            raise ValueError("adapter owns task identity and local shared environment isolation")
        self.world = AppWorld(task_id=task_id, experiment_name=experiment_name,
                              load_ground_truth=False, **environment)
        if self.world.task.db_version != DATA_VERSION:
            self.world.close()
            raise ValueError("AppWorld task data version mismatch")
        self.task_id, self.experiment_name = task_id, experiment_name
        self.instruction = public_instruction(self.world.task)
        self.tools = [API_TOOL]
        self.catalog = {doc["function"]["name"] for doc in self.world.task.api_docs.function_calling()}
        self.lock = threading.Lock()
        self.phase = "execute"
        self.tool_calls = 0

    def invoke(self, name: str, args: dict) -> str:
        if name != "appworld_api" or set(args) != {"app", "api", "arguments_json"}:
            raise ValueError("only the documented AppWorld API interface is allowed")
        app, api = args["app"], args["api"]
        if not all(isinstance(x, str) and re.fullmatch(r"[a-z][a-z0-9_]*", x) for x in (app, api)):
            raise ValueError("invalid API identifier")
        if f"{app}__{api}" not in self.catalog:
            raise ValueError("API not in this task's official public API catalog")
        parameters = json.loads(args["arguments_json"])
        if not isinstance(parameters, dict):
            raise ValueError("arguments_json must decode to an object")
        json.dumps(parameters, allow_nan=False)
        code = f"print(apis.{app}.{api}(**{parameters!r}))"
        with self.lock:
            if self.phase != "execute":
                raise RuntimeError("task execution has ended")
            self.tool_calls += 1
            return self.world.execute(code)

    def finish(self) -> None:
        with self.lock:
            if self.phase != "execute":
                raise RuntimeError("finish may only be called once")
            self.world.save_state()
            self.world.save_logs()
            self.phase = "evaluation"

    def evaluate(self) -> dict:
        if self.phase != "evaluation":
            raise RuntimeError("official scoring is unavailable during actor execution")
        from appworld import evaluate_task
        tracker = evaluate_task(self.task_id, experiment_name=self.experiment_name,
                                suppress_errors=True, save_report=True)
        self.phase = "evaluated"
        return tracker.to_dict()

    def close(self) -> None:
        self.world.close()
        self.phase = "closed"

    def session(self) -> EvaluationSession:
        return EvaluationSession(tools=self.tools, invoke=self.invoke, context=PUBLIC_CONTEXT,
            finish=self.finish, evaluate=lambda answer: self.evaluate(), close=self.close)
