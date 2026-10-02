"""Tests for the deterministic tool wrappers, run against the real sample_repo
git history — these must pass without any LLM involved.
"""

import os

import pytest

from verdict.tools import (
    check_test_delta,
    get_diff,
    inspect_python_test_references,
    run_bandit,
    run_ruff,
)


REPO = os.path.join(
    os.path.dirname(__file__),
    "..",
    "sample_repo",
)


def test_get_diff_hardcoded_secret_branch():
    diff = get_diff(
        REPO,
        "feature/hardcoded-secret",
        "main",
    )

    assert diff["changed_files"] == ["app.py"]
    assert "BILLING_API_SECRET_TOKEN" in diff["diff_text"]


def test_get_diff_clean_branch_touches_test_file():
    diff = get_diff(
        REPO,
        "feature/clean-pr",
        "main",
    )

    assert "tests/test_app.py" in diff["changed_files"]


def test_run_bandit_flags_hardcoded_secret():
    import git

    repo = git.Repo(REPO)

    repo.git.checkout("feature/hardcoded-secret")

    try:
        findings = run_bandit(
            REPO,
            ["app.py"],
        )
    finally:
        repo.git.checkout("main")

    assert any(
        "password" in finding["issue"].lower()
        for finding in findings
    )


def test_run_bandit_skips_test_files():
    # Test files legitimately use `assert` — Bandit shouldn't flag
    # it as B101 noise.
    findings = run_bandit(
        REPO,
        ["tests/test_app.py"],
    )

    assert findings == []


def test_run_ruff_flags_unused_import():
    import git

    repo = git.Repo(REPO)

    repo.git.checkout("feature/style-issue")

    try:
        findings = run_ruff(
            REPO,
            ["app.py"],
        )
    finally:
        repo.git.checkout("main")

    assert any(
        "unused" in finding["issue"].lower()
        for finding in findings
    )


def test_check_test_delta_flags_missing_coverage():
    diff = get_diff(
        REPO,
        "feature/missing-test",
        "main",
    )

    result = check_test_delta(
        diff["diff_text"],
        diff["changed_files"],
    )

    assert result["missing_coverage"] is True
    assert "clamp" in result["new_functions"]


def test_check_test_delta_clean_pr_has_matching_test():
    diff = get_diff(
        REPO,
        "feature/clean-pr",
        "main",
    )

    result = check_test_delta(
        diff["diff_text"],
        diff["changed_files"],
    )

    assert result["missing_coverage"] is False
    assert "test_divide" in result["new_test_functions"]


def test_check_test_delta_does_not_treat_unrelated_test_as_coverage():
    diff = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -0,0 +1,2 @@
+def clamp(value, low, high):
+    return max(low, min(value, high))
diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -0,0 +1,2 @@
+def test_other_feature():
+    assert True
"""

    result = check_test_delta(
        diff,
        ["app.py", "tests/test_app.py"],
    )

    assert result["new_functions"] == ["clamp"]
    assert result["new_test_functions"] == ["test_other_feature"]
    assert result["missing_coverage"] is True


def test_check_test_delta_ignores_non_python_and_test_helper_functions():
    diff = """\
diff --git a/docs/example.py.txt b/docs/example.py.txt
--- a/docs/example.py.txt
+++ b/docs/example.py.txt
@@ -0,0 +1 @@
+def documented():
diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -0,0 +1 @@
+def helper():
"""

    result = check_test_delta(
        diff,
        ["docs/example.py.txt", "tests/test_app.py"],
    )

    assert result["new_functions"] == []
    assert result["new_test_functions"] == ["helper"]
    assert result["missing_coverage"] is False


def test_check_test_delta_matches_test_to_its_source_function():
    diff = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -0,0 +1,2 @@
+def clamp(value, low, high):
+    return max(low, min(value, high))
diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -0,0 +1,2 @@
+def test_clamp_bounds():
+    assert clamp(5, 0, 10) == 5
"""

    result = check_test_delta(
        diff,
        ["app.py", "tests/test_app.py"],
    )

    assert result["missing_coverage"] is False


@pytest.mark.parametrize(
    ("tool", "stdout"),
    [
        ("bandit", "not json"),
        ("ruff", "not json"),
    ],
)
def test_linter_tool_failures_are_not_reported_as_clean(
    monkeypatch,
    tmp_path,
    tool,
    stdout,
):
    from types import SimpleNamespace

    from verdict import tools

    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=stdout,
            stderr="scanner failed",
            returncode=2,
        ),
    )

    run_tool = tools.run_bandit if tool == "bandit" else tools.run_ruff
    with pytest.raises(RuntimeError, match="invalid JSON"):
        run_tool(str(tmp_path), ["app.py"])


