"""Deterministic tool wrappers. No LLM involved here on purpose — these are
the ground-truth facts the agents reason over, so they need to be boring
and correct before anything else gets built on top of them.
"""

import json
import re
import subprocess
from pathlib import Path

from git import Repo


def _repo_relative_path(repo_path: str, file_path: str) -> str:
    """Return tool-reported paths relative to the reviewed repository."""
    repo_root = Path(repo_path).resolve()
    resolved_path = Path(file_path).resolve()

    try:
        return resolved_path.relative_to(repo_root).as_posix()
    except ValueError as error:
        raise RuntimeError(
            f"Tool reported a file outside the repository: {file_path}"
        ) from error


def get_diff(repo_path: str, branch: str, base: str = "main") -> dict:
    """Return changed files and a file-aware unified diff."""
    repo = Repo(repo_path)
    base_commit = repo.commit(base)
    branch_commit = repo.commit(branch)
    diff_index = base_commit.diff(branch_commit, create_patch=True)

    changed_files = [d.b_path or d.a_path for d in diff_index]

    diff_parts = []

    for diff in diff_index:
        path = diff.b_path or diff.a_path

        patch = diff.diff.decode("utf-8", errors="replace")

        diff_parts.append(
            "\n".join(
                [
                    f"diff --git a/{path} b/{path}",
                    f"--- a/{path}",
                    f"+++ b/{path}",
                    patch,
                ]
            )
        )

    return {
        "changed_files": changed_files,
        "diff_text": "\n".join(diff_parts),
    }

def run_bandit(repo_path: str, file_paths: list) -> list:
    """Run Bandit's security scan on the changed Python files.

    Test files are excluded on purpose: bandit's B101 flags any use of
    `assert`, which is the normal, expected way to write a pytest test —
    running bandit on test files just produces noise.
    """
    py_files = [
        f
        for f in file_paths
        if f.endswith(".py") and "test" not in Path(f).name.lower()
    ]

    full_paths = [
        str(Path(repo_path) / f)
        for f in py_files
        if Path(repo_path, f).exists()
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
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Bandit returned invalid JSON "
            f"(exit code {result.returncode}): {result.stderr[:300]}"
        ) from error

    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise RuntimeError("Bandit returned JSON without a results list.")

    return [
        {
            "file": _repo_relative_path(repo_path, r["filename"]),
            "line": r["line_number"],
            "issue": r["issue_text"],
            "severity": r["issue_severity"],
        }
        for r in data.get("results", [])
    ]


def run_ruff(repo_path: str, file_paths: list) -> list:
    """Run Ruff's style/lint scan on the changed Python files."""
    py_files = [
        f for f in file_paths
        if f.endswith(".py")
    ]

    full_paths = [
        str(Path(repo_path) / f)
        for f in py_files
        if Path(repo_path, f).exists()
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
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Ruff returned invalid JSON "
            f"(exit code {result.returncode}): {result.stderr[:300]}"
        ) from error

    if not isinstance(data, list):
        raise RuntimeError("Ruff returned JSON that was not a findings list.")

    return [
        {
            "file": _repo_relative_path(repo_path, r["filename"]),
            "line": r["location"]["row"],
            "issue": r["message"],
            "code": r["code"],
        }
        for r in data
    ]


def check_test_delta(diff_text: str, changed_files: list) -> dict:
    """Flag added source functions without a corresponding added test function."""
    def is_test_file(path: str) -> bool:
        normalized = path.replace("\\", "/")
        filename = normalized.rsplit("/", 1)[-1].lower()
        parts = {part.lower() for part in normalized.split("/")}
        return (
            "tests" in parts
            or filename.startswith("test_")
            or filename.endswith("_test.py")
        )

    new_source_funcs = []
    new_test_funcs = []
    current_file = None

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            continue

        if not line.startswith("+") or line.startswith("+++"):
            continue

        if current_file is None or not current_file.lower().endswith(".py"):
            continue

        match = re.match(
            r"\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            line[1:],
        )
        if not match:
            continue

        function_name = match.group(1)
        target = new_test_funcs if is_test_file(current_file) else new_source_funcs
        if function_name not in target:
            target.append(function_name)

    test_files_touched = [
        f
        for f in changed_files
        if is_test_file(f)
    ]

    missing_coverage = any(
        not any(
            test_name == f"test_{function_name}"
            or test_name.startswith(f"test_{function_name}_")
            for test_name in new_test_funcs
        )
        for function_name in new_source_funcs
    )

    return {
        "new_functions": new_source_funcs,
        "new_test_functions": new_test_funcs,
        "test_files_touched": test_files_touched,
        "missing_coverage": missing_coverage,
    }


