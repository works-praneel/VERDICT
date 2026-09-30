"""Tests for verify_llm diagnostic script."""
from types import SimpleNamespace
import pytest

import verify_llm
from verdict.llm import LLMError


def test_verify_llm_run_scenario_passes_evidence_to_reviewer_and_judge(monkeypatch):
    class FakeRepo:
        def __init__(self, repo_path):
            self.active_branch = SimpleNamespace(name="main")
            self.git = SimpleNamespace(checkout=lambda branch: None)

    monkeypatch.setattr(verify_llm, "Repo", FakeRepo)
    monkeypatch.setattr(
        verify_llm,
        "get_diff",
        lambda repo, branch, base: {"changed_files": ["app.py"], "diff_text": "+BILLING_KEY=secret"},
    )
    monkeypatch.setattr(
        verify_llm.scanner,
        "decide_tools",
        lambda files: {"tools": ["bandit", "ruff", "check_test_delta"], "reason": "code", "source": "llm"},
    )
    monkeypatch.setattr(
        verify_llm,
        "run_bandit",
        lambda repo, files: [{"file": "app.py", "line": 1, "issue": "Hardcoded password", "severity": "LOW"}],
    )
    monkeypatch.setattr(
        verify_llm,
        "run_ruff",
        lambda repo, files: [{"file": "app.py", "line": 2, "issue": "Unused import", "code": "F401"}],
    )
    monkeypatch.setattr(
        verify_llm,
        "check_test_delta",
        lambda diff, files: {
            "new_functions": ["foo"],
            "new_test_functions": [],
            "test_files_touched": [],
            "missing_coverage": True,
        },
    )

    reviewer_calls = []

    def fake_draft_comments(diff_text, evidence):
        reviewer_calls.append((diff_text, evidence))
        return {
            "comments": [{"severity": "blocking", "file": "app.py", "line": 1, "comment": "Fix secret"}],
            "source": "llm",
        }

    judge_calls = []

    def fake_decide_verdict(diff_text, evidence, comments):
        judge_calls.append((diff_text, evidence, comments))
        return {
            "verdict": "request_changes",
            "justification": "Secret found.",
            "source": "llm",
        }

    monkeypatch.setattr(verify_llm.reviewer, "draft_comments", fake_draft_comments)
    monkeypatch.setattr(verify_llm.judge, "decide_verdict", fake_decide_verdict)

    result = verify_llm.run_scenario(
        "feature/hardcoded-secret",
        "request_changes",
        "LLM should override Bandit LOW rating",
    )

    assert result["match"] is True
    assert result["actual"] == "request_changes"
    assert result["reviewer_source"] == "llm"
    assert result["judge_source"] == "llm"

    # Verify reviewer was called with (diff_text, evidence)
    assert len(reviewer_calls) == 1
    diff_text, evidence = reviewer_calls[0]
    assert diff_text == "+BILLING_KEY=secret"
    assert len(evidence) == 3
    evidence_tools = {item["tool"] for item in evidence}
    assert evidence_tools == {"bandit", "ruff", "check_test_delta"}

    # Verify judge was called with (diff_text, evidence, comments)
    assert len(judge_calls) == 1
    j_diff, j_evidence, j_comments = judge_calls[0]
    assert j_diff == "+BILLING_KEY=secret"
    assert j_evidence == evidence
    assert j_comments == [{"severity": "blocking", "file": "app.py", "line": 1, "comment": "Fix secret"}]


def test_check_ollama_reachable_exits_on_error(monkeypatch):
    monkeypatch.setattr(verify_llm, "call_llm", lambda prompt: (_ for _ in ()).throw(LLMError("offline")))
    with pytest.raises(SystemExit) as exc_info:
        verify_llm.check_ollama_reachable()
    assert exc_info.value.code == 1


def test_check_ollama_reachable_succeeds_when_online(monkeypatch):
    monkeypatch.setattr(verify_llm, "call_llm", lambda prompt: "OK")
    verify_llm.check_ollama_reachable()
