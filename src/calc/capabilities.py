"""Local progressive tool discovery for OpenAI-compatible model clients.

Independent CALC adaptation of the progressive disclosure design in Anthropic's
Tool.deferred / Agent._tool_params reference (Apache-2.0):
https://github.com/anthropics/single-agent-loop-kit/blob/
c43796287b83bec847db923f07131d1cc8de750d/reference_loop/loop.py

No upstream source is copied and no provider-specific tool-search API is used.
Discovery describes candidates; only explicit load() returns parameter schemas.
Scopes constrain discovery and loading, not backend execution permissions, which
the runtime must enforce separately. No schema is silently guessed or loaded.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from copy import deepcopy


CATALOG_DESCRIPTION_CHARS = 160


class ToolRegistry:
    """An immutable-by-interface catalog with an explicit visible tool scope.

    discover() ranks case-insensitive literal query-token matches in the tool
    name and full description. A name match ranks before description-only
    matches; ties preserve registration order. There is no semantic/fuzzy search
    or automatic choice when the query has no matches.
    """

    def __init__(self, schemas: Sequence[dict], *, allowed_tools: Sequence[str] | None = None):
        if not isinstance(schemas, Sequence) or isinstance(schemas, (str, bytes)):
            raise ValueError("tool schemas must be a sequence")
        self._schemas: dict[str, dict] = {}
        for schema in schemas:
            if not isinstance(schema, dict) or schema.get("type") != "function":
                raise ValueError("an OpenAI function tool schema is required")
            function = schema.get("function")
            if not isinstance(function, dict):
                raise ValueError("tool function must be an object")
            name = function.get("name")
            if not isinstance(name, str) or not name.strip() or name != name.strip():
                raise ValueError("tool name must be a nonempty unpadded string")
            if name in self._schemas:
                raise ValueError(f"duplicate tool name: {name}")
            if not isinstance(function.get("description", ""), str):
                raise ValueError(f"tool description must be a string: {name}")
            if not isinstance(function.get("parameters"), dict):
                raise ValueError(f"tool parameters must be an object: {name}")
            self._schemas[name] = deepcopy(schema)
        selected = self._validate_names(allowed_tools) if allowed_tools is not None else list(self._schemas)
        self._names = tuple(selected)

    def _validate_names(self, names: Sequence[str]) -> list[str]:
        if not isinstance(names, Sequence) or isinstance(names, (str, bytes)):
            raise ValueError("tool names must be a sequence of names")
        selected: list[str] = []
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("each tool name must be a nonempty string")
            if name not in self._schemas:
                raise ValueError(f"unknown tool: {name}")
            if name in selected:
                raise ValueError(f"duplicate requested tool: {name}")
            selected.append(name)
        return selected

    @property
    def names(self) -> tuple[str, ...]:
        return self._names

    def catalog(self) -> list[dict[str, str]]:
        """Return names and brief descriptions, never parameters or full schemas."""
        result = []
        for name in self._names:
            description = " ".join(self._schemas[name]["function"].get("description", "").split())
            description = re.split(r"(?<=[.!?])\s+", description, maxsplit=1)[0]
            if len(description) > CATALOG_DESCRIPTION_CHARS:
                description = description[:CATALOG_DESCRIPTION_CHARS - 1] + "…"
            result.append({"name": name, "description": description})
        return result

    def discover(self, query: str) -> list[dict[str, str]]:
        """Return matching scoped catalog entries; a valid unmatched query gives []."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("discovery query must be a nonempty string")
        terms = set(re.findall(r"[^\W_]+", query.casefold()))
        if not terms:
            raise ValueError("discovery query must contain a word or identifier")
        entries = {entry["name"]: entry for entry in self.catalog()}
        matches = []
        for order, name in enumerate(self._names):
            name_text = name.casefold()
            description = self._schemas[name]["function"].get("description", "").casefold()
            name_hits = sum(term in name_text for term in terms)
            description_hits = sum(term in description for term in terms)
            if name_hits or description_hits:
                matches.append((-name_hits, -description_hits, order, entries[name]))
        return [entry for _, _, _, entry in sorted(matches, key=lambda match: match[:3])]

    def load(self, names: Sequence[str]) -> list[dict]:
        """Load exactly the named schemas; reject unknown or out-of-scope names."""
        selected = self._validate_names(names)
        for name in selected:
            if name not in self._names:
                raise ValueError(f"tool outside current scope: {name}")
        return [deepcopy(self._schemas[name]) for name in selected]

    def scoped(self, allowed_tools: Sequence[str]) -> ToolRegistry:
        """Create a narrower registry; scope cannot widen through this method."""
        selected = self._validate_names(allowed_tools)
        for name in selected:
            if name not in self._names:
                raise ValueError(f"cannot widen tool scope: {name}")
        return ToolRegistry(list(self._schemas.values()), allowed_tools=selected)
