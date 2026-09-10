"""Focused Phase 5 Step 1 tests for bounded investigation state."""
import pytest

from verdict.context import InvestigationGoal, InvestigationState, ReviewContext


def test_investigation_goal_uses_a_semantic_capability():
    goal = InvestigationGoal(
        question="Is lint evidence available for this change?",
        required_capability="lint_python",
        reason="The review needs trusted lint findings.",
    )

    assert goal.required_capability == "lint_python"


@pytest.mark.parametrize("required_capability", ["ruff", "run ruff", ""])
def test_investigation_goal_rejects_concrete_or_malformed_capabilities(required_capability):
    with pytest.raises(ValueError, match="semantic capability"):
        InvestigationGoal("Question", required_capability, "Reason")


def test_investigation_state_initializes_without_an_investigation_loop():
    state = InvestigationState()

    assert state.current_round == 0
    assert state.next_round == 1
    assert state.requested_goals == []
    assert state.completed_capabilities == set()
    assert state.unresolved_goals == []


def test_investigation_state_tracks_completed_capabilities_and_unresolved_goals():
    goal = InvestigationGoal("Need lint facts", "lint_python", "Review requires lint findings.")
    state = InvestigationState(requested_goals=[goal], unresolved_goals=[goal])
    state.completed_capabilities.add("lint_python")
    context = ReviewContext(investigation=state)

    assert context.investigation.completed_capabilities == {"lint_python"}
    assert context.investigation.unresolved_goals == [goal]
