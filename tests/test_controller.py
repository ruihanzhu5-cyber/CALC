"""Controller tests check admissible decisions and packet-dependent behavior."""

from copy import deepcopy

import pytest

from calc.context import ContextBudgetError
from calc.controller import JointController
from calc.lifecycle import LifecycleRuntime
from calc.state import Evidence, TaskState, WorkItem


def make_state() -> TaskState:
    state = TaskState("controller-test", "Resolve the project alias and provide the release date.")
    state.add_work(WorkItem(
        "verify", "Check the release record", owner="researcher",
        unresolved=["Confirm the alias"],
    ))
    state.add_evidence(Evidence(
        "primary", "The primary record identifies Aurora as Dawn. " * 60,
        "fixture://release", ["verify"],
    ))
    state.agents["researcher"].stagnant_steps = 2
    state.agents["researcher"].new_evidence_count = 0
    return state


def identity(decision):
    return (
        decision.action, decision.agent_id, decision.recipient,
        tuple(decision.work_ids), tuple(decision.evidence_ids),
        decision.context_budget, decision.step_budget, decision.packet_mode,
    )


@pytest.mark.parametrize("mode", ["independent", "lifecycle", "context", "fixed"])
def test_modes_share_the_same_candidate_and_resource_foundation(mode):
    state = make_state()
    joint = JointController(mode="joint", context_budget=2048, step_budget=4)
    comparison = JointController(mode=mode, context_budget=2048, step_budget=4)

    assert {identity(item) for item in joint.candidates(state, "researcher")} == {
        identity(item) for item in comparison.candidates(state, "researcher")
    }


@pytest.mark.parametrize("mode", ["joint", "independent", "lifecycle", "context", "fixed"])
def test_scoring_and_deciding_do_not_commit_state_changes(mode):
    state = make_state()
    before = deepcopy(state.to_dict())
    controller = JointController(mode=mode)

    candidates = controller.candidates(state, "researcher")
    selected = controller.decide(state, "researcher")

    assert identity(selected) in {identity(item) for item in candidates}
    assert state.to_dict() == before


def test_joint_lifecycle_choice_changes_when_the_handoff_fact_can_fit():
    state = make_state()
    before = deepcopy(state.to_dict())

    incomplete = JointController(context_budget=256).decide(state, "researcher")
    complete = JointController(context_budget=2048).decide(state, "researcher")

    assert incomplete.action == "continue"
    assert complete.action == "transfer"
    assert "primary" not in incomplete.evidence_ids
    assert "primary" in complete.evidence_ids
    assert state.to_dict() == before


def test_every_candidate_can_be_applied_with_existing_recipient_obligations():
    state = make_state()
    state.add_work(WorkItem(
        "main-open", "An existing coordinator obligation " * 50,
        unresolved=["An existing mandatory constraint " * 25],
    ))
    controller = JointController(context_budget=256)

    candidates = controller.candidates(state, "researcher")

    assert candidates
    for decision in candidates:
        replay = TaskState.from_dict(deepcopy(state.to_dict()))
        packet = LifecycleRuntime(replay).apply(decision)
        assert packet.estimated_tokens <= decision.context_budget


@pytest.mark.parametrize("mode", ["joint", "independent", "lifecycle", "context", "fixed"])
def test_main_is_not_a_transfer_or_retirement_candidate(mode):
    state = TaskState("main-test", "Find the answer.")
    state.add_work(WorkItem("answer", "Inspect the available primary source"))
    controller = JointController(mode=mode)

    candidates = controller.candidates(state, "main")

    assert all(item.action == "continue" for item in candidates)
    assert controller.decide(state, "main").action == "continue"


def test_no_feasible_packet_raises_without_modifying_state():
    state = make_state()
    before = deepcopy(state.to_dict())

    with pytest.raises(ContextBudgetError):
        JointController(context_budget=1).decide(state, "researcher")

    assert state.to_dict() == before


def test_unknown_control_mode_is_rejected():
    with pytest.raises(ValueError):
        JointController(mode="undefined")
