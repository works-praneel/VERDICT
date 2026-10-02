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

_BANDIT_SEVERITIES = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
}


def _normalized_line(value: object) -> int | None:
    """Return a trustworthy integer line number or None."""
    if isinstance(value, bool):
        return None

    return value if isinstance(value, int) else None


def _normalized_severity(
    value: object,
    default: str = "info",
) -> str:
    """Return a severity from the supported Evidence vocabulary."""
    if isinstance(value, str) and value in ALLOWED_SEVERITIES:
        return value

    return default


def bandit_to_evidence(
    findings: object,
) -> list[Evidence]:
    """Normalize Bandit findings without changing the raw tool result."""
    if not isinstance(findings, list):
        return []

    evidence: list[Evidence] = []

    for finding in findings:
        if not isinstance(finding, dict):
            continue

        file = finding.get("file")
        message = finding.get("issue")
        source_severity = finding.get("severity")

        if not isinstance(file, str):
            continue

        if not isinstance(message, str):
            continue

        if not isinstance(source_severity, str):
            continue

        evidence.append(
            {
                "capability": "detect_python_security",
                "tool": "bandit",
                "kind": "security",
                "file": file,
                "line": _normalized_line(
                    finding.get("line")
                ),
                "message": message,
                "severity": _BANDIT_SEVERITIES.get(
                    source_severity,
                    "info",
                ),
                "rule_id": (
                    finding.get("test_id")
                    if isinstance(finding.get("test_id"), str)
                    else None
                ),
                "details": {
                    "source_severity": source_severity,
                },
            }
        )

    return evidence


def ruff_to_evidence(
    findings: object,
) -> list[Evidence]:
    """Normalize Ruff findings without changing the raw tool result."""
    if not isinstance(findings, list):
        return []

    evidence: list[Evidence] = []

    for finding in findings:
        if not isinstance(finding, dict):
            continue

        file = finding.get("file")
        message = finding.get("issue")
        code = finding.get("code")

        if not isinstance(file, str):
            continue

        if not isinstance(message, str):
            continue

        evidence.append(
            {
                "capability": "lint_python",
                "tool": "ruff",
                "kind": "lint",
                "file": file,
                "line": _normalized_line(
                    finding.get("line")
                ),
                "message": message,
                "severity": "info",
                "rule_id": (
                    code
                    if isinstance(code, str)
                    else None
                ),
                "details": {},
            }
        )

    return evidence


def test_delta_to_evidence(
    result: object,
) -> list[Evidence]:
    """Normalize the existing test-delta summary when coverage is missing."""
    if (
        not isinstance(result, dict)
        or result.get("missing_coverage") is not True
    ):
        return []

    new_functions = result.get("new_functions")
    new_test_functions = result.get("new_test_functions")
    test_files_touched = result.get("test_files_touched")

    if (
        not isinstance(new_functions, list)
        or not all(
            isinstance(name, str)
            for name in new_functions
        )
    ):
        return []

    if (
        not isinstance(new_test_functions, list)
        or not all(
            isinstance(name, str)
            for name in new_test_functions
        )
    ):
        return []

    if (
        not isinstance(test_files_touched, list)
        or not all(
            isinstance(path, str)
            for path in test_files_touched
        )
    ):
        return []

    return [
        {
            "capability": "check_new_python_test_coverage",
            "tool": "check_test_delta",
            "kind": "test_coverage",
            "file": "",
            "line": None,
            "message": (
                f"New function(s) {new_functions} "
                "have no matching tests."
            ),
            "severity": "info",
            "rule_id": "missing_test_coverage",
            "details": {
                "new_functions": new_functions,
                "new_test_functions": new_test_functions,
                "test_files_touched": test_files_touched,
            },
        }
    ]


