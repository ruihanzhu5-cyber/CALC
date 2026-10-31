"""Lifecycle changes transfer real responsibilities and preserve recovery state."""

from copy import deepcopy

import pytest

from calc.context import ContextBudgetError
from calc.lifecycle import LifecycleRuntime
from calc.state import Decision, Evidence, TaskState, WorkItem


def make_state() -> TaskState:
    state = TaskState("lifecycle-test", "Find the release date and resolve the project alias.")
    state.add_work(WorkItem(
        "investigate", "Verify the alias using the primary record", owner="researcher",
        unresolved=["Confirm that Aurora and Dawn refer to the same project"],
    ))
    state.add_evidence(Evidence(
        "release", "Aurora, previously Dawn, was released on 18 September 2026.",
        "fixture://project-history", ["investigate"],
    ))
    state.agents["researcher"].history.append({
        "role": "tool", "content": "Read the primary project record.", "evidence_ids": ["release"],
    })
    return state


def assert_owned_once(state, work_id, expected_owner):
    assert state.work_items[work_id].owner == expected_owner
    owners = [agent.id for agent in state.agents.values() if work_id in agent.work_ids]
    assert owners == [expected_owner]


def test_transfer_keeps_unfinished_work_and_evidence_available_to_recipient():
    state = make_state()
    original_history = deepcopy(state.agents["researcher"].history)

    packet = LifecycleRuntime(state).apply(Decision("transfer", "researcher", work_ids=["investigate"]))

    assert_owned_once(state, "investigate", "main")
    assert state.work_items["investigate"].status == "pending"
    assert state.agents["researcher"].status == "archived"
    assert state.agents["main"].status == "active"
    assert state.agents["researcher"].history == original_history
    assert "Confirm that Aurora and Dawn" in packet.content
    assert "release" in packet.evidence_ids
    assert state.evidence["release"].source in packet.content


def test_partial_transfer_does_not_stop_remaining_responsibilities():
    state = make_state()
    state.add_work(WorkItem("remaining", "Check the date independently", owner="researcher"))

    LifecycleRuntime(state).apply(Decision("transfer", "researcher", work_ids=["investigate"]))

    assert_owned_once(state, "investigate", "main")
    assert_owned_once(state, "remaining", "researcher")
    assert state.agents["researcher"].status == "active"


def test_transfer_preserves_the_coordinators_existing_work_and_new_obligations():
    state = make_state()
    state.add_work(WorkItem(
        "integrate", "Write the final sourced answer",
        unresolved=["Include a citation for the release date"],
    ))

    packet = LifecycleRuntime(state).apply(Decision("transfer", "researcher"))

    assert_owned_once(state, "integrate", "main")
    assert_owned_once(state, "investigate", "main")
    assert {"integrate", "investigate"} <= set(packet.work_ids)
    assert "Include a citation for the release date" in packet.content
    assert "Confirm that Aurora and Dawn" in packet.content


def test_resume_recovers_history_and_reassigns_requested_work():
    state = make_state()
    original_history = deepcopy(state.agents["researcher"].history)
    runtime = LifecycleRuntime(state)
    runtime.apply(Decision("transfer", "researcher", work_ids=["investigate"]))

    packet = runtime.apply(Decision("resume", "researcher", work_ids=["investigate"]))

    assert_owned_once(state, "investigate", "researcher")
    assert state.agents["researcher"].status == "active"
    assert state.agents["researcher"].history == original_history
    assert "Confirm that Aurora and Dawn" in packet.content
    assert "release" in packet.evidence_ids


def test_retire_hands_all_pending_work_to_main():
    state = make_state()
    state.add_work(WorkItem(
        "second", "Resolve the release date conflict", owner="researcher",
        unresolved=["Check whether the archive timestamp is a revision"],
    ))

    packet = LifecycleRuntime(state).apply(Decision("retire", "researcher", work_ids=["investigate"]))

    assert_owned_once(state, "investigate", "main")
    assert_owned_once(state, "second", "main")
    assert state.agents["researcher"].status == "archived"
    assert "Check whether the archive timestamp is a revision" in packet.content
    assert state.work_items["second"].status == "pending"


