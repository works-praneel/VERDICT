"""Focused Phase 1 tests for planning, trusted dispatch, and fallback behavior."""
import pytest

from verdict.agents import planner
from verdict.context import ReviewContext
from verdict.evidence import ruff_findings_to_evidence
from verdict import tools
from verdict.tool_registry import ToolRegistration, ToolRegistry, ToolResolution


def test_planner_returns_valid_semantic_capabilities(monkeypatch):
    monkeypatch.setattr(
        planner,
        "call_llm_json",
        lambda prompt: {"capabilities": ["detect_python_security", "lint_python"], "reason": "Python changed"},
    )
    result = planner.plan(["app.py"], "+def app(): pass")
    assert result["capabilities"] == ["detect_python_security", "lint_python"]
    assert result["source"] == "llm"


@pytest.mark.parametrize(
    ("changed_files", "diff_text", "capabilities"),
    [
        (["app.py"], "+def calculate(): pass", ["detect_python_security", "lint_python"]),
        (["web/app.ts"], "+export const app = 1", ["analyze_typescript_changes"]),
        (["Dockerfile"], "+FROM python:3.12", ["analyze_container_configuration"]),
        (["infra/main.tf"], "+resource \"aws_s3_bucket\" \"assets\" {}", ["analyze_infrastructure_as_code"]),
        (["README.md"], "+# Documentation", []),
        (["assets/model.custom"], "+format data", ["analyze_custom_format"]),
        (
            ["app.py", "web/app.ts"],
            "+def calculate(): pass\n+export const app = 1",
            ["lint_python", "analyze_typescript_changes"],
        ),
    ],
    ids=["python", "typescript", "dockerfile", "terraform", "docs", "unknown", "mixed"],
)
def test_planner_accepts_semantic_plans_for_change_categories(
    monkeypatch, changed_files, diff_text, capabilities
):
    monkeypatch.setattr(
        planner,
        "call_llm_json",
        lambda prompt: {"capabilities": capabilities, "reason": "mocked semantic plan"},
    )

    result = planner.plan(changed_files, diff_text)

    assert result["capabilities"] == capabilities
    assert result["source"] == "llm"


def test_planner_rejects_malformed_output(monkeypatch):
    monkeypatch.setattr(planner, "call_llm_json", lambda prompt: {"capabilities": "lint_python"})
    with pytest.raises(planner.PlannerError):
        planner.plan(["app.py"], "")


def test_planner_rejects_concrete_tool_output(monkeypatch):
    monkeypatch.setattr(planner, "call_llm_json", lambda prompt: {"capabilities": ["bandit"], "reason": "bad"})
    with pytest.raises(planner.PlannerError):
        planner.plan(["app.py"], "")


def test_planner_failure_uses_v0_scanner(monkeypatch):
    from verdict import cli

    monkeypatch.setattr(cli.planner, "plan", lambda *args: (_ for _ in ()).throw(planner.PlannerError("bad plan")))
    monkeypatch.setattr(cli.scanner, "decide_tools", lambda files: {"tools": ["ruff"], "source": "fallback"})
    route = cli._plan_or_fallback({"changed_files": ["app.py"], "diff_text": ""})
    assert route["path"] == "scanner_fallback"
    assert set(route["decision"]["tools"]) == {
        "bandit",
        "ruff",
        "check_test_delta",
    }


def test_planner_fallback_enforces_docker_base_image_check(monkeypatch):
    from verdict import cli

    monkeypatch.setattr(
        cli.planner,
        "plan",
        lambda *args: (_ for _ in ()).throw(
            cli.planner.PlannerError("malformed planner response")
        ),
    )
    monkeypatch.setattr(
        cli.scanner,
        "decide_tools",
        lambda files: {"tools": [], "source": "llm"},
    )

    route = cli._plan_or_fallback(
        {
            "changed_files": ["Dockerfile"],
            "diff_text": "+++ b/Dockerfile\n@@ -0,0 +1 @@\n+FROM python:latest\n",
        }
    )

    assert route["decision"]["tools"] == [
        "check_container_base_image_pinning",
    ]


def test_registry_resolves_capability_to_registered_tool():
    resolution = ToolRegistry().resolve(["detect_python_security"])
    assert [tool.tool_name for tool in resolution.supported] == ["bandit"]
    assert resolution.supported[0].function is tools.run_bandit


def test_unsupported_capability_does_not_discard_supported_capability():
    registry = ToolRegistry()
    calls = []
    registry._registrations["lint_python"] = ToolRegistration(
        "lint_python", "ruff", lambda repo_path, changed_files: calls.append((repo_path, changed_files)) or ["ran"], "repo_files", ruff_findings_to_evidence
    )
    resolution = registry.resolve(["lint_python", "some_future_capability"])
    assert [tool.tool_name for tool in resolution.supported] == ["ruff"]
    assert resolution.unsupported == ("some_future_capability",)
    execution = registry.execute(resolution, "repo", ["app.py"], "diff")
    assert execution.raw_results["ruff"] == ["ran"]
    assert calls == [("repo", ["app.py"])]


