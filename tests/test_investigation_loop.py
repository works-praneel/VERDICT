"""Focused Phase 5 Step 3 tests for the bounded investigation loop."""
import json
from types import SimpleNamespace
import pytest

from verdict import cli, tools
from verdict.context import InvestigationGoal
from verdict.llm import LLMError


class _FakeRepo:
    def __init__(self, repo_path):
        self.active_branch = SimpleNamespace(name="main")
        self.head = SimpleNamespace(is_detached=False)
        self.git = SimpleNamespace(checkout=lambda branch: None)


@pytest.fixture
def mock_review_env(monkeypatch):
    """Provides a deterministic baseline review environment."""
    monkeypatch.setattr(cli, "Repo", _FakeRepo)
    monkeypatch.setattr(
        cli,
        "get_diff",
        lambda repo, branch, base: {"changed_files": ["app.py"], "diff_text": "+def foo(): pass"},
    )
    monkeypatch.setattr(
        cli.planner,
        "plan",
        lambda files, diff: {"capabilities": ["lint_python"], "reason": "Python changed", "source": "llm"},
    )
    monkeypatch.setattr(
        tools,
        "run_ruff",
        lambda repo, files: [{"file": "app.py", "line": 1, "issue": "unused import", "code": "F401"}],
    )
    monkeypatch.setattr(
        tools,
        "run_bandit",
        lambda repo, files: [{"file": "app.py", "line": 2, "issue": "hardcoded password", "severity": "HIGH"}],
    )
    monkeypatch.setattr(
        tools,
        "check_container_base_image_pinning",
        lambda diff, files: [{"file": "Dockerfile", "line": 1, "image": "python", "reason": "untagged"}],
    )


def test_zero_investigation_rounds_direct_judge(mock_review_env, monkeypatch, tmp_path):
    """When InvestigationPlanner decides no investigation is needed, proceed directly to Judge."""
    reviewer_calls = []
    judge_calls = []

    monkeypatch.setattr(
        cli.investigation_planner,
        "plan_investigation",
        lambda diff, evidence, comments, state: {"investigate": False, "goals": [], "source": "llm"},
    )
    monkeypatch.setattr(
        cli.reviewer,
        "draft_comments",
        lambda diff, evidence: reviewer_calls.append((diff, evidence)) or {
            "comments": [{"severity": "nitpick", "comment": "style issue"}],
            "source": "llm",
        },
    )
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: judge_calls.append((diff, evidence, comments)) or {
            "verdict": "comment",
            "justification": "Minor style.",
            "source": "llm",
        },
    )

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"))

    assert result["investigation"]["current_round"] == 0
    assert result["investigation"]["requested_goals"] == []
    assert result["investigation"]["unresolved_goals"] == []
    assert len(reviewer_calls) == 1
    assert len(judge_calls) == 1
    assert result["verdict"]["verdict"] == "comment"


def test_one_successful_investigation_round(mock_review_env, monkeypatch, tmp_path):
    """One investigation round gathers new evidence, updates Reviewer, then exits to Judge."""
    rounds_called = []

    def mock_plan_investigation(diff, evidence, comments, state):
        rounds_called.append(state.current_round)
        if state.current_round == 0:
            return {
                "investigate": True,
                "goals": [
                    InvestigationGoal(
                        question="Is the base image pinned?",
                        required_capability="check_container_base_image_pinning",
                        reason="Need container tag facts.",
                    )
                ],
                "source": "llm",
            }
        return {"investigate": False, "goals": [], "source": "llm"}

    monkeypatch.setattr(cli.investigation_planner, "plan_investigation", mock_plan_investigation)

    reviewer_calls = []
    monkeypatch.setattr(
        cli.reviewer,
        "draft_comments",
        lambda diff, evidence: reviewer_calls.append(list(evidence)) or {
            "comments": [{"severity": "note", "comment": f"round {len(reviewer_calls)}"}],
            "source": "llm",
        },
    )
    judge_calls = []
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: judge_calls.append((list(evidence), list(comments))) or {
            "verdict": "approve",
            "justification": "All facts gathered.",
            "source": "llm",
        },
    )

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"))

    assert result["investigation"]["current_round"] == 1
    assert "check_container_base_image_pinning" in result["investigation"]["completed_capabilities"]
    assert len(result["investigation"]["requested_goals"]) == 1
    assert result["investigation"]["unresolved_goals"] == []

    # Reviewer called twice: initial round 0 and after investigation round 1
    assert len(reviewer_calls) == 2
    # First reviewer call had only lint evidence (1 item)
    assert len(reviewer_calls[0]) == 1
    assert reviewer_calls[0][0]["capability"] == "lint_python"
    # Second reviewer call had accumulated evidence (lint + docker = 2 items)
    assert len(reviewer_calls[1]) == 2
    assert {e["capability"] for e in reviewer_calls[1]} == {"lint_python", "check_container_base_image_pinning"}

    # Judge received all 2 evidence items and final comments
    assert len(judge_calls) == 1
    j_evidence, j_comments = judge_calls[0]
    assert len(j_evidence) == 2
    assert j_comments[0]["comment"] == "round 2"


