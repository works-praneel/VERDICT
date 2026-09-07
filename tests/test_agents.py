"""Tests for each agent's deterministic fallback path — these run without
Ollama so they work in any environment. The LLM path is exercised manually
once a local model is available (see README)."""
from verdict.agents import judge, reviewer, scanner


def test_scanner_fallback_skips_docs_only_change():
    result = scanner._fallback_rule(["README.md", "CHANGELOG.md"])
    assert result["tools"] == []


def test_scanner_fallback_runs_all_checks_on_source_change():
    result = scanner._fallback_rule(["app.py"])
    assert set(result["tools"]) == {"bandit", "ruff", "check_test_delta"}


def test_scanner_fallback_skips_test_delta_for_test_only_change():
    result = scanner._fallback_rule(["tests/test_app.py"])
    assert "check_test_delta" not in result["tools"]


def test_reviewer_fallback_empty_when_no_findings():
    result = reviewer._fallback_comments([], [], {"missing_coverage": False})
    assert result["comments"] == []


def test_reviewer_fallback_maps_high_severity_to_blocking():
    bandit_findings = [{"file": "app.py", "line": 1, "issue": "eval used", "severity": "HIGH"}]
    result = reviewer._fallback_comments(bandit_findings, [], {"missing_coverage": False})
    assert result["comments"][0]["severity"] == "blocking"


def test_reviewer_fallback_maps_low_severity_to_nitpick():
    bandit_findings = [{"file": "app.py", "line": 1, "issue": "hardcoded password", "severity": "LOW"}]
    result = reviewer._fallback_comments(bandit_findings, [], {"missing_coverage": False})
    assert result["comments"][0]["severity"] == "nitpick"


def test_judge_approves_with_no_comments():
    result = judge.decide_verdict([])
    assert result["verdict"] == "approve"


def test_judge_fallback_blocks_on_blocking_comment():
    comments = [{"severity": "blocking", "comment": "hardcoded secret"}]
    result = judge.decide_verdict(comments)
    assert result["verdict"] == "request_changes"


def test_judge_fallback_comments_on_nitpick_only():
    comments = [{"severity": "nitpick", "comment": "unused import"}]
    result = judge.decide_verdict(comments)
    assert result["verdict"] == "comment"
