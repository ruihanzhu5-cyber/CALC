"""Strict function-call wire parsing, separate from business/schema validation.

Tool calling supplies a call ID, function name, and JSON-encoded arguments;
see https://platform.openai.com/docs/guides/function-calling . Treat those
arguments as untrusted serialized data. Parse the entire batch before execution,
preserve IDs and values, and reject ambiguity instead of repairing JSON or
inventing missing fields. Tool-specific schemas, versions, ownership, and allowed
operations belong to their respective runtime validators.
"""
from __future__ import annotations

import json
import math
from typing import Any


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON object key')
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError('non-finite JSON number')


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('non-finite JSON number')
    return number


def parse_tool_calls(calls: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
    """Return validated (original call, name, arguments) tuples, or ValueError.

    Errors identify the call index and available function name, never echo raw
    arguments, duplicate key values, or call IDs. Empty batches return []. An
    error invalidates the batch: this function performs no dispatch or mutation.
    Provider-specific additional envelope fields are preserved on the original
    call; all required function-call fields are explicitly checked.
    """
    if not isinstance(calls, list):
        raise ValueError('tool_calls must be a list')
    parsed = []
    seen_ids: set[str] = set()
    for index, call in enumerate(calls):
        function = call.get('function') if isinstance(call, dict) else None
        name = function.get('name') if isinstance(function, dict) else None
        label = repr(name[:80]) if isinstance(name, str) else '<invalid>'
        prefix = f'tool call[{index}] name={label}: '
        if not isinstance(call, dict):
            raise ValueError(prefix + 'call must be an object')
        if call.get('type') != 'function':
            raise ValueError(prefix + 'type must be function')
        call_id = call.get('id')
        if not isinstance(call_id, str) or not call_id.strip():
            raise ValueError(prefix + 'nonempty string call ID required')
        if call_id in seen_ids:
            raise ValueError(prefix + 'duplicate call ID')
        seen_ids.add(call_id)
        if not isinstance(function, dict):
            raise ValueError(prefix + 'function must be an object')
        if not isinstance(name, str) or not name.strip():
            raise ValueError(prefix + 'nonempty string function name required')
        arguments = function.get('arguments')
        if not isinstance(arguments, str):
            raise ValueError(prefix + 'arguments must be a JSON string')
        try:
            args = json.loads(arguments, object_pairs_hook=_object_without_duplicates,
                              parse_constant=_reject_constant, parse_float=_finite_float)
        except json.JSONDecodeError as exc:
            raise ValueError(prefix + f'invalid JSON at line {exc.lineno} column {exc.colno}') from None
        except ValueError as exc:
            # Only our structural/numeric errors reach this branch. Do not expose
            # the serialized argument text in a model-visible error message.
            raise ValueError(prefix + str(exc)) from None
        except RecursionError:
            raise ValueError(prefix + 'JSON nesting exceeds parser depth') from None
        if not isinstance(args, dict):
            raise ValueError(prefix + 'arguments JSON must be an object')
        parsed.append((call, name, args))
    return parsed
