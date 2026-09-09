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


def check_container_base_image_pinning(diff_text: str, changed_files: list) -> list[dict]:
    """Find added Dockerfile FROM instructions without a version pin.

    This deliberately inspects diff text only. It does not require, contact, or
    execute Docker in any form.
    """
    dockerfiles = [path for path in changed_files if Path(path).name.lower() == "dockerfile"]
    current_file = dockerfiles[0] if len(dockerfiles) == 1 else None
    current_line = None
    findings = []

    for diff_line in diff_text.splitlines():
        if diff_line.startswith("+++ b/"):
            current_file = diff_line[6:]
            continue
        hunk = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", diff_line)
        if hunk:
            current_line = int(hunk.group(1))
            continue
        if diff_line.startswith("+") and not diff_line.startswith("+++"):
            added_line = diff_line[1:]
            match = re.match(r"\s*FROM\s+(?:--\S+\s+)*([^\s#]+)", added_line, re.IGNORECASE)
            if current_file and Path(current_file).name.lower() == "dockerfile" and match:
                image = match.group(1)
                image_name = image.rsplit("/", 1)[-1]
                is_latest = image_name.endswith(":latest")
                is_untagged = "@" not in image and ":" not in image_name
                if is_latest or is_untagged:
                    findings.append(
                        {
                            "file": current_file,
                            "line": current_line,
                            "image": image,
                            "reason": "latest" if is_latest else "untagged",
                        }
                    )
            if current_line is not None:
                current_line += 1
        elif not diff_line.startswith("-") and current_line is not None:
            current_line += 1

    return findings
