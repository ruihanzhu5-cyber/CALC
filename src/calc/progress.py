"""Benchmark-independent, versioned work reports and experimental operation masks.

Original CALC implementation. Design references (not imported/copied): POrchestra
SAE + revise_active + MainMemoryBus; Anthropic single-agent-loop-kit transfers.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


MODES = {"single", "initial_static", "no_merge_fold", "full"}
EVENT_TYPES = {"task_start", "progress", "blocked", "dependency_changed", "conflict", "overlap"}
OPERATIONS = {"continue", "delegate", "merge", "fold", "wait", "escalate", "respond"}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()


@dataclass
class WorkReport:
    current_scope: str
    progress: str
    completion_condition: str
    unresolved: list[str] = field(default_factory=list)
    failed_routes: list[str] = field(default_factory=list)
    next_step: str = ""

    @classmethod
    def parse(cls, value: dict) -> WorkReport:
        keys = {"current_scope", "progress", "completion_condition", "unresolved", "failed_routes", "next_step"}
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError("progress must contain exactly the documented work-report fields")
        for key in keys - {"unresolved", "failed_routes"}:
            if not isinstance(value[key], str) or not value[key].strip():
                raise ValueError(f"nonempty progress.{key} required")
        for key in ("unresolved", "failed_routes"):
            if not isinstance(value[key], list) or any(not isinstance(s, str) or not s.strip() for s in value[key]):
                raise ValueError(f"progress.{key} must be a list of nonempty strings")
        return cls(**value)


def allowed_operations(mode: str, initial_open: bool, is_main: bool) -> set[str]:
    if mode not in MODES:
        raise ValueError(f"unknown collaboration mode: {mode}")
    if mode == "single":
        return {"continue"}
    common = {"continue", "wait"}
    if mode == "initial_static":
        return common | ({"delegate"} if initial_open and is_main else set())
    return OPERATIONS - ({"merge", "fold"} if mode == "no_merge_fold" else set())


def validate_proposal(p: dict, version: int) -> WorkReport:
    if p.get("event_type") not in EVENT_TYPES:
        raise ValueError("valid event_type required")
    if type(p.get("event_version")) is not int or p["event_version"] != version:
        raise ValueError(f"stale or invalid event_version; current version is {version}")
    for key in ("reason", "baseline_next", "proposed_next", "expected_savings", "risks", "handoff"):
        if not isinstance(p.get(key), str) or not p[key].strip():
            raise ValueError(f"nonempty {key} required; describe who does what, not a calibrated benefit")
    if not isinstance(p.get("evidence_ids"), list):
        raise ValueError("evidence_ids required (may be empty before observations)")
    return WorkReport.parse(p.get("progress"))


def collection_facts(output) -> list[dict]:
    """Describe JSON collections with distinct object IDs, not their independence.

    Ordinary scalar responses and documentation without object IDs are not events.
    Identity/order changes are factual; the model judges whether work can be split.
    """
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (ValueError, TypeError):
            return []  # non-JSON text has no supported structural observation
    facts = []

    def visit(value, path):
        if isinstance(value, dict):
            # Inspect primary result envelopes only. Embedded metadata such as an
            # individual record's artists/tags is not a newly discovered work set.
            for key, child in value.items():
                if key in {"results", "items", "records", "data"} and isinstance(child, (list, dict)):
                    visit(child, f"{path}/{key}")
        elif isinstance(value, list) and len(value) > 1 and all(isinstance(v, dict) for v in value):
            fields = set.intersection(*(set(v) for v in value))
            for key in sorted(fields, key=lambda x: (x != "id", x)):
                if key != "id" and not key.endswith("_id"):
                    continue
                ids = [v[key] for v in value]
                if all(type(v) in (str, int) for v in ids) and len(set(ids)) == len(ids):
                    facts.append({"path": path, "id_field": key, "count": len(ids),
                                  "identity": fingerprint(sorted(ids, key=str))})
                    break
    visit(output, "$")
    return facts


def validate_subgoals(value: list[dict]) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("subgoals must be a list")
    goals = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {"id", "goal", "status", "dependencies"}:
            raise ValueError("subgoal requires id, goal, status, dependencies")
        if any(not isinstance(item[k], str) or not item[k].strip() for k in ("id", "goal")):
            raise ValueError("nonempty subgoal id and goal required")
        if item["id"] in goals or item["status"] not in {"open", "blocked", "done"}:
            raise ValueError("duplicate subgoal or invalid status")
        if not isinstance(item["dependencies"], list) or any(not isinstance(d, str) for d in item["dependencies"]):
            raise ValueError("subgoal dependencies must be IDs")
        goals[item["id"]] = item
    visited, visiting = set(), set()

    def check(key):
        if key not in goals or key in visiting:
            raise ValueError("unknown or cyclic subgoal dependency")
        if key in visited:
            return
        visiting.add(key)
        for dep in goals[key]["dependencies"]:
            check(dep)
        visiting.remove(key)
        visited.add(key)
    for key in goals:
        check(key)
    return sorted(value, key=lambda g: g["id"])