def test_completed_work_can_be_retired_without_erasing_result():
    state = make_state()
    work = state.work_items["investigate"]
    work.status = "done"
    work.unresolved.clear()
    work.result = "The two project names identify the same project."

    packet = LifecycleRuntime(state).apply(Decision("retire", "researcher"))

    assert state.agents["researcher"].status == "archived"
    assert work.status == "done"
    assert work.result in packet.content
    assert "release" in state.evidence


def test_merge_preserves_distinct_unfinished_professional_checks():
    state = make_state()
    state.add_work(WorkItem(
        "audit", "Check attribution separately", owner="reviewer",
        unresolved=["Verify the author against the primary record"],
    ))

    packet = LifecycleRuntime(state).apply(Decision("merge", "researcher", recipient="reviewer"))

    assert_owned_once(state, "investigate", "reviewer")
    assert_owned_once(state, "audit", "reviewer")
    assert state.agents["researcher"].status == "archived"
    assert "Verify the author against the primary record" in packet.content
    assert "Confirm that Aurora and Dawn" in packet.content


def test_spawn_moves_work_to_a_new_execution_agent():
    state = TaskState("spawn-test", "Investigate the primary record.")
    state.add_work(WorkItem("find", "Locate the original source"))

    packet = LifecycleRuntime(state).apply(Decision("spawn", "researcher", work_ids=["find"]))

    assert_owned_once(state, "find", "researcher")
    assert state.agents["researcher"].status == "active"
    assert packet.recipient == "researcher"
    assert "Locate the original source" in packet.content


def test_reassign_keeps_one_owner_and_no_duplicate_memberships():
    state = make_state()
    runtime = LifecycleRuntime(state)
    decision = Decision("reassign", "researcher", recipient="reviewer", work_ids=["investigate"])

    runtime.apply(decision)
    runtime.apply(Decision("reassign", "reviewer", recipient="reviewer", work_ids=["investigate"]))

    assert_owned_once(state, "investigate", "reviewer")
    assert state.agents["reviewer"].work_ids.count("investigate") == 1


@pytest.mark.parametrize("action", ["transfer", "retire", "merge"])
def test_budget_failure_leaves_source_and_recipient_state_unchanged(action):
    state = make_state()
    before = deepcopy(state.to_dict())
    runtime = LifecycleRuntime(state)

    with pytest.raises(ContextBudgetError):
        runtime.apply(Decision(action, "researcher", recipient="new-recipient", context_budget=1))

    assert state.to_dict() == before
    assert runtime.packets == {}


def test_transfer_cannot_take_another_agents_work():
    state = make_state()
    state.add_work(WorkItem("private", "Continue the other investigation", owner="other"))
    before = deepcopy(state.to_dict())

    with pytest.raises(ValueError):
        LifecycleRuntime(state).apply(Decision("transfer", "researcher", work_ids=["private"]))

    assert state.to_dict() == before


def test_archived_agent_must_resume_before_continuing():
    state = make_state()
    runtime = LifecycleRuntime(state)
    runtime.apply(Decision("transfer", "researcher"))
    before = deepcopy(state.to_dict())

    with pytest.raises(ValueError):
        runtime.apply(Decision("continue", "researcher"))

    assert state.to_dict() == before


def test_state_roundtrip_preserves_resumable_handoff():
    state = make_state()
    LifecycleRuntime(state).apply(Decision("transfer", "researcher"))
    restored = TaskState.from_dict(deepcopy(state.to_dict()))

    LifecycleRuntime(restored).apply(Decision("resume", "researcher", work_ids=["investigate"]))

    assert_owned_once(restored, "investigate", "researcher")
    assert restored.evidence["release"] == state.evidence["release"]
    assert restored.agents["researcher"].history == state.agents["researcher"].history