def test_multiple_investigation_rounds(mock_review_env, monkeypatch, tmp_path):
    """Multiple investigation rounds sequentially accumulate facts across rounds."""
    def mock_plan_investigation(diff, evidence, comments, state):
        if state.current_round == 0:
            return {
                "investigate": True,
                "goals": [
                    InvestigationGoal(
                        question="Check security?",
                        required_capability="detect_python_security",
                        reason="Need security scan.",
                    )
                ],
                "source": "llm",
            }
        elif state.current_round == 1:
            return {
                "investigate": True,
                "goals": [
                    InvestigationGoal(
                        question="Check container pinning?",
                        required_capability="check_container_base_image_pinning",
                        reason="Need container scan.",
                    )
                ],
                "source": "llm",
            }
        return {"investigate": False, "goals": [], "source": "llm"}

    monkeypatch.setattr(cli.investigation_planner, "plan_investigation", mock_plan_investigation)

    reviewer_calls = []
    monkeypatch.setattr(
        cli.reviewer,
        "draft_comments",
        lambda diff, evidence: reviewer_calls.append(list(evidence)) or {"comments": [], "source": "llm"},
    )
    judge_calls = []
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: judge_calls.append(list(evidence)) or {"verdict": "approve", "source": "llm"},
    )

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"), max_rounds=3)

    assert result["investigation"]["current_round"] == 2
    assert len(result["investigation"]["requested_goals"]) == 2
    assert {"detect_python_security", "check_container_base_image_pinning"}.issubset(
        result["investigation"]["completed_capabilities"]
    )
    # Reviewer called 3 times (initial + round 1 + round 2)
    assert len(reviewer_calls) == 3
    # Judge received accumulated evidence from all 3 tool runs (lint + security + docker)
    assert len(judge_calls[0]) == 3


def test_max_rounds_termination(mock_review_env, monkeypatch, tmp_path):
    """Ensure the loop terminates strictly at max_rounds even when planner continuously requests more."""
    planner_calls = 0

    def endless_investigation(diff, evidence, comments, state):
        nonlocal planner_calls
        planner_calls += 1

        capabilities = [
            "detect_python_security",
            "check_container_base_image_pinning",
            "lint_python",
        ]

        capability = capabilities[state.current_round]

        return {
            "investigate": True,
            "goals": [
                InvestigationGoal(
                    question=f"Need facts for {capability}?",
                    required_capability=capability,
                    reason="Ongoing investigation.",
                )
            ],
            "source": "llm",
        }

    monkeypatch.setattr(cli.investigation_planner, "plan_investigation", endless_investigation)
    monkeypatch.setattr(cli.reviewer, "draft_comments", lambda diff, evidence: {"comments": [], "source": "llm"})
    judge_calls = []
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: judge_calls.append(True) or {"verdict": "approve", "source": "llm"},
    )

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"), max_rounds=2)

    assert result["investigation"]["current_round"] == 2
    assert planner_calls == 2
    assert len(judge_calls) == 1


def test_malformed_investigation_planner_output(mock_review_env, monkeypatch, tmp_path):
    """Malformed output from InvestigationPlanner is caught safely and defaults to no investigation."""
    monkeypatch.setattr(
        cli.investigation_planner,
        "call_llm_json",
        lambda prompt: {"investigate": "not-a-boolean", "goals": "not-a-list"},
    )
    judge_calls = []
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: judge_calls.append(True) or {"verdict": "approve", "source": "rule"},
    )

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"))

    assert result["investigation"]["current_round"] == 0
    assert result["investigation"]["requested_goals"] == []
    assert len(judge_calls) == 1


def test_unsupported_capability_request(mock_review_env, monkeypatch, tmp_path):
    """When an unsupported capability is requested, it is recorded as unresolved without crashing."""
    def mock_plan(diff, evidence, comments, state):
        if state.current_round == 0:
            return {
                "investigate": True,
                "goals": [
                    InvestigationGoal(
                        question="Trace external taint?",
                        required_capability="trace_external_taint",
                        reason="Need deep dataflow analysis.",
                    )
                ],
                "source": "llm",
            }
        return {"investigate": False, "goals": [], "source": "llm"}

    monkeypatch.setattr(cli.investigation_planner, "plan_investigation", mock_plan)
    monkeypatch.setattr(cli.reviewer, "draft_comments", lambda diff, evidence: {"comments": [], "source": "llm"})
    monkeypatch.setattr(cli.judge, "decide_verdict", lambda diff, evidence, comments: {"verdict": "comment", "source": "llm"})

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"))

    assert result["investigation"]["current_round"] == 1
    assert "trace_external_taint" not in result["investigation"]["completed_capabilities"]
    assert len(result["investigation"]["unresolved_goals"]) == 1
    assert result["investigation"]["unresolved_goals"][0]["required_capability"] == "trace_external_taint"


