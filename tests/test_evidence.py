"""Focused tests for Phase 2's normalized evidence adapters."""
import json

from verdict.evidence import (
    ALLOWED_SEVERITIES,
    bandit_findings_to_evidence,
    coverage_delta_to_evidence,
    ruff_findings_to_evidence,
)


def test_bandit_finding_normalizes_to_json_serializable_evidence():
    result = bandit_findings_to_evidence(
        [{"file": "app.py", "line": 7, "issue": "Hardcoded password", "severity": "HIGH"}]
    )

    assert result == [
        {
            "capability": "detect_python_security",
            "tool": "bandit",
            "kind": "security",
            "file": "app.py",
            "line": 7,
            "message": "Hardcoded password",
            "severity": "high",
            "rule_id": None,
            "details": {"source_severity": "HIGH"},
        }
    ]
    assert result[0]["severity"] in ALLOWED_SEVERITIES
    json.dumps(result)


def test_ruff_finding_normalizes_to_evidence():
    result = ruff_findings_to_evidence(
        [{"file": "app.py", "line": 3, "issue": "Unused import", "code": "F401"}]
    )

    assert result == [
        {
            "capability": "lint_python",
            "tool": "ruff",
            "kind": "lint",
            "file": "app.py",
            "line": 3,
            "message": "Unused import",
            "severity": "info",
            "rule_id": "F401",
            "details": {},
        }
    ]


def test_test_delta_missing_coverage_normalizes_to_evidence():
    result = coverage_delta_to_evidence(
        {
            "new_functions": ["clamp"],
            "new_test_functions": [],
            "test_files_touched": [],
            "missing_coverage": True,
        }
    )

    assert result == [
        {
            "capability": "check_new_python_test_coverage",
            "tool": "check_test_delta",
            "kind": "test_coverage",
            "file": "",
            "line": None,
            "message": "New function(s) ['clamp'] have no matching tests.",
            "severity": "info",
            "rule_id": "missing_test_coverage",
            "details": {
                "new_functions": ["clamp"],
                "new_test_functions": [],
                "test_files_touched": [],
            },
        }
    ]


def test_clean_results_produce_no_evidence():
    assert bandit_findings_to_evidence([]) == []
    assert ruff_findings_to_evidence([]) == []
    assert coverage_delta_to_evidence(
        {
            "new_functions": [],
            "new_test_functions": ["test_add"],
            "test_files_touched": ["tests/test_app.py"],
            "missing_coverage": False,
        }
    ) == []


def test_malformed_results_produce_no_evidence():
    assert bandit_findings_to_evidence(
        [{}, "not a finding", {"file": "app.py", "issue": "bad", "severity": object()}]
    ) == []
    assert ruff_findings_to_evidence({"file": "app.py"}) == []
    assert coverage_delta_to_evidence({"missing_coverage": True, "new_functions": "clamp"}) == []
    assert coverage_delta_to_evidence(
        {
            "missing_coverage": True,
            "new_functions": ["clamp"],
            "new_test_functions": object(),
            "test_files_touched": [],
        }
    ) == []