@pytest.mark.parametrize(
    ("tool", "payload"),
    [
        (
            "bandit",
            {
                "results": [
                    {
                        "filename": "src/api.py",
                        "line_number": 3,
                        "issue_text": "issue",
                        "issue_severity": "LOW",
                    }
                ]
            },
        ),
        (
            "ruff",
            [
                {
                    "filename": "src/api.py",
                    "location": {"row": 4},
                    "message": "issue",
                    "code": "F401",
                }
            ],
        ),
    ],
)
def test_tool_findings_keep_repository_relative_paths(
    monkeypatch,
    tmp_path,
    tool,
    payload,
):
    import json
    from types import SimpleNamespace

    from verdict import tools

    source_file = tmp_path / "src" / "api.py"
    source_file.parent.mkdir()
    source_file.write_text("value = 1\n", encoding="utf-8")
    finding = payload["results"][0] if tool == "bandit" else payload[0]
    finding["filename"] = str(source_file)
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps(payload),
            stderr="",
            returncode=0,
        ),
    )

    run_tool = tools.run_bandit if tool == "bandit" else tools.run_ruff
    findings = run_tool(str(tmp_path), ["src/api.py"])

    assert findings[0]["file"] == "src/api.py"


def test_inspect_python_test_references_detects_existing_reference(
    tmp_path,
):
    """Existing unchanged tests are found by repository inspection."""

    repo = tmp_path

    tests_dir = repo / "tests"
    tests_dir.mkdir()

    test_file = tests_dir / "test_app.py"

    test_file.write_text(
        """
def test_existing_clamp():
    assert clamp(5, 0, 10) == 5
""",
        encoding="utf-8",
    )

    diff = """
diff --git a/app.py b/app.py
index 123..456 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,5 @@
+def clamp(value, low, high):
+    return max(low, min(value, high))
"""

    result = inspect_python_test_references(
        str(repo),
        ["app.py"],
        diff,
    )

    assert result["referenced"] is True

    assert result["functions"][0]["function"] == "clamp"

    assert result["functions"][0]["referenced"] is True

    assert (
        "tests/test_app.py"
        in result["functions"][0]["test_files"]
    )

    assert "tests/test_app.py" in result["test_files"]


def test_inspect_python_test_references_detects_missing_reference(
    tmp_path,
):
    """A newly added function with no existing test reference is detected."""

    repo = tmp_path

    tests_dir = repo / "tests"
    tests_dir.mkdir()

    # An existing test file that does not reference clamp.
    test_file = tests_dir / "test_app.py"

    test_file.write_text(
        """
def test_other_function():
    assert True
""",
        encoding="utf-8",
    )

    diff = """
diff --git a/utils.py b/utils.py
index 123..456 100644
--- a/utils.py
+++ b/utils.py
@@ -1,1 +1,3 @@
+def clamp(value, low, high):
+    return max(low, min(value, high))
"""

    result = inspect_python_test_references(
        str(repo),
        ["utils.py"],
        diff,
    )

    assert result["referenced"] is False

    assert result["functions"][0]["function"] == "clamp"

    assert result["functions"][0]["referenced"] is False

    assert result["functions"][0]["test_files"] == []

    assert result["test_files"] == []


def test_inspect_python_test_references_ignores_non_test_python_files(
    tmp_path,
):
    """Only Python test files are inspected for references."""

    repo = tmp_path

    tests_dir = repo / "tests"
    tests_dir.mkdir()

    (repo / "helper.py").write_text(
        """
def helper():
    return clamp(5, 0, 10)
""",
        encoding="utf-8",
    )

    (tests_dir / "test_app.py").write_text(
        """
def test_other_function():
    assert True
""",
        encoding="utf-8",
    )

    diff = """
diff --git a/app.py b/app.py
index 123..456 100644
--- a/app.py
+++ b/app.py
@@ -1,1 +1,4 @@
+def clamp(value, low, high):
+    return max(low, min(value, high))
"""

    result = inspect_python_test_references(
        str(repo),
        ["app.py"],
        diff,
    )

    assert result["referenced"] is False
    assert result["functions"][0]["referenced"] is False


def test_inspect_python_test_references_returns_no_functions_without_added_functions(
    tmp_path,
):
    """No newly added function means no investigation evidence."""

    repo = tmp_path

    tests_dir = repo / "tests"
    tests_dir.mkdir()

    (tests_dir / "test_app.py").write_text(
        """
def test_existing():
    assert True
""",
        encoding="utf-8",
    )

    diff = """
diff --git a/app.py b/app.py
index 123..456 100644
--- a/app.py
+++ b/app.py
@@ -1,1 +1,2 @@
+VALUE = 42
"""

    result = inspect_python_test_references(
        str(repo),
        ["app.py"],
        diff,
    )

    assert result == {
        "functions": [],
        "referenced": False,
        "test_files": [],
    }

def test_inspect_python_test_references_ignores_test_functions(tmp_path):
    repo = tmp_path

    tests_dir = repo / "tests"
    tests_dir.mkdir()

    (repo / "app.py").write_text(
        "def divide(a, b):\n"
        "    return a / b\n",
        encoding="utf-8",
    )

    (tests_dir / "test_app.py").write_text(
        "def test_divide():\n"
        "    assert divide(4, 2) == 2\n"
        "\n"
        "def test_divide_by_zero_raises():\n"
        "    pass\n",
        encoding="utf-8",
    )

    diff = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -0,0 +1,2 @@
+def divide(a, b):
+    return a / b
diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -0,0 +1,5 @@
+def test_divide():
+    assert divide(4, 2) == 2
+
+def test_divide_by_zero_raises():
+    pass
"""

    result = inspect_python_test_references(
        str(repo),
        ["app.py", "tests/test_app.py"],
        diff,
    )

    assert result["functions"] == [
        {
            "function": "divide",
            "referenced": True,
            "test_files": ["tests/test_app.py"],
        }
    ]
