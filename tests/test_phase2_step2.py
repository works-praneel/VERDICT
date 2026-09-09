"""Focused Phase 2 Step 2 tests for trusted evidence wiring."""
import pytest
from types import SimpleNamespace

from verdict import cli, tools
from verdict.context import ReviewContext
from verdict.evidence import (
    bandit_findings_to_evidence,
    coverage_delta_to_evidence,
    ruff_findings_to_evidence,
)
from verdict.tool_registry import ToolRegistration, ToolRegistry, ToolResolution


def test_each_registration_owns_its_fixed_evidence_adapter():
    registry = ToolRegistry()
    assert registry._registrations["detect_python_security"].evidence_adapter is bandit_findings_to_evidence
    assert registry._registrations["lint_python"].evidence_adapter is ruff_findings_to_evidence
    assert registry._registrations["check_new_python_test_coverage"].evidence_adapter is coverage_delta_to_evidence


def test_registry_normalizes_bandit_ruff_and_test_delta_while_preserving_raw_results(monkeypatch):
    monkeypatch.setattr(tools, "run_bandit", lambda repo, files: [{"file": "app.py", "line": 2, "issue": "secret", "severity": "HIGH"}])
    monkeypatch.setattr(tools, "run_ruff", lambda repo, files: [{"file": "app.py", "line": 4, "issue": "unused", "code": "F401"}])
    monkeypatch.setattr(tools, "check_test_delta", lambda diff, files: {"new_functions": ["f"], "new_test_functions": [], "test_files_touched": [], "missing_coverage": True})
    registry = ToolRegistry()

    execution = registry.execute(
        registry.resolve(["detect_python_security", "lint_python", "check_new_python_test_coverage"]),
        "repo", ["app.py"], "diff",
    )

    assert execution.raw_results["bandit"][0]["issue"] == "secret"
    assert {item["tool"] for item in execution.evidence} == {"bandit", "ruff", "check_test_delta"}


def test_clean_trusted_results_produce_no_evidence(monkeypatch):
    monkeypatch.setattr(tools, "run_bandit", lambda repo, files: [])
    registry = ToolRegistry()
    execution = registry.execute(registry.resolve(["detect_python_security"]), "repo", [], "")
    assert execution.evidence == []


def test_unsupported_capability_remains_unsupported():
    resolution = ToolRegistry().resolve(["analyze_container_configuration"])
    assert resolution.supported == ()
    assert resolution.unsupported == ("analyze_container_configuration",)


def test_forged_registration_is_rejected_before_its_adapter_or_callable_runs():
    calls = []
    forged = ToolRegistration(
        "forged", "ruff", lambda repo, files: calls.append("call"), "repo_files", lambda raw: calls.append("adapter")
    )

    with pytest.raises(RuntimeError, match="Untrusted tool registration"):
        ToolRegistry().execute(ToolResolution((forged,), ()), "repo", [], "")

    assert calls == []


def test_review_context_stores_normalized_evidence():
    raw_results = {"bandit": [{"file": "app.py", "line": 2, "issue": "secret", "severity": "HIGH"}]}
    context = ReviewContext(
        tool_results=raw_results,
        evidence=bandit_findings_to_evidence(raw_results["bandit"]),
    )
    assert context.evidence[0]["tool"] == "bandit"
    assert context.tool_results is raw_results


def test_scanner_fallback_uses_registry_evidence_wiring(monkeypatch):
    monkeypatch.setattr(tools, "run_ruff", lambda repo, files: [{"file": "app.py", "line": 1, "issue": "unused", "code": "F401"}])
    execution = cli._run_legacy_tools({"tools": ["ruff"]}, "repo", {"changed_files": ["app.py"], "diff_text": ""})
    assert execution.evidence[0]["tool"] == "ruff"


def test_normal_cli_planner_path_returns_registry_normalized_evidence(monkeypatch, tmp_path):
    class FakeRepo:
        def __init__(self, repo_path):
            self.active_branch = SimpleNamespace(name="main")
            self.head = SimpleNamespace(is_detached=False)
            self.git = SimpleNamespace(checkout=lambda branch: None)

    monkeypatch.setattr(cli, "get_diff", lambda *args: {"changed_files": ["app.py"], "diff_text": "diff"})
    monkeypatch.setattr(
        cli.planner,
        "plan",
        lambda *args: {"capabilities": ["detect_python_security"], "reason": "Python changed"},
    )
    monkeypatch.setattr(cli, "Repo", FakeRepo)
    monkeypatch.setattr(
        tools,
        "run_bandit",
        lambda repo, files: [{"file": "app.py", "line": 2, "issue": "secret", "severity": "HIGH"}],
    )
    reviewer_calls = []
    monkeypatch.setattr(
        cli.reviewer,
        "draft_comments",
        lambda diff, evidence: reviewer_calls.append((diff, evidence)) or {"comments": []},
    )
    monkeypatch.setattr(cli.judge, "decide_verdict", lambda comments: {"verdict": "approve"})

    result = cli.review("repo", "feature", log_path=str(tmp_path / "runs.jsonl"))

    assert result["evidence"] == [
        {
            "capability": "detect_python_security",
            "tool": "bandit",
            "kind": "security",
            "file": "app.py",
            "line": 2,
            "message": "secret",
            "severity": "high",
            "rule_id": None,
            "details": {"source_severity": "HIGH"},
        }
    ]
    assert reviewer_calls == [("diff", result["evidence"])]
