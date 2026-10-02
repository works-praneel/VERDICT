"""Investigation Planner: decides whether to investigate further.

The Investigation Planner sits between the Reviewer and the Judge.
After the Reviewer drafts comments from the initial evidence, this
module asks the LLM whether additional investigation is warranted
and, if so, which semantic capabilities should be executed.

This is a function-based API; no class is introduced.
"""

from __future__ import annotations

import re

from ..context import InvestigationGoal, InvestigationState
from ..llm import LLMError, call_llm_json


_CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CONCRETE_TOOL_NAMES = frozenset({"bandit", "ruff", "check_test_delta"})
_NON_INVESTIGATION_CAPABILITIES = frozenset(
    {
        "detect_python_security",
        "lint_python",
        "check_new_python_test_coverage",
        "check_container_base_image_pinning",
    }
)


class InvestigationPlannerError(Exception):
    """Raised when investigation planning output violates its contract."""


INVESTIGATION_PROMPT = """\
You are the Investigation Planner stage of a PR review agent.

You are given:
1. A pull-request diff.
2. Structured Evidence already gathered by trusted deterministic tools.
3. Review comments drafted by the Reviewer.
4. The current investigation state (round number, completed capabilities,
   unresolved goals).

Decide whether additional investigation is needed. If it is, specify the
semantic capabilities that should be executed.

Available investigation capabilities are ONLY:

- inspect_python_test_references: check whether functions newly added by
  the PR are referenced by existing Python tests, including tests that
  were NOT modified by the PR.

You MUST choose `required_capability` from the available investigation
capabilities listed above.

Do NOT invent capability IDs.
Do NOT use placeholder values such as `semantic_capability_id`.
Do NOT request concrete tool names such as `bandit`, `ruff`, or
`check_test_delta`.

If none of the available investigation capabilities can answer the
unresolved question, return:
{{"investigate": false, "goals": []}}.

Rules:
- Only request a capability if the current evidence is genuinely
  insufficient.
- Never request a capability that has already been completed.
- Use semantic capability IDs only (e.g. inspect_python_test_references).
- Never use concrete tool names (bandit, ruff, check_test_delta).
- Never use shell commands or executable code.
- If no investigation is needed, set investigate to false with an empty
  goals list.
- If investigation IS needed, investigate must be true and goals must
  be non-empty.

Diff:
{diff}

Evidence:
{evidence}

Reviewer comments:
{comments}

Investigation state:
- Current round: {current_round}
- Completed capabilities: {completed_capabilities}
- Unresolved goals: {unresolved_goals}

Respond with ONLY a JSON object in this shape:

<VERDICT_JSON>
{{
  "investigate": true,
  "goals": [
    {{
      "question": "Is the newly added function referenced by an existing test?",
      "required_capability": "inspect_python_test_references",
      "reason": "Initial test-delta evidence does not inspect unchanged tests."
    }}
  ]
}}
</VERDICT_JSON>

Or, if no investigation is needed:

<VERDICT_JSON>
{{"investigate": false, "goals": []}}
</VERDICT_JSON>
"""


def _validate_intent(raw: dict) -> dict:
    """Validate an investigation intent from the LLM.

    Raises InvestigationPlannerError on contract violations.
    Returns a dict with ``investigate``, ``goals`` (list of
    InvestigationGoal), and ``source``.
    """
    if not isinstance(raw, dict):
        raise InvestigationPlannerError(
            "Investigation planner response must be a JSON object."
        )

    investigate = raw.get("investigate")
    goals_raw = raw.get("goals")

    if not isinstance(investigate, bool):
        raise InvestigationPlannerError(
            "Investigation planner 'investigate' must be a boolean."
        )

    if not isinstance(goals_raw, list):
        raise InvestigationPlannerError(
            "Investigation planner 'goals' must be a list."
        )

    if investigate and not goals_raw:
        raise InvestigationPlannerError(
            "Investigation planner set investigate=true but provided "
            "no goals."
        )

    if not investigate and goals_raw:
        raise InvestigationPlannerError(
            "Investigation planner set investigate=false but provided "
            "goals — this is contradictory."
        )

    if not investigate:
        return {
            "investigate": False,
            "goals": [],
            "source": "llm",
        }

    # Validate each goal and convert to InvestigationGoal.
    validated_goals: list[InvestigationGoal] = []

    for goal_raw in goals_raw:
        if not isinstance(goal_raw, dict):
            raise InvestigationPlannerError(
                "Each investigation goal must be a JSON object."
            )

        question = goal_raw.get("question")
        required_capability = goal_raw.get("required_capability")
        reason = goal_raw.get("reason")

        if not isinstance(question, str) or not question.strip():
            raise InvestigationPlannerError(
                "Investigation goal 'question' must be a non-empty string."
            )

        if not isinstance(reason, str) or not reason.strip():
            raise InvestigationPlannerError(
                "Investigation goal 'reason' must be a non-empty string."
            )

        if (
            not isinstance(required_capability, str)
            or not _CAPABILITY_ID_RE.fullmatch(required_capability)
        ):
            raise InvestigationPlannerError(
                f"Investigation goal 'required_capability' "
                f"({required_capability!r}) is not a valid "
                f"semantic capability ID."
            )

        if required_capability in _CONCRETE_TOOL_NAMES:
            raise InvestigationPlannerError(
                f"Investigation goal used concrete tool name "
                f"'{required_capability}' instead of a semantic "
                f"capability ID."
            )

        if required_capability in _NON_INVESTIGATION_CAPABILITIES:
            raise InvestigationPlannerError(
                f"Investigation goal requested capability "
                f"'{required_capability}', which is not available "
                "for investigation."
            )

        # InvestigationGoal.__post_init__ will also validate; let it
        # raise ValueError which we catch in plan_investigation.
        validated_goals.append(
            InvestigationGoal(
                question=question,
                required_capability=required_capability,
                reason=reason,
            )
        )

    return {
        "investigate": True,
        "goals": validated_goals,
        "source": "llm",
    }


def _fallback() -> dict:
    """Safe fallback: no investigation."""
    return {
        "investigate": False,
        "goals": [],
        "source": "fallback",
    }


def plan_investigation(
    diff_text: str,
    evidence: list[dict],
    reviewer_comments: list[dict],
    investigation_state: InvestigationState,
) -> dict:
    """Ask the LLM whether further investigation is needed.

    Returns a dict with:
    - ``investigate`` (bool)
    - ``goals`` (list of InvestigationGoal or empty list)
    - ``source`` ("llm" or "fallback")
    - ``error`` (str, only on fallback)
    """
    prompt = INVESTIGATION_PROMPT.format(
        diff=diff_text[:4000],
        evidence=evidence,
        comments=reviewer_comments,
        current_round=investigation_state.current_round,
        completed_capabilities=sorted(
            investigation_state.completed_capabilities
        ),
        unresolved_goals=[
            {
                "question": g.question,
                "required_capability": g.required_capability,
                "reason": g.reason,
            }
            for g in investigation_state.unresolved_goals
        ],
    )

    try:
        raw = call_llm_json(prompt)
        return _validate_intent(raw)

    except (
        LLMError,
        InvestigationPlannerError,
        ValueError,
        TypeError,
    ) as error:
        result = _fallback()
        result["error"] = str(error)
        return result
