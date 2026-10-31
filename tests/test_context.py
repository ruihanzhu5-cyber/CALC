"""Input views must preserve obligations without rewriting the source record."""

from copy import deepcopy
import json

import pytest

from calc.context import ContextBudgetError, ContextCompiler
from calc.state import Evidence, TaskState, WorkItem


def make_state() -> TaskState:
    state = TaskState("context-test", "Find the origin and publication date; cite the primary document.")
    state.add_work(WorkItem(
        "verify", "Check the publication date", owner="researcher",
        unresolved=["Resolve the conflict between the archive and release page"],
    ))
    state.add_evidence(Evidence(
        "primary", "The original release was published on 18 September 2026.",
        "fixture://release-page", ["verify"], version="revision-2",
    ))
    return state


@pytest.mark.parametrize("mode", ["evidence", "recent", "full"])
def test_packet_keeps_task_and_unfinished_obligations(mode):
    state = make_state()
    work = state.work_items["verify"]
    packet = ContextCompiler().compile(state, "main", ["verify"], budget=512, mode=mode)

    assert state.instruction in packet.content
    assert work.goal in packet.content
    assert work.unresolved[0] in packet.content
    assert packet.work_ids == ["verify"]
    assert packet.estimated_tokens <= 512


@pytest.mark.parametrize("mode", ["evidence", "recent", "full"])
def test_compilation_leaves_raw_history_and_evidence_unchanged(mode):
    state = make_state()
    state.agents["researcher"].history.extend([
        {"role": "tool", "content": "old-raw-record " * 500},
        {"role": "assistant", "content": "The conflicting date still needs a check."},
    ])
    before = deepcopy(state.to_dict())

    ContextCompiler().compile(state, "main", ["verify"], budget=512, mode=mode)

    assert state.to_dict() == before


def test_mandatory_overflow_is_explicit_and_does_not_truncate():
    state = make_state()
    state.work_items["verify"].unresolved.append("mandatory-constraint " * 200)
    before = deepcopy(state.to_dict())

    with pytest.raises(ContextBudgetError):
        ContextCompiler().compile(state, "main", ["verify"], budget=64)

    assert state.to_dict() == before


def test_selected_evidence_includes_fact_provenance_and_version():
    state = make_state()
    state.add_work(WorkItem("unrelated", "Check a different project", owner="other"))
    state.add_evidence(Evidence("other-doc", "Unrelated material", "fixture://other", ["unrelated"]))

    packet = ContextCompiler().compile(state, "main", ["verify"], budget=512)

    assert "primary" in packet.evidence_ids
    assert state.evidence["primary"].content in packet.content
    assert state.evidence["primary"].source in packet.content
    assert state.evidence["primary"].version in packet.content
    assert "other-doc" not in packet.evidence_ids
    assert "Unrelated material" not in packet.content


def test_evidence_that_does_not_fit_is_reported_as_omitted():
    state = make_state()
    state.evidence["primary"].content = "A long source paragraph. " * 1_000

    packet = ContextCompiler().compile(state, "main", ["verify"], budget=256)

    assert packet.estimated_tokens <= 256
    assert "primary" not in packet.evidence_ids
    assert "primary" in packet.omitted_evidence_ids
    assert state.work_items["verify"].unresolved[0] in packet.content


def test_history_reference_alone_is_not_counted_as_retained_fact():
    state = make_state()
    state.agents["researcher"].history.append({
        "role": "tool", "content": "Read the release page.", "evidence_ids": ["primary"],
    })

    packet = ContextCompiler().compile(state, "main", ["verify"], budget=512, mode="recent")

    assert "Read the release page." in packet.content
    assert state.evidence["primary"].content not in packet.content
    assert "primary" not in packet.evidence_ids
    assert "primary" in packet.omitted_evidence_ids


@pytest.mark.parametrize("fact", ['Line one\nLine two', 'The name is "Aurora".'])
def test_recent_view_recognizes_facts_inside_json_encoded_tool_results(fact):
    state = make_state()
    state.evidence["primary"].content = fact
    state.agents["researcher"].history.append({
        "role": "tool", "evidence_ids": ["primary"],
        "content": json.dumps([{"docid": "primary", "text": fact}]),
    })

    packet = ContextCompiler().compile(state, "main", ["verify"], budget=512, mode="recent")

    assert "primary" in packet.evidence_ids
    assert "primary" not in packet.omitted_evidence_ids


def test_recent_view_is_bounded_but_the_full_record_remains_available():
    state = make_state()
    history = state.agents["researcher"].history
    history.extend([
        {"role": "tool", "content": "EARLY_HISTORY_MARKER " * 300},
        {"role": "assistant", "content": "LATEST_HISTORY_MARKER: compare the two dates."},
    ])
    compiler = ContextCompiler()

    recent = compiler.compile(state, "main", ["verify"], budget=512, mode="recent")
    full = compiler.compile(state, "main", ["verify"], budget=8_000, mode="full")

    assert "LATEST_HISTORY_MARKER" in recent.content
    assert "EARLY_HISTORY_MARKER" not in recent.content
    assert "EARLY_HISTORY_MARKER" in full.content
    assert "EARLY_HISTORY_MARKER" in history[0]["content"]
    assert recent.estimated_tokens <= 512


def test_compiled_messages_use_the_view_instead_of_raw_history():
    state = make_state()
    state.agents["researcher"].history.append({"role": "tool", "content": "RAW_ONLY_SENTINEL"})
    compiler = ContextCompiler()
    packet = compiler.compile(state, "main", ["verify"], budget=512, mode="evidence")

    messages = compiler.messages(packet)

    assert any(message["content"] == packet.content for message in messages)
    assert all("RAW_ONLY_SENTINEL" not in message["content"] for message in messages)
    assert state.agents["researcher"].history[0]["content"] == "RAW_ONLY_SENTINEL"


def test_default_work_selection_matches_recipient_ownership():
    state = make_state()
    state.add_work(WorkItem("main-task", "Integrate the checked evidence"))

    packet = ContextCompiler().compile(state, "main", budget=512)

    assert packet.work_ids == ["main-task"]
    assert "Integrate the checked evidence" in packet.content
    assert "Check the publication date" not in packet.content


def test_unknown_packet_mode_is_rejected():
    with pytest.raises(ValueError):
        ContextCompiler().compile(make_state(), "main", ["verify"], mode="undefined")