def check_container_base_image_pinning(
    diff_text: str,
    changed_files: list,
) -> list[dict]:
    """Find added Dockerfile FROM instructions without a version pin.

    This deliberately inspects diff text only. It does not require, contact,
    or execute Docker in any form.
    """
    dockerfiles = [
        path
        for path in changed_files
        if Path(path).name.lower() == "dockerfile"
    ]

    current_file = dockerfiles[0] if len(dockerfiles) == 1 else None
    current_line = None
    findings = []

    for diff_line in diff_text.splitlines():
        if diff_line.startswith("+++ b/"):
            current_file = diff_line[6:]
            continue

        hunk = re.match(
            r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@",
            diff_line,
        )

        if hunk:
            current_line = int(hunk.group(1))
            continue

        if diff_line.startswith("+") and not diff_line.startswith("+++"):
            added_line = diff_line[1:]

            match = re.match(
                r"\s*FROM\s+(?:--\S+\s+)*([^\s#]+)",
                added_line,
                re.IGNORECASE,
            )

            if (
                current_file
                and Path(current_file).name.lower() == "dockerfile"
                and match
            ):
                image = match.group(1)
                image_name = image.rsplit("/", 1)[-1]

                is_digest_pinned = "@" in image
                is_latest = (
                    image_name.endswith(":latest")
                    and not is_digest_pinned
                )
                is_untagged = (
                    not is_digest_pinned
                    and ":" not in image_name
                    and image.lower() != "scratch"
                )

                if is_latest or is_untagged:
                    findings.append(
                        {
                            "file": current_file,
                            "line": current_line,
                            "image": image,
                            "reason": (
                                "latest"
                                if is_latest
                                else "untagged"
                            ),
                        }
                    )

            if current_line is not None:
                current_line += 1

        elif (
            not diff_line.startswith("-")
            and current_line is not None
        ):
            current_line += 1

    return findings


def inspect_python_test_references(
    repo_path: str,
    changed_files: list[str],
    diff_text: str,
) -> dict:
    """Inspect existing Python tests for references to newly added source functions.

    This is intentionally deterministic and read-only. It does not execute
    tests or arbitrary commands.

    Only functions added to non-test Python files are considered. Test
    functions themselves are not investigation targets.

    Unlike check_test_delta(), this inspection searches the checked-out
    repository's existing Python test files, including tests that were not
    modified by the current PR.
    """

    def is_test_file(path: str) -> bool:
        normalized = path.replace("\\", "/")
        parts = Path(normalized).parts
        filename = Path(normalized).name.lower()

        return (
            "tests" in {part.lower() for part in parts}
            or filename.startswith("test_")
            or filename.endswith("_test.py")
        )

    # Track the file associated with each added line. A unified diff can
    # contain multiple files, so we must not search the whole diff blindly.
    added_functions: set[str] = set()
    current_file: str | None = None

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue

        if (
            current_file is None
            or not current_file.endswith(".py")
            or is_test_file(current_file)
        ):
            continue

        if line.startswith("+") and not line.startswith("+++"):
            added_line = line[1:]

            match = re.match(
                r"\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                added_line,
            )

            if match:
                added_functions.add(match.group(1))

    if not added_functions:
        return {
            "functions": [],
            "referenced": False,
            "test_files": [],
        }

    repo = Path(repo_path)

    test_files = []

    for path in repo.rglob("*.py"):
        if ".git" in path.parts:
            continue

        relative_path = str(
            path.relative_to(repo)
        ).replace("\\", "/")

        if is_test_file(relative_path):
            test_files.append(path)

    references = {
        function_name: []
        for function_name in sorted(added_functions)
    }

    for test_file in test_files:
        try:
            source = test_file.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            continue

        for function_name in added_functions:
            if re.search(
                rf"\b{re.escape(function_name)}\s*\(",
                source,
            ):
                references[function_name].append(
                    str(
                        test_file.relative_to(repo)
                    ).replace("\\", "/")
                )

    functions = []

    for function_name in sorted(added_functions):
        matched_files = sorted(
            set(references[function_name])
        )

        functions.append(
            {
                "function": function_name,
                "referenced": bool(matched_files),
                "test_files": matched_files,
            }
        )

    return {
        "functions": functions,
        "referenced": any(
            item["referenced"]
            for item in functions
        ),
        "test_files": sorted(
            {
                test_file
                for item in functions
                for test_file in item["test_files"]
            }
        ),
    }
