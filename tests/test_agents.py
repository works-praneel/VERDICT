"""Tests for each agent's deterministic fallback path — these run without
Ollama so they work in any environment. The LLM path is exercised manually
once a local model is available (see README)."""
from verdict.agents import judge, planner, reviewer, scanner
from verdict.llm import LLMError


def test_scanner_fallback_skips_docs_only_change():
    result = scanner._fallback_rule(["README.md", "CHANGELOG.md"])
    assert result["tools"] == []


def test_scanner_fallback_runs_all_checks_on_source_change():
    result = scanner._fallback_rule(["app.py"])
    assert set(result["tools"]) == {"bandit", "ruff", "check_test_delta"}


def test_scanner_fallback_skips_test_delta_for_test_only_change():
    result = scanner._fallback_rule(["tests/test_app.py"])
    assert "check_test_delta" not in result["tools"]


def test_scanner_uses_fallback_for_malformed_llm_schema(monkeypatch):
    monkeypatch.setattr(
        scanner,
        "call_llm_json",
        lambda prompt: {"tools": "ruff", "reason": "malformed"},
    )

    result = scanner.decide_tools(["app.py"])

    assert result["source"] == "fallback"
    assert set(result["tools"]) == {"bandit", "ruff", "check_test_delta"}

def test_planner_selects_test_coverage_for_new_python_function(monkeypatch):
    captured = []

    monkeypatch.setattr(
        planner,
        "call_llm_json",
        lambda prompt: captured.append(prompt)
        or {
            "capabilities": [
                "lint_python",
                "check_new_python_test_coverage",
            ],
            "reason": "A new non-test Python function was added.",
        },
    )

    result = planner.plan(
        ["utils.py"],
        """
+def clamp(value, low, high):
+    return max(low, min(value, high))
""",
    )

    assert "check_new_python_test_coverage" in result["capabilities"]
    assert "utils.py" in captured[0]
    assert "check_new_python_test_coverage" in captured[0]

def test_reviewer_fallback_empty_when_no_findings():
    result = reviewer._fallback_comments([])
    assert result["comments"] == []


def test_reviewer_fallback_maps_high_severity_to_blocking():
    evidence = [{"kind": "security", "file": "app.py", "line": 1, "message": "eval used", "severity": "high"}]
    result = reviewer._fallback_comments(evidence)
    assert result["comments"][0]["severity"] == "blocking"


def test_reviewer_fallback_maps_low_severity_to_nitpick():
    evidence = [{"kind": "security", "file": "app.py", "line": 1, "message": "hardcoded password", "severity": "low"}]
    result = reviewer._fallback_comments(evidence)
    assert result["comments"][0]["severity"] == "nitpick"


def test_reviewer_fallback_maps_lint_and_test_coverage_evidence():
    result = reviewer._fallback_comments(
        [
            {"kind": "lint", "file": "app.py", "line": 2, "message": "unused import", "severity": "info"},
            {"kind": "test_coverage", "file": "", "line": None, "message": "missing test", "severity": "info"},
        ]
    )
    assert [comment["severity"] for comment in result["comments"]] == ["nitpick", "note"]
    assert result["comments"][1]["file"] == ""
    assert result["comments"][1]["line"] is None


def test_reviewer_accepts_normalized_evidence_in_llm_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(reviewer, "call_llm_json", lambda prompt: captured.append(prompt) or {"comments": []})

    result = reviewer.draft_comments("diff", [{"kind": "lint", "message": "unused import"}])

    assert result["comments"] == []
    assert "Evidence:" in captured[0]


def test_reviewer_falls_back_when_comments_field_is_missing(monkeypatch):
    monkeypatch.setattr(
        reviewer,
        "call_llm_json",
        lambda prompt: {"unexpected": []},
    )

    result = reviewer.draft_comments(
        "diff",
        [
            {
                "kind": "lint",
                "file": "app.py",
                "line": 1,
                "message": "unused import",
            }
        ],
    )

    assert result["source"] == "fallback"
    assert result["comments"][0]["comment"] == "unused import"