def test_repeated_unsupported_capability_is_not_reinvestigated(
    mock_review_env, monkeypatch, tmp_path
):
    """An unsupported capability is recorded once and not retried in a later round."""
    planner_calls = []

    def mock_plan(diff, evidence, comments, state):
        planner_calls.append(state.current_round)
        return {
            "investigate": True,
            "goals": [
                InvestigationGoal(
                    question="Trace external taint?",
                    required_capability="trace_external_taint",
                    reason="Need deep dataflow analysis.",
                )
            ],
            "source": "llm",
        }

    monkeypatch.setattr(
        cli.investigation_planner,
        "plan_investigation",
        mock_plan,
    )
    monkeypatch.setattr(
        cli.reviewer,
        "draft_comments",
        lambda diff, evidence: {"comments": [], "source": "llm"},
    )
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: {
            "verdict": "comment",
            "source": "llm",
        },
    )

    result = cli.review(
        "repo",
        "feature",
        log_path=str(tmp_path / "runs.jsonl"),
        max_rounds=2,
    )

    assert planner_calls == [0, 1]
    assert result["investigation"]["current_round"] == 1
    assert len(result["investigation"]["requested_goals"]) == 1
    assert len(result["investigation"]["unresolved_goals"]) == 1
    assert result["investigation"]["unresolved_goals"][0]["required_capability"] == (
        "trace_external_taint"
    )


def test_repeated_completed_capability_is_not_reinvestigated(
    mock_review_env, monkeypatch, tmp_path
):
    """A capability already completed is not executed again."""
    planner_calls = []
    ruff_calls = []

    def mock_ruff(repo, files):
        ruff_calls.append(True)
        return [
            {
                "file": "app.py",
                "line": 1,
                "issue": "unused import",
                "code": "F401",
            }
        ]

    monkeypatch.setattr(tools, "run_ruff", mock_ruff)

    def mock_plan(diff, evidence, comments, state):
        planner_calls.append(state.current_round)
        return {
            "investigate": True,
            "goals": [
                InvestigationGoal(
                    question="Check lint again?",
                    required_capability="lint_python",
                    reason="Verify lint findings.",
                )
            ],
            "source": "llm",
        }

    monkeypatch.setattr(
        cli.investigation_planner,
        "plan_investigation",
        mock_plan,
    )
    monkeypatch.setattr(
        cli.reviewer,
        "draft_comments",
        lambda diff, evidence: {"comments": [], "source": "llm"},
    )
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: {
            "verdict": "approve",
            "source": "llm",
        },
    )

    result = cli.review(
        "repo",
        "feature",
        log_path=str(tmp_path / "runs.jsonl"),
        max_rounds=2,
    )

    assert planner_calls == [0]
    assert len(ruff_calls) == 1
    assert result["investigation"]["current_round"] == 0
    assert result["investigation"]["requested_goals"] == []

def test_investigation_planner_failure_fallback(mock_review_env, monkeypatch, tmp_path):
    """When LLM raises LLMError during investigation planning, fallback cleanly continues to Judge."""
    monkeypatch.setattr(
        cli.investigation_planner,
        "call_llm_json",
        lambda prompt: (_ for _ in ()).throw(LLMError("offline")),
    )
    judge_called = False

    def mock_judge(diff, evidence, comments):
        nonlocal judge_called
        judge_called = True
        return {"verdict": "approve", "justification": "Fallback judge.", "source": "fallback"}

    monkeypatch.setattr(cli.judge, "decide_verdict", mock_judge)

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"))

    assert result["investigation"]["current_round"] == 0
    assert judge_called is True
    assert result["verdict"]["verdict"] == "approve"


