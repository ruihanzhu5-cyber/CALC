"""Offline contracts for local progressive disclosure, without a model client."""
import copy

import pytest

from calc.capabilities import CATALOG_DESCRIPTION_CHARS, ToolRegistry


def tool(name, description="Read the requested record."):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": {"record_id": {"type": "string"}},
                       "required": ["record_id"], "additionalProperties": False}}}


def test_catalog_does_not_disclose_parameter_schema_or_long_procedure():
    registry = ToolRegistry([tool("Emails__read", "Read an email. SECRET PROCEDURE and long explanation."),
                             tool("Files__read", "x" * 300)])
    catalog = registry.catalog()
    assert catalog[0] == {"name": "Emails__read", "description": "Read an email."}
    assert len(catalog[1]["description"]) == CATALOG_DESCRIPTION_CHARS
    assert all(set(entry) == {"name", "description"} for entry in catalog)


def test_explicit_load_preserves_complete_original_schema():
    schemas = [tool("read"), tool("write")]
    registry = ToolRegistry(schemas)
    assert registry.load(["write", "read"]) == [schemas[1], schemas[0]]
    assert registry.load([]) == []
    assert registry.names == ("read", "write")


def test_discovery_is_literal_ranked_and_never_loads_schema():
    registry = ToolRegistry([tool("contacts", "Find an email address."), tool("Emails__read"),
                             tool("Files__read")])
    assert [entry["name"] for entry in registry.discover("EMAIL")] == ["Emails__read", "contacts"]
    assert registry.discover("nonexistent") == []
    assert all("parameters" not in entry for entry in registry.discover("read"))


def test_scope_filters_catalog_discovery_and_load_without_widening():
    registry = ToolRegistry([tool("email"), tool("calendar")], allowed_tools=["email"])
    assert registry.names == ("email",)
    assert registry.discover("calendar") == []
    with pytest.raises(ValueError, match="outside current scope"):
        registry.load(["calendar"])
    with pytest.raises(ValueError, match="cannot widen"):
        registry.scoped(["calendar"])
    assert registry.scoped([]).catalog() == []
    assert registry.scoped(["email"]).load(["email"]) == [tool("email")]


def test_schema_and_catalog_mutations_cannot_change_registry():
    schemas = [tool("read")]
    expected = copy.deepcopy(schemas)
    registry = ToolRegistry(schemas)
    schemas[0]["function"]["parameters"]["properties"].clear()
    loaded = registry.load(["read"])
    loaded[0]["function"]["parameters"].clear()
    catalog = registry.catalog()
    catalog[0]["name"] = "overwritten"
    assert registry.load(["read"]) == expected
    assert registry.names == ("read",)


@pytest.mark.parametrize("names", [["missing"], ["read", "read"], "read", [None]])
def test_invalid_load_names_fail_without_partial_result(names):
    with pytest.raises(ValueError):
        ToolRegistry([tool("read")]).load(names)


@pytest.mark.parametrize("allowed", [["missing"], ["read", "read"], "read"])
def test_invalid_initial_scope_is_rejected(allowed):
    with pytest.raises(ValueError):
        ToolRegistry([tool("read")], allowed_tools=allowed)


@pytest.mark.parametrize("schemas", [[tool("read"), tool("read")],
    [{"type": "custom"}], [{"type": "function", "function": {"name": "read"}}]])
def test_malformed_or_duplicate_schema_is_rejected(schemas):
    with pytest.raises(ValueError):
        ToolRegistry(schemas)


@pytest.mark.parametrize("query", ["", "   ", "___", None])
def test_invalid_discovery_query_is_explicit_error(query):
    with pytest.raises(ValueError):
        ToolRegistry([tool("read")]).discover(query)