def test_reviewer_rejects_unlocated_comment_without_unlocated_evidence():
    comments = [
        {
            "severity": "note",
            "file": "",
            "line": None,
            "comment": "Unsupported claim",
        }
    ]
    evidence = [
        {
            "kind": "lint",
            "file": "app.py",
            "line": 1,
            "message": "unused import",
        }
    ]

    result = reviewer._validate_comments(comments, evidence)

    assert result == reviewer._fallback_comments(evidence)["comments"]


def test_judge_approves_with_no_comments():
    result = judge.decide_verdict("diff", [], [])
    assert result["verdict"] == "approve"


def test_judge_fallback_blocks_on_blocking_comment(monkeypatch):
    monkeypatch.setattr(judge, "call_llm_json", lambda prompt: (_ for _ in ()).throw(LLMError("offline")))
    comments = [{"severity": "blocking", "comment": "hardcoded secret"}]
    result = judge.decide_verdict("diff", [], comments)
    assert result["verdict"] == "request_changes"


def test_judge_fallback_comments_on_nitpick_only(monkeypatch):
    monkeypatch.setattr(judge, "call_llm_json", lambda prompt: (_ for _ in ()).throw(LLMError("offline")))
    comments = [{"severity": "nitpick", "comment": "unused import"}]
    result = judge.decide_verdict("diff", [], comments)
    assert result["verdict"] == "comment"


def test_judge_accepts_evidence_and_includes_all_inputs_in_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(
        judge,
        "call_llm_json",
        lambda prompt: captured.append(prompt) or {"verdict": "comment", "justification": "checked"},
    )

    result = judge.decide_verdict(
        "+changed line",
        [{"kind": "lint", "message": "unused import", "severity": "info"}],
        [{"severity": "nitpick", "comment": "advisory"}],
    )

    assert result["verdict"] == "comment"
    assert "+changed line" in captured[0]
    assert "Evidence:" in captured[0]
    assert "Reviewer comments (advisory):" in captured[0]


def test_judge_fallback_uses_serious_evidence_without_reviewer_comments(monkeypatch):
    monkeypatch.setattr(judge, "call_llm_json", lambda prompt: (_ for _ in ()).throw(LLMError("offline")))

    result = judge.decide_verdict(
        "diff",
        [{"kind": "security", "message": "secret", "severity": "high"}],
        [],
    )

    assert result["verdict"] == "request_changes"


def test_judge_ignores_malformed_evidence_without_crashing():
    result = judge.decide_verdict("diff", [{"kind": object()}, "invalid"], [])
    assert result["verdict"] == "approve"


def test_judge_handles_unsupported_evidence_without_crashing(monkeypatch):
    monkeypatch.setattr(judge, "call_llm_json", lambda prompt: (_ for _ in ()).throw(LLMError("offline")))

    result = judge.decide_verdict("diff", [{"kind": "future", "message": "unknown", "severity": "info"}], [])

    assert result["verdict"] == "comment"


def test_judge_falls_back_for_malformed_verdict_type(monkeypatch):
    monkeypatch.setattr(
        judge,
        "call_llm_json",
        lambda prompt: {
            "verdict": ["request_changes"],
            "justification": "malformed",
        },
    )

    result = judge.decide_verdict(
        "diff",
        [{"kind": "security", "message": "secret", "severity": "high"}],
        [],
    )

    assert result["verdict"] == "request_changes"
    assert result["source"] == "fallback"
    assert "invalid verdict" in result["error"]


def test_judge_falls_back_when_justification_is_malformed(monkeypatch):
    monkeypatch.setattr(
        judge,
        "call_llm_json",
        lambda prompt: {"verdict": "approve", "justification": None},
    )

    result = judge.decide_verdict(
        "diff",
        [],
        [{"severity": "blocking", "comment": "issue"}],
    )

    assert result["verdict"] == "request_changes"
    assert result["source"] == "fallback"
