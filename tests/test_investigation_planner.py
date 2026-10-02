"""Focused Phase 5 Step 2 tests for investigation intent planning."""
from verdict.agents import investigation_planner
from verdict.context import InvestigationState
from verdict.llm import LLMError


def _plan(monkeypatch, response):
    monkeypatch.setattr(investigation_planner, "call_llm_json", lambda prompt: response)
    return investigation_planner.plan_investigation("diff", [], [], InvestigationState())


def test_investigation_planner_accepts_valid_non_investigating_response(monkeypatch):
    result = _plan(monkeypatch, {"investigate": False, "goals": []})

    assert result == {"investigate": False, "goals": [], "source": "llm"}


def test_investigation_planner_accepts_an_available_investigation_goal(monkeypatch):
    result = _plan(
        monkeypatch,
        {
            "investigate": True,
            "goals": [
                {
                    "question": "Do existing tests reference this function?",
                    "required_capability": "inspect_python_test_references",
                    "reason": "The current evidence is incomplete.",
                }
            ],
        },
    )

    assert result["investigate"] is True
    assert (
        result["goals"][0].required_capability
        == "inspect_python_test_references"
    )


def test_investigation_planner_fails_safely_for_malformed_response(monkeypatch):
    result = _plan(monkeypatch, {"investigate": False, "goals": [{"question": "not allowed"}]})

    assert result["investigate"] is False
    assert result["goals"] == []
    assert result["source"] == "fallback"


def test_investigation_planner_rejects_concrete_tool_name(monkeypatch):
    result = _plan(
        monkeypatch,
        {"investigate": True, "goals": [{"question": "scan", "required_capability": "ruff", "reason": "need facts"}]},
    )

    assert result["source"] == "fallback"


def test_investigation_planner_rejects_arbitrary_command(monkeypatch):
    result = _plan(
        monkeypatch,
        {"investigate": True, "goals": [{"question": "scan", "required_capability": "rm -rf /", "reason": "need facts"}]},
    )

    assert result["source"] == "fallback"


def test_investigation_planner_supports_multiple_goals(monkeypatch):
    result = _plan(
        monkeypatch,
        {
            "investigate": True,
            "goals": [
                {
                    "question": "Find existing test references?",
                    "required_capability": "inspect_python_test_references",
                    "reason": "review gap",
                },
                {
                    "question": "Trace the input source?",
                    "required_capability": "trace_input_source",
                    "reason": "review gap",
                },
            ],
        },
    )

    assert [goal.required_capability for goal in result["goals"]] == [
        "inspect_python_test_references",
        "trace_input_source",
    ]


def test_investigation_planner_uses_empty_fallback_when_llm_fails(monkeypatch):
    monkeypatch.setattr(
        investigation_planner,
        "call_llm_json",
        lambda prompt: (_ for _ in ()).throw(LLMError("offline")),
    )

    result = investigation_planner.plan_investigation("diff", [], [], InvestigationState())

    assert result["investigate"] is False
    assert result["goals"] == []
    assert result["source"] == "fallback"

def test_investigation_planner_accepts_unknown_semantic_capability(monkeypatch):
    result = _plan(
        monkeypatch,
        {
            "investigate": True,
            "goals": [
                {
                    "question": "Is this input externally controlled?",
                    "required_capability": "trace_input_source",
                    "reason": "The security finding requires additional context.",
                }
            ],
        },
    )

    assert result["source"] == "llm"
    assert result["goals"][0].required_capability == "trace_input_source"