def test_planner_plan_with_future_capability_resolves_supported_and_unsupported(monkeypatch):
    monkeypatch.setattr(
        planner,
        "call_llm_json",
        lambda prompt: {
            "capabilities": ["lint_python", "analyze_future_runtime"],
            "reason": "Python and a future runtime change",
        },
    )

    plan = planner.plan(["app.py"], "+def app(): pass")
    resolution = ToolRegistry().resolve(plan["capabilities"])

    assert [tool.capability for tool in resolution.supported] == ["lint_python"]
    assert resolution.unsupported == ("analyze_future_runtime",)


def test_unknown_capability_cannot_execute():
    registry = ToolRegistry()
    resolution = registry.resolve(["not_registered"])
    assert resolution.supported == ()
    assert resolution.unsupported == ("not_registered",)
    assert registry.execute(resolution, "repo", ["app.py"], "diff").raw_results == {
        "bandit": [], "ruff": [], "test_delta": {}
    }


def test_registry_rejects_forged_registration_without_executing_callable():
    registry = ToolRegistry()
    calls = []
    forged_registration = ToolRegistration(
        "forged_capability",
        "ruff",
        lambda repo_path, changed_files: calls.append((repo_path, changed_files)),
        "repo_files",
        ruff_findings_to_evidence,
    )
    forged_resolution = ToolResolution((forged_registration,), ())

    with pytest.raises(RuntimeError, match="Untrusted tool registration"):
        registry.execute(forged_resolution, "repo", ["app.py"], "diff")

    assert calls == []


def test_review_context_carries_pipeline_state():
    context = ReviewContext(
        changed_files=["app.py"],
        diff="diff",
        capabilities=["lint_python"],
        selected_tools=["ruff"],
        unsupported_capabilities=["future"],
        tool_results={"ruff": []},
        evidence=[{"tool": "ruff"}],
        comments=[{"comment": "unused import"}],
        verdict={"verdict": "comment"},
    )
    assert context.selected_tools == ["ruff"]
    assert context.unsupported_capabilities == ["future"]
    assert context.evidence == [{"tool": "ruff"}]
    assert context.verdict["verdict"] == "comment"

def test_required_python_test_coverage_is_added_when_planner_omits_it():
    from verdict.cli import _enforce_required_capabilities

    decision = {
        "capabilities": ["lint_python"],
        "reason": "Python changed",
        "source": "llm",
    }

    result = _enforce_required_capabilities(
        decision,
        ["utils.py"],
        "diff --git a/utils.py b/utils.py\n"
        "--- a/utils.py\n"
        "+++ b/utils.py\n"
        "+def clamp(value, low, high):\n"
        "+    return max(low, min(value, high))\n",
    )

    assert result["capabilities"] == [
        "lint_python",
        "check_new_python_test_coverage",
    ]


def test_required_python_test_coverage_is_not_added_for_test_files():
    from verdict.cli import _enforce_required_capabilities

    decision = {
        "capabilities": ["lint_python"],
        "reason": "Python changed",
        "source": "llm",
    }

    result = _enforce_required_capabilities(
        decision,
        ["tests/test_utils.py"],
        "diff --git a/tests/test_utils.py b/tests/test_utils.py\n"
        "--- a/tests/test_utils.py\n"
        "+++ b/tests/test_utils.py\n"
        "+def test_clamp():\n"
        "+    assert clamp(5, 1, 10) == 5\n",
    )

    assert result["capabilities"] == ["lint_python"]


def test_required_python_test_coverage_is_not_duplicated():
    from verdict.cli import _enforce_required_capabilities

    decision = {
        "capabilities": [
            "lint_python",
            "check_new_python_test_coverage",
        ],
        "reason": "Python changed",
        "source": "llm",
    }

    result = _enforce_required_capabilities(
        decision,
        ["utils.py"],
        "diff --git a/utils.py b/utils.py\n"
        "--- a/utils.py\n"
        "+++ b/utils.py\n"
        "+def clamp(value, low, high):\n"
        "+    return value\n",
    )

    assert result["capabilities"] == [
        "lint_python",
        "check_new_python_test_coverage",
    ]


def test_required_lint_is_added_when_planner_omits_it():
    from verdict.cli import _enforce_required_capabilities

    result = _enforce_required_capabilities(
        {"capabilities": [], "reason": "Python changed"},
        ["app.py"],
        "+++ b/app.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n",
    )

    assert result["capabilities"] == [
        "lint_python",
        "check_new_python_test_coverage",
    ]


def test_required_docker_check_is_added_for_added_from_instruction():
    from verdict.cli import _enforce_required_capabilities

    result = _enforce_required_capabilities(
        {"capabilities": [], "reason": "Container base image changed"},
        ["Dockerfile"],
        "+++ b/Dockerfile\n@@ -0,0 +1 @@\n+FROM python:latest\n",
    )

    assert result["capabilities"] == [
        "check_container_base_image_pinning",
    ]


def test_required_docker_check_is_not_added_for_non_from_change():
    from verdict.cli import _enforce_required_capabilities

    result = _enforce_required_capabilities(
        {"capabilities": [], "reason": "Build command changed"},
        ["Dockerfile"],
        "+++ b/Dockerfile\n@@ -1 +1 @@\n-RUN echo old\n+RUN echo new\n",
    )

    assert result["capabilities"] == []
