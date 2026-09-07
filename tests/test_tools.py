"""Tests for the deterministic tool wrappers, run against the real sample_repo
git history — these must pass without any LLM involved."""
import os

import pytest

from verdict.tools import check_test_delta, get_diff, run_bandit, run_ruff

REPO = os.path.join(os.path.dirname(__file__), "..", "sample_repo")


def test_get_diff_hardcoded_secret_branch():
    diff = get_diff(REPO, "feature/hardcoded-secret", "main")
    assert diff["changed_files"] == ["app.py"]
    assert "BILLING_API_SECRET_TOKEN" in diff["diff_text"]


def test_get_diff_clean_branch_touches_test_file():
    diff = get_diff(REPO, "feature/clean-pr", "main")
    assert "tests/test_app.py" in diff["changed_files"]


def test_run_bandit_flags_hardcoded_secret():
    import git

    repo = git.Repo(REPO)
    repo.git.checkout("feature/hardcoded-secret")
    try:
        findings = run_bandit(REPO, ["app.py"])
    finally:
        repo.git.checkout("main")
    assert any("password" in f["issue"].lower() for f in findings)


def test_run_bandit_skips_test_files():
    # test files legitimately use `assert` — bandit shouldn't flag it as B101 noise
    findings = run_bandit(REPO, ["tests/test_app.py"])
    assert findings == []


def test_run_ruff_flags_unused_import():
    import git

    repo = git.Repo(REPO)
    repo.git.checkout("feature/style-issue")
    try:
        findings = run_ruff(REPO, ["app.py"])
    finally:
        repo.git.checkout("main")
    assert any("unused" in f["issue"].lower() for f in findings)


def test_check_test_delta_flags_missing_coverage():
    diff = get_diff(REPO, "feature/missing-test", "main")
    result = check_test_delta(diff["diff_text"], diff["changed_files"])
    assert result["missing_coverage"] is True
    assert "clamp" in result["new_functions"]


def test_check_test_delta_clean_pr_has_matching_test():
    diff = get_diff(REPO, "feature/clean-pr", "main")
    result = check_test_delta(diff["diff_text"], diff["changed_files"])
    assert result["missing_coverage"] is False
    assert "test_divide" in result["new_test_functions"]
