"""Tests for bounded investigation planning and state."""

import pytest

from verdict.agents import investigation_planner
from verdict.context import (
    InvestigationGoal,
    InvestigationState,
    ReviewContext,
)


def test_investigation_goal_uses_a_semantic_capability():
    goal = InvestigationGoal(
        question="Is lint evidence available for this change?",
        required_capability="lint_python",
        reason="The review needs trusted lint findings.",
    )

    assert goal.required_capability == "lint_python"


@pytest.mark.parametrize(
    "required_capability",
    [
        "ruff",
        "run ruff",
        "",
    ],
)
def test_investigation_goal_rejects_concrete_or_malformed_capabilities(
    required_capability,
):
    with pytest.raises(ValueError, match="semantic capability"):
        InvestigationGoal(
            "Question",
            required_capability,
            "Reason",
        )


def test_investigation_state_initializes_without_an_investigation_loop():
    state = InvestigationState()

    assert state.current_round == 0
    assert state.next_round == 1
    assert state.requested_goals == []
    assert state.completed_capabilities == set()
    assert state.unresolved_goals == []
    assert state.evidence == []


def test_investigation_state_tracks_completed_capabilities_and_unresolved_goals():
    goal = InvestigationGoal(
        "Need lint facts",
        "lint_python",
        "Review requires lint findings.",
    )

    state = InvestigationState(
        requested_goals=[goal],
        unresolved_goals=[goal],
    )

    state.completed_capabilities.add("lint_python")

    context = ReviewContext(
        investigation=state,
    )

    assert context.investigation.completed_capabilities == {
        "lint_python"
    }

    assert context.investigation.unresolved_goals == [
        goal
    ]


def test_investigation_state_tracks_accumulated_evidence():
    evidence_item = {
        "capability": "lint_python",
        "tool": "ruff",
        "kind": "lint",
        "file": "app.py",
        "line": 12,
        "message": "style",
        "severity": "info",
        "rule_id": "I001",
        "details": {},
    }

    state = InvestigationState(
        evidence=[evidence_item]
    )

    context = ReviewContext(
        investigation=state,
    )

    assert context.investigation.evidence == [
        evidence_item
    ]


def test_validate_intent_accepts_registered_investigation_capability():
    result = investigation_planner._validate_intent(
        {
            "investigate": True,
            "goals": [
                {
                    "question": (
                        "Verify whether an existing test already "
                        "references the new function."
                    ),
                    "required_capability": (
                        "inspect_python_test_references"
                    ),
                    "reason": (
                        "The initial test-delta evidence only examined "
                        "tests changed in the PR."
                    ),
                }
            ],
        }
    )

    assert result["investigate"] is True
    assert len(result["goals"]) == 1

    goal = result["goals"][0]

    assert isinstance(goal, InvestigationGoal)
    assert (
        goal.required_capability
        == "inspect_python_test_references"
    )


def test_validate_intent_preserves_unknown_semantic_capability_for_registry():
    """The planner validates semantic shape; the Registry owns support.

    An unknown semantic capability is intentionally allowed through this
    layer so the ToolRegistry can classify it as unsupported and reject
    execution safely.
    """
    result = investigation_planner._validate_intent(
        {
            "investigate": True,
            "goals": [
                {
                    "question": "Need additional environment information.",
                    "required_capability": (
                        "detect_environment_variables"
                    ),
                    "reason": "The reviewer requested this evidence.",
                }
            ],
        }
    )

    assert result["investigate"] is True
    assert len(result["goals"]) == 1

    goal = result["goals"][0]

    assert isinstance(goal, InvestigationGoal)
    assert (
        goal.required_capability
        == "detect_environment_variables"
    )


def test_validate_intent_rejects_concrete_tool_name():
    with pytest.raises(
        investigation_planner.InvestigationPlannerError
    ):
        investigation_planner._validate_intent(
            {
                "investigate": True,
                "goals": [
                    {
                        "question": "Run Ruff for this change.",
                        "required_capability": "ruff",
                        "reason": "Need lint findings.",
                    }
                ],
            }
        )


def test_validate_intent_rejects_registered_non_investigation_capability():
    with pytest.raises(
        investigation_planner.InvestigationPlannerError,
        match="not available for investigation",
    ):
        investigation_planner._validate_intent(
            {
                "investigate": True,
                "goals": [
                    {
                        "question": "Run lint after the initial scan.",
                        "required_capability": "lint_python",
                        "reason": "The initial scan did not request it.",
                    }
                ],
            }
        )


def test_validate_intent_rejects_investigation_without_goals():
    with pytest.raises(
        investigation_planner.InvestigationPlannerError
    ):
        investigation_planner._validate_intent(
            {
                "investigate": True,
                "goals": [],
            }
        )


def test_validate_intent_rejects_goals_when_investigation_is_false():
    with pytest.raises(
        investigation_planner.InvestigationPlannerError
    ):
        investigation_planner._validate_intent(
            {
                "investigate": False,
                "goals": [
                    {
                        "question": "Need more evidence.",
                        "required_capability": (
                            "inspect_python_test_references"
                        ),
                        "reason": "Additional evidence is needed.",
                    }
                ],
            }
        )


def test_plan_investigation_accepts_supported_capability(monkeypatch):
    monkeypatch.setattr(
        investigation_planner,
        "call_llm_json",
        lambda prompt: {
            "investigate": True,
            "goals": [
                {
                    "question": (
                        "Is the newly added function referenced "
                        "by an existing test?"
                    ),
                    "required_capability": (
                        "inspect_python_test_references"
                    ),
                    "reason": (
                        "Initial test-delta evidence does not inspect "
                        "unchanged existing tests."
                    ),
                }
            ],
        },
    )

    result = investigation_planner.plan_investigation(
        diff_text="+def clamp(value):\n+    return value\n",
        evidence=[],
        reviewer_comments=[],
        investigation_state=InvestigationState(),
    )

    assert result["investigate"] is True
    assert result["source"] == "llm"
    assert len(result["goals"]) == 1
    assert (
        result["goals"][0].required_capability
        == "inspect_python_test_references"
    )


def test_plan_investigation_falls_back_on_invalid_llm_output(
    monkeypatch,
):
    monkeypatch.setattr(
        investigation_planner,
        "call_llm_json",
        lambda prompt: {
            "invalid": "schema",
        },
    )

    result = investigation_planner.plan_investigation(
        diff_text="",
        evidence=[],
        reviewer_comments=[],
        investigation_state=InvestigationState(),
    )

    assert result["investigate"] is False
    assert result["goals"] == []
    assert result["source"] == "fallback"
    assert "error" in result