def docker_base_image_to_evidence(
    findings: object,
) -> list[Evidence]:
    """Normalize deterministic Dockerfile base-image findings."""
    if not isinstance(findings, list):
        return []

    evidence: list[Evidence] = []

    for finding in findings:
        if not isinstance(finding, dict):
            continue

        file = finding.get("file")
        image = finding.get("image")
        reason = finding.get("reason")

        if not isinstance(file, str):
            continue

        if not isinstance(image, str):
            continue

        if reason not in {"untagged", "latest"}:
            continue

        if reason == "latest":
            message = (
                f"Base image '{image}' uses "
                "the mutable :latest tag."
            )
        else:
            message = (
                f"Base image '{image}' is untagged."
            )

        evidence.append(
            {
                "capability": (
                    "check_container_base_image_pinning"
                ),
                "tool": (
                    "check_container_base_image_pinning"
                ),
                "kind": "container",
                "file": file,
                "line": _normalized_line(
                    finding.get("line")
                ),
                "message": message,
                "severity": "info",
                "rule_id": (
                    "docker_base_image_not_pinned"
                ),
                "details": {
                    "image": image,
                    "reason": reason,
                },
            }
        )

    return evidence


def python_test_references_to_evidence(
    result: object,
) -> list[Evidence]:
    """Normalize Python test-reference investigation results.

    This evidence is produced by the bounded investigation capability
    ``inspect_python_test_references``.

    A reference finding may identify an existing test file, but it does not
    establish a trustworthy source line. Therefore line is always None.
    """

    if not isinstance(result, dict):
        return []

    functions = result.get("functions")

    if not isinstance(functions, list):
        return []

    evidence: list[Evidence] = []

    for item in functions:
        if not isinstance(item, dict):
            continue

        function_name = item.get("function")
        referenced = item.get("referenced")
        test_files = item.get("test_files")

        if not isinstance(function_name, str):
            continue

        if not isinstance(referenced, bool):
            continue

        if not isinstance(test_files, list):
            continue

        if not all(
            isinstance(path, str)
            for path in test_files
        ):
            continue

        if referenced:
            evidence.append(
                {
                    "capability": (
                        "inspect_python_test_references"
                    ),
                    "tool": (
                        "inspect_python_test_references"
                    ),
                    "kind": "python_test_reference",
                    "file": (
                        test_files[0]
                        if test_files
                        else ""
                    ),
                    "line": None,
                    "message": (
                        "Existing tests reference newly "
                        f"added function {function_name}."
                    ),
                    "severity": "info",
                    "rule_id": None,
                    "details": {
                        "function": function_name,
                        "referenced": True,
                        "test_files": test_files,
                    },
                }
            )

        else:
            evidence.append(
                {
                    "capability": (
                        "inspect_python_test_references"
                    ),
                    "tool": (
                        "inspect_python_test_references"
                    ),
                    "kind": (
                        "missing_python_test_reference"
                    ),
                    "file": "",
                    "line": None,
                    "message": (
                        "No existing test reference found "
                        f"for newly added function {function_name}."
                    ),
                    "severity": "medium",
                    "rule_id": None,
                    "details": {
                        "function": function_name,
                        "referenced": False,
                        "test_files": test_files,
                    },
                }
            )

    return evidence


# ---------------------------------------------------------------------------
# Backward-compatible aliases
# ---------------------------------------------------------------------------
#
# These aliases prevent older tests or modules from breaking while the
# registry uses the cleaner names above.

bandit_findings_to_evidence = bandit_to_evidence
ruff_findings_to_evidence = ruff_to_evidence
coverage_delta_to_evidence = test_delta_to_evidence
docker_base_image_pinning_to_evidence = docker_base_image_to_evidence

def normalize_evidence(
    capability: str,
    raw_result: object,
) -> list[Evidence]:
    """Normalize a trusted tool result by semantic capability.

    This compatibility dispatcher preserves the public normalization API
    used by the existing orchestration and Phase 1/2 tests.

    ToolRegistry normally uses the adapter attached to each
    ToolRegistration,
    but callers that normalize by capability can continue using this
    function.
    """

    if capability == "detect_python_security":
        return bandit_to_evidence(raw_result)

    if capability == "lint_python":
        return ruff_to_evidence(raw_result)

    if capability == "check_new_python_test_coverage":
        return test_delta_to_evidence(raw_result)

    if capability == "check_container_base_image_pinning":
        return docker_base_image_to_evidence(raw_result)

    if capability == "inspect_python_test_references":
        return python_test_references_to_evidence(raw_result)

    return []
