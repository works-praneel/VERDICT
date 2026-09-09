"""Normalized, JSON-serializable evidence from trusted tool results."""
from typing import TypedDict


class Evidence(TypedDict):
    capability: str
    tool: str
    kind: str
    file: str
    line: int | None
    message: str
    severity: str
    rule_id: str | None
    details: dict


ALLOWED_SEVERITIES = frozenset({"high", "medium", "low", "info"})
_BANDIT_SEVERITIES = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


def bandit_findings_to_evidence(findings: object) -> list[Evidence]:
    """Normalize the existing Bandit finding list without changing it."""
    if not isinstance(findings, list):
        return []

    evidence = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        file = finding.get("file")
        message = finding.get("issue")
        if not isinstance(file, str) or not isinstance(message, str):
            continue
        line = finding.get("line")
        source_severity = finding.get("severity")
        if not isinstance(source_severity, str):
            continue
        evidence.append(
            {
                "capability": "detect_python_security",
                "tool": "bandit",
                "kind": "security",
                "file": file,
                "line": line if isinstance(line, int) else None,
                "message": message,
                "severity": _BANDIT_SEVERITIES.get(source_severity, "info"),
                "rule_id": None,
                "details": {"source_severity": source_severity},
            }
        )
    return evidence


def ruff_findings_to_evidence(findings: object) -> list[Evidence]:
    """Normalize the existing Ruff finding list without changing it."""
    if not isinstance(findings, list):
        return []

    evidence = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        file = finding.get("file")
        message = finding.get("issue")
        if not isinstance(file, str) or not isinstance(message, str):
            continue
        line = finding.get("line")
        code = finding.get("code")
        evidence.append(
            {
                "capability": "lint_python",
                "tool": "ruff",
                "kind": "lint",
                "file": file,
                "line": line if isinstance(line, int) else None,
                "message": message,
                "severity": "info",
                "rule_id": code if isinstance(code, str) else None,
                "details": {},
            }
        )
    return evidence


def coverage_delta_to_evidence(result: object) -> list[Evidence]:
    """Normalize the existing test-delta summary when coverage is missing."""
    if not isinstance(result, dict) or result.get("missing_coverage") is not True:
        return []

    new_functions = result.get("new_functions")
    new_test_functions = result.get("new_test_functions")
    test_files_touched = result.get("test_files_touched")
    if not isinstance(new_functions, list) or not all(isinstance(name, str) for name in new_functions):
        return []
    if not isinstance(new_test_functions, list) or not all(
        isinstance(name, str) for name in new_test_functions
    ):
        return []
    if not isinstance(test_files_touched, list) or not all(isinstance(path, str) for path in test_files_touched):
        return []

    return [
        {
            "capability": "check_new_python_test_coverage",
            "tool": "check_test_delta",
            "kind": "test_coverage",
            "file": "",
            "line": None,
            "message": f"New function(s) {new_functions} have no matching tests.",
            "severity": "info",
            "rule_id": "missing_test_coverage",
            "details": {
                "new_functions": new_functions,
                "new_test_functions": new_test_functions,
                "test_files_touched": test_files_touched,
            },
        }
    ]


def docker_base_image_pinning_to_evidence(findings: object) -> list[Evidence]:
    """Normalize deterministic Dockerfile base-image pinning findings."""
    if not isinstance(findings, list):
        return []

    evidence = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        file = finding.get("file")
        image = finding.get("image")
        reason = finding.get("reason")
        if not isinstance(file, str) or not isinstance(image, str) or reason not in {"untagged", "latest"}:
            continue
        line = finding.get("line")
        message = (
            f"Base image '{image}' uses the mutable :latest tag."
            if reason == "latest"
            else f"Base image '{image}' is untagged."
        )
        evidence.append(
            {
                "capability": "check_container_base_image_pinning",
                "tool": "check_container_base_image_pinning",
                "kind": "container",
                "file": file,
                "line": line if isinstance(line, int) else None,
                "message": message,
                "severity": "info",
                "rule_id": "docker_base_image_not_pinned",
                "details": {"image": image, "reason": reason},
            }
        )
    return evidence
