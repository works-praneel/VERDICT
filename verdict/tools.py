"""Deterministic tool wrappers. No LLM involved here on purpose — these are
the ground-truth facts the agents reason over, so they need to be boring
and correct before anything else gets built on top of them.
"""
import json
import re
import subprocess
from pathlib import Path

from git import Repo


def get_diff(repo_path: str, branch: str, base: str = "main") -> dict:
    """Return the changed files and unified diff text between base and branch."""
    repo = Repo(repo_path)
    base_commit = repo.commit(base)
    branch_commit = repo.commit(branch)
    diff_index = base_commit.diff(branch_commit, create_patch=True)

    changed_files = [d.b_path or d.a_path for d in diff_index]
    diff_text = "\n".join(
        d.diff.decode("utf-8", errors="replace") for d in diff_index
    )
    return {"changed_files": changed_files, "diff_text": diff_text}


def run_bandit(repo_path: str, file_paths: list) -> list:
    """Run Bandit's security scan on the changed Python files.

    Test files are excluded on purpose: bandit's B101 flags any use of
    `assert`, which is the normal, expected way to write a pytest test —
    running bandit on test files just produces noise.
    """
    py_files = [
        f for f in file_paths if f.endswith(".py") and "test" not in Path(f).name.lower()
    ]
    full_paths = [
        str(Path(repo_path) / f) for f in py_files if Path(repo_path, f).exists()
    ]
    if not full_paths:
        return []

    result = subprocess.run(
        ["bandit", "-f", "json", *full_paths],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return [
        {
            "file": Path(r["filename"]).name,
            "line": r["line_number"],
            "issue": r["issue_text"],
            "severity": r["issue_severity"],
        }
        for r in data.get("results", [])
    ]


def run_ruff(repo_path: str, file_paths: list) -> list:
    """Run Ruff's style/lint scan on the changed Python files."""
    py_files = [f for f in file_paths if f.endswith(".py")]
    full_paths = [
        str(Path(repo_path) / f) for f in py_files if Path(repo_path, f).exists()
    ]
    if not full_paths:
        return []

    result = subprocess.run(
        ["ruff", "check", "--output-format=json", *full_paths],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return [
        {
            "file": Path(r["filename"]).name,
            "line": r["location"]["row"],
            "issue": r["message"],
            "code": r["code"],
        }
        for r in data
    ]


def check_test_delta(diff_text: str, changed_files: list) -> dict:
    """Flag new functions added to source files with no matching new test function.

    This is a demo-scale heuristic, not a real coverage tool: it looks at
    added lines across the whole diff rather than per-file, which is good
    enough to distinguish the four planted scenarios but would need proper
    per-file diff parsing for real-world use.
    """
    added_lines = [
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]

    added_func_names = []
    for line in added_lines:
        match = re.match(r"\s*def (\w+)", line)
        if match:
            added_func_names.append(match.group(1))

    new_test_funcs = [f for f in added_func_names if f.startswith("test_")]
    new_source_funcs = [f for f in added_func_names if not f.startswith("test_")]
    test_files_touched = [f for f in changed_files if "test" in Path(f).name.lower()]

    missing_coverage = bool(new_source_funcs) and not new_test_funcs

    return {
        "new_functions": new_source_funcs,
        "new_test_functions": new_test_funcs,
        "test_files_touched": test_files_touched,
        "missing_coverage": missing_coverage,
    }
