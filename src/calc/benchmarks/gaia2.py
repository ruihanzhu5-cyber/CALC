"""GAIA2 bridge using unmodified ARE tools, event clock and graph judge.

Only public notifications and tool schemas/results cross the actor boundary.
Oracle trajectories and judge state remain private to the environment.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from calc.llm import OpenAICompatibleClient
from calc.benchmarks.session import EvaluationSession

ARE_COMMIT = "a9fd2edccb4bc7e22fbf45c8482a5fef30a2a5a4"
MANTA_COMMIT = "3da40879d690a25459cc401292e5c6f0cc366d84"


def public_value(value):
    """Lossless JSON representation of official public tool return types.

    Text stays text; dataclass records stay records. Unknown types fail explicitly
    instead of silently turning data into a truncated Python repr downstream.
    """
    if isinstance(value, Enum):
        return public_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return public_value(asdict(value))
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise TypeError("public tool dictionaries require string keys")
        return {k: public_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_value(v) for v in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported public tool result: {type(value).__name__}")
PUBLIC_CONTEXT = """You operate a shared application environment with evolving user requests.
Use the public API tools and notifications. Environment updates can supersede earlier requests.
All workers share the same application state. Avoid duplicate writes.
Only the main coordinator should send the final user response using AgentUserInterface__send_message_to_user.
Use SystemApp__wait_for_notification when waiting for external replies or future events.
Returning an answer ends the current user turn, not necessarily the scenario.
"""


class JudgeEngine:
    """Transport only; prompts, parsing, checks and turn gates are official ARE."""
    model_name = "deepseek-flash"

    def __init__(self, client, emit):
        self.client, self.emit = client, emit
        self.lock = threading.Lock()

    def __call__(self, messages, stop_sequences=None, **kwargs):
        with self.lock:
            try:
                response = self.client.complete(messages, max_output_tokens=16384)
            except Exception as exc:
                self.emit({"event": "judge_request", "usage": {}, "error": type(exc).__name__})
                raise
            self.emit({"event": "judge_request", "usage": response.usage.to_dict(),
                       "finish_reason": response.finish_reason})
            if response.finish_reason == "length":
                raise RuntimeError("official judge response truncated")
            return response.message["content"], response.usage.raw


class Gaia2Adapter:
    def __init__(self, path: Path, judge_engine, emit, *, preflight=False):
        from are.simulation.benchmark.scenario_loader import load_scenario
        from are.simulation.environment import Environment, EnvironmentConfig
        from are.simulation.notification_system import VerboseNotificationSystem
        from are.simulation.scenarios.scenario_imported_from_json.utils import preprocess_scenario
        from are.simulation.tool_utils import AppToolAdapter
        from are.simulation.validation import GraphPerEventJudgeConfig
        from are.simulation.types import EnvironmentType
        self.emit = emit
        self.lock = threading.RLock()
        self.clock_lock = threading.Lock()
        self.active_requests = 0
        self.notifications = []
        self.cursor = 0
        self.sent = 0
        self.scenario, _ = load_scenario(path.read_text(), str(path), False)
        if self.scenario is None:
            raise ValueError("official scenario import failed")
        # Official validation preprocessing executes an isolated oracle world then resets.
        # No oracle state, expected action or validation rationale is included in model input.
        preprocess_scenario(self.scenario,
            judge_config=GraphPerEventJudgeConfig(engine=judge_engine),
            max_scenario_duration=1800)
        self.env = Environment(EnvironmentConfig(start_time=self.scenario.start_time,
            time_increment_in_seconds=self.scenario.time_increment_in_seconds, verbose=False),
            environment_type=EnvironmentType.CLI,
            notification_system=VerboseNotificationSystem())
        self.env.run(self.scenario, wait_for_end=False)
        hidden_aui = {"get_last_message_from_user", "get_last_message_from_agent",
                      "get_last_unread_messages", "get_all_messages"}
        app_tools = [t for t in self.scenario.get_tools()
                     if not (t.app_name == "AgentUserInterface" and t.func_name in hidden_aui)]
        self.app_tools = {t.name: t for t in app_tools}
        self.tools = []
        for t in app_tools:
            adapted = AppToolAdapter(t)
            properties, required = {}, []
            for name, info in adapted.inputs.items():
                prop = {"description": info.get("description") or ""}
                if info["type"] != "any":
                    prop["type"] = info["type"]
                if prop.get("type") == "array":
                    prop["items"] = {}
                if "default" in info:
                    prop["default"] = info["default"]
                else:
                    required.append(name)
                properties[name] = prop
            self.tools.append({"type": "function", "function": {"name": t.name,
                "description": adapted.description, "parameters": {"type": "object",
                    "properties": properties, "required": required, "additionalProperties": False}}})

    def poll(self):
        with self.lock:
            now = datetime.fromtimestamp(self.env.time_manager.time(), tz=timezone.utc)
            messages = self.env.notification_system.message_queue.get_by_timestamp(now)
            fresh = []
            for msg in messages:
                event = {"id": f"env_{len(self.notifications)}", "type": msg.message_type.value,
                         "timestamp": msg.timestamp.isoformat(), "message": msg.message}
                self.notifications.append(event)
                fresh.append(event)
                self.emit({"event": "notification", **event})
            return fresh

    def pending(self):
        self.poll()
        result = self.notifications[self.cursor:]
        self.cursor = len(self.notifications)
        return [e for e in result if e["type"] != "ENVIRONMENT_STOP"]

    def public_snapshot(self):
        self.poll()
        return json.dumps({"current_time": self.env.time_manager.time(),
                           "notifications": self.notifications}, ensure_ascii=False)

    def stopped(self):
        return self.env.stop_event.is_set()

    def wait_events(self):
        while not self.stopped():
            events = self.pending()
            if events:
                return events
            time.sleep(0.2)
        return []

    def begin_request(self):
        with self.clock_lock:
            if self.stopped():
                raise RuntimeError("GAIA2 environment stopped")
            if self.active_requests == 0:
                self.env.pause()
                self.request_started = time.perf_counter()
            self.active_requests += 1

    def end_request(self):
        with self.clock_lock:
            self.active_requests -= 1
            if self.active_requests == 0:
                self.env.resume_with_offset(time.perf_counter() - self.request_started)

    def invoke(self, name, args):
        with self.lock:
            if self.stopped():
                raise RuntimeError("GAIA2 environment stopped")
            if name not in self.app_tools:
                raise ValueError("tool not in public catalog")
            try:
                result = public_value(self.app_tools[name](**args))
                if name == "AgentUserInterface__send_message_to_user":
                    self.sent += 1
                self.emit({"event": "tool_result", "name": name, "arguments": args,
                           "result": result, "success": True})
                return result
            except Exception as exc:
                self.emit({"event": "tool_result", "name": name, "arguments": args,
                           "error": str(exc), "success": False})
                raise

    def evaluate(self):
        return self.scenario.validate(self.env)

    def close(self):
        self.env.stop()

    def session(self) -> EvaluationSession:
        return EvaluationSession(tools=self.tools, invoke=self.invoke, context=PUBLIC_CONTEXT,
            events=self.pending, evaluate=lambda answer: self.evaluate(), close=self.close)


class ClockedClient:
    def __init__(self, client: OpenAICompatibleClient, adapter: Gaia2Adapter, emit):
        self.client, self.adapter, self.emit = client, adapter, emit
        self.model = client.model

    def complete(self, messages, **kwargs):
        request_id, started = uuid.uuid4().hex, time.perf_counter()
        self.emit({"event": "actor_input", "request_id": request_id, "messages": messages,
                   "tools": kwargs.get("tools", []), "model": self.model})
        self.adapter.begin_request()
        try:
            response = self.client.complete(messages, **kwargs)
            self.emit({"event": "actor_request", "request_id": request_id,
                       "elapsed_seconds": time.perf_counter() - started, "usage": response.usage.to_dict(),
                       "finish_reason": response.finish_reason, "message": response.message})
            return response
        except Exception as exc:
            self.emit({"event": "actor_request", "request_id": request_id,
                       "elapsed_seconds": time.perf_counter() - started, "usage": {}, "error": type(exc).__name__})
            raise
        finally:
            self.adapter.end_request()