def test_accumulated_evidence_reaching_reviewer_and_judge(mock_review_env, monkeypatch, tmp_path):
    """Verify that both Reviewer and Judge receive the complete accumulated evidence chain."""
    def mock_plan(diff, evidence, comments, state):
        if state.current_round == 0:
            return {
                "investigate": True,
                "goals": [
                    InvestigationGoal(
                        question="Check security?",
                        required_capability="detect_python_security",
                        reason="Check for passwords.",
                    )
                ],
                "source": "llm",
            }
        return {"investigate": False, "goals": [], "source": "llm"}

    monkeypatch.setattr(cli.investigation_planner, "plan_investigation", mock_plan)

    captured_reviewer_evidence = []
    monkeypatch.setattr(
        cli.reviewer,
        "draft_comments",
        lambda diff, evidence: captured_reviewer_evidence.append(list(evidence)) or {"comments": [], "source": "llm"},
    )

    captured_judge_evidence = []
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: captured_judge_evidence.append(list(evidence)) or {
            "verdict": "request_changes",
            "source": "llm",
        },
    )

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"))

    # Initial evidence has 1 item (ruff lint)
    assert len(captured_reviewer_evidence[0]) == 1
    assert captured_reviewer_evidence[0][0]["tool"] == "ruff"

    # Post-investigation evidence has 2 items (ruff + bandit)
    assert len(captured_reviewer_evidence[1]) == 2
    assert {e["tool"] for e in captured_reviewer_evidence[1]} == {"ruff", "bandit"}

    # Judge received the same 2 items
    assert len(captured_judge_evidence[0]) == 2
    assert {e["tool"] for e in captured_judge_evidence[0]} == {"ruff", "bandit"}


def test_state_and_round_transitions(mock_review_env, monkeypatch, tmp_path):
    """Verify round, completed capabilities, unresolved goals, and evidence transitions."""
    states_observed = []

    def mock_plan(diff, evidence, comments, state):
        states_observed.append({
            "round": state.current_round,
            "next_round": state.next_round,
            "completed": set(state.completed_capabilities),
            "unresolved": len(state.unresolved_goals),
        })
        if state.current_round == 0:
            return {
                "investigate": True,
                "goals": [
                    InvestigationGoal("Q1", "detect_python_security", "R1"),
                    InvestigationGoal("Q2", "unsupported_cap", "R2"),
                ],
                "source": "llm",
            }
        return {"investigate": False, "goals": [], "source": "llm"}

    monkeypatch.setattr(cli.investigation_planner, "plan_investigation", mock_plan)
    monkeypatch.setattr(cli.reviewer, "draft_comments", lambda diff, evidence: {"comments": [], "source": "llm"})
    monkeypatch.setattr(cli.judge, "decide_verdict", lambda diff, evidence, comments: {"verdict": "approve", "source": "llm"})

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"))

    assert len(states_observed) == 2
    # Round 0 check: initial capabilities recorded
    assert states_observed[0]["round"] == 0
    assert states_observed[0]["next_round"] == 1
    assert "lint_python" in states_observed[0]["completed"]
    assert states_observed[0]["unresolved"] == 0

    # Round 1 check: 1 supported added to completed, 1 unsupported added to unresolved
    assert states_observed[1]["round"] == 1
    assert states_observed[1]["next_round"] == 2
    assert "detect_python_security" in states_observed[1]["completed"]
    assert states_observed[1]["unresolved"] == 1


def test_cli_end_to_end_integration_of_investigation_loop(mock_review_env, monkeypatch, tmp_path):
    """Verify full end-to-end audit logging of investigation events to JSONL."""
    log_file = tmp_path / "test_verdict_runs.jsonl"

    def mock_plan(diff, evidence, comments, state):
        if state.current_round == 0:
            return {
                "investigate": True,
                "goals": [
                    InvestigationGoal("Check Docker?", "check_container_base_image_pinning", "Need image tag")
                ],
                "source": "llm",
            }
        return {"investigate": False, "goals": [], "source": "llm"}

    monkeypatch.setattr(cli.investigation_planner, "plan_investigation", mock_plan)
    monkeypatch.setattr(
        cli.reviewer,
        "draft_comments",
        lambda diff, evidence: {"comments": [{"severity": "blocking", "comment": "Unpinned Docker image"}], "source": "llm"},
    )
    monkeypatch.setattr(
        cli.judge,
        "decide_verdict",
        lambda diff, evidence, comments: {"verdict": "request_changes", "justification": "Docker issue.", "source": "llm"},
    )

    result = cli.review("repo", "feature", log_path=str(log_file))

    assert result["verdict"]["verdict"] == "request_changes"
    assert result["investigation"]["current_round"] == 1

    # Verify log output
    with open(log_file) as f:
        events = [json.loads(line) for line in f]

    stages = [e["stage"] for e in events]
    assert stages == [
        "diff",
        "planner",
        "tool_registry",
        "scan_results",
        "reviewer",
        "investigation_planner",
        "investigation_registry",
        "investigation_results",
        "reviewer",
        "investigation_planner",
        "judge",
    ]

    # Verify round numbers in logged events
    inv_plan_1 = events[5]
    assert inv_plan_1["round"] == 1
    assert inv_plan_1["investigate"] is True

    inv_plan_2 = events[9]
    assert inv_plan_2["round"] == 2
    assert inv_plan_2["investigate"] is False
