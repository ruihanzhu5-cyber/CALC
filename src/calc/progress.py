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
