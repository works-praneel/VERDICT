"""Plan bounded investigation intent without executing any capability."""
from ..context import InvestigationGoal, InvestigationState
from ..evidence import Evidence
from ..llm import LLMError, call_llm_json


INVESTIGATION_PROMPT = """You are the Investigation Planner for a PR review.
Decide whether the supplied diff, normalized evidence, Reviewer comments, and
current investigation state require additional trusted evidence. You do not
execute investigations.

Return only JSON in this shape:
{{"investigate": true, "goals": [{{"question": "...", "required_capability": "semantic_capability_id", "reason": "..."}}]}}

`required_capability` must be a semantic capability ID only. Never return a
concrete tool name, command, shell expression, executable code, or an
arbitrary command. If no additional evidence is needed, return exactly
{{"investigate": false, "goals": []}}.

Diff:
{diff}

Evidence:
{evidence}

Reviewer comments:
{comments}

Investigation state:
{state}
"""


class InvestigationPlannerError(Exception):
    """Raised internally for invalid investigation-planning output."""


def plan_investigation(
    diff_text: str,
    evidence: list[Evidence],
    reviewer_comments: list[dict],
    investigation_state: InvestigationState,
) -> dict:
    """Return validated investigation intent; never execute a capability."""
    prompt = INVESTIGATION_PROMPT.format(
        diff=diff_text[:4000],
        evidence=evidence,
        comments=reviewer_comments,
        state=investigation_state,
    )
    try:
        return _validate_intent(call_llm_json(prompt))
    except (LLMError, InvestigationPlannerError, TypeError, ValueError) as error:
        return {
            "investigate": False,
            "goals": [],
            "source": "fallback",
            "error": str(error),
        }


def _validate_intent(result: object) -> dict:
    if not isinstance(result, dict):
        raise InvestigationPlannerError("Investigation response must be a JSON object.")

    investigate = result.get("investigate")
    goals_data = result.get("goals")
    if not isinstance(investigate, bool) or not isinstance(goals_data, list):
        raise InvestigationPlannerError("Investigation response requires boolean investigate and list goals.")
    if not investigate and goals_data:
        raise InvestigationPlannerError("Non-investigating responses must have no goals.")
    if investigate and not goals_data:
        raise InvestigationPlannerError("Investigating responses must include at least one goal.")

    goals = []
    for goal_data in goals_data:
        if not isinstance(goal_data, dict):
            raise InvestigationPlannerError("Each investigation goal must be an object.")
        try:
            goals.append(
                InvestigationGoal(
                    question=goal_data["question"],
                    required_capability=goal_data["required_capability"],
                    reason=goal_data["reason"],
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvestigationPlannerError(f"Invalid investigation goal: {error}") from error

    return {"investigate": investigate, "goals": goals, "source": "llm"}
