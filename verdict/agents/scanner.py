"""Scanner: decides which checks apply to a given diff.

This is the first real decision in the pipeline — a docs-only PR should
run nothing, a source-code PR should run the relevant checks. The LLM
makes this call; a clearly-labeled deterministic rule is the fallback if
Ollama isn't reachable, so the pipeline stays demoable end to end offline.
"""
from pathlib import Path

from ..llm import LLMError, call_llm_json

AVAILABLE_TOOLS = ["bandit", "ruff", "check_test_delta"]

SCANNER_PROMPT = """You are the Scanner stage of a PR review agent. Given the \
list of changed files in a pull request, decide which of the available \
checks should run.

Available checks:
- bandit: security scan for Python (.py) files
- ruff: style/lint scan for Python (.py) files
- check_test_delta: checks whether new functions added to non-test Python \
files have matching new test functions

Changed files:
{files}

Apply ALL of these rules that match, they are not mutually exclusive:
1. If ANY changed file ends in .py, include both "bandit" and "ruff".
2. If ANY changed file ends in .py AND does not have "test" in its filename, \
you MUST also include "check_test_delta" — this rule applies even if that \
same file is the only changed file.
3. If NO changed file ends in .py (only docs/config), tools must be [].

Worked example — changed files: ["utils.py"]
utils.py is a non-test .py file, so rules 1 and 2 both apply.
Correct output: {{"tools": ["bandit", "ruff", "check_test_delta"], "reason": "utils.py is a non-test python source file"}}

Respond with ONLY a JSON object like:
{{"tools": ["bandit", "ruff", "check_test_delta"], "reason": "..."}}
"""


def decide_tools(changed_files: list) -> dict:
    """Ask the LLM which tools should run for this diff."""
    prompt = SCANNER_PROMPT.format(files="\n".join(changed_files))
    try:
        decision = call_llm_json(prompt)
        tools = [t for t in decision.get("tools", []) if t in AVAILABLE_TOOLS]
        return {"tools": tools, "reason": decision.get("reason", ""), "source": "llm"}
    except LLMError as e:
        result = _fallback_rule(changed_files)
        result["error"] = str(e)
        return result


def _fallback_rule(changed_files: list) -> dict:
    py_files = [f for f in changed_files if f.endswith(".py")]
    if not py_files:
        return {"tools": [], "reason": "no python files changed", "source": "fallback"}

    non_test_py = [f for f in py_files if "test" not in Path(f).name.lower()]
    tools = ["bandit", "ruff"]
    if non_test_py:
        tools.append("check_test_delta")
    return {"tools": tools, "reason": "python files changed", "source": "fallback"}
