"""Planner: selects semantic analysis capabilities for a PR diff."""
import re

from ..llm import LLMError, call_llm_json

KNOWN_CAPABILITIES = (
    "detect_python_security",
    "lint_python",
    "check_new_python_test_coverage",
)
CONCRETE_TOOL_NAMES = {"bandit", "ruff", "check_test_delta"}
CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

PLANNER_PROMPT = """You are the Planner stage of a PR review agent. Given a
pull-request diff and its changed files, choose the semantic analysis
capabilities that are relevant. You do not execute anything.

The initial available semantic capabilities are:
- detect_python_security: inspect changed Python source for security issues
- lint_python: inspect changed Python files for lint/style issues
- check_new_python_test_coverage: check new non-test Python functions for matching tests

Never return concrete tool names, commands, shell snippets, or executable code.
Do not use names such as bandit, ruff, or check_test_delta.

Changed files:
{files}

Diff:
{diff}

Respond with ONLY a JSON object in this shape:
{{"capabilities": ["detect_python_security"], "reason": "..."}}
"""


class PlannerError(Exception):
    """Raised when Planner output is unavailable or violates its contract."""


def plan(changed_files: list[str], diff_text: str) -> dict:
    """Use the LLM to choose semantic capability IDs for the supplied change."""
    prompt = PLANNER_PROMPT.format(files="\n".join(changed_files), diff=diff_text[:4000])
    try:
        result = call_llm_json(prompt)
    except LLMError as error:
        raise PlannerError(str(error)) from error
    return _validate_plan(result)


def _validate_plan(result: object) -> dict:
    """Validate structure and ensure the plan cannot contain concrete tools."""
    if not isinstance(result, dict):
        raise PlannerError("Planner response must be a JSON object.")

    capabilities = result.get("capabilities")
    reason = result.get("reason")
    if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
        raise PlannerError("Planner response field 'capabilities' must be a list of strings.")
    if not isinstance(reason, str):
        raise PlannerError("Planner response field 'reason' must be a string.")
    if any(not CAPABILITY_ID_RE.fullmatch(item) or item in CONCRETE_TOOL_NAMES for item in capabilities):
        raise PlannerError("Planner returned an invalid capability ID.")

    return {"capabilities": capabilities, "reason": reason, "source": "llm"}
