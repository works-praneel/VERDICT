"""Judge: weighs the Reviewer's comments into a single verdict.

This is the decision to spend the most time on when demoing autonomy — it
has to reason about severity, not just count comments. One blocking
security issue should outweigh five nitpicks.
"""
from ..llm import LLMError, call_llm_json

JUDGE_PROMPT = """You are the Judge stage of a PR review agent. Given a list \
of review comments, decide the final verdict.

Comments:
{comments}

Guidance: a single "blocking" severity comment (e.g. a security issue) \
should result in request_changes. Only "nitpick" or "note" comments should \
result in comment, not request_changes. Weigh the comments, don't just \
count them.

Respond with ONLY a JSON object like:
{{"verdict": "approve", "justification": "..."}}
Valid verdicts are: approve, comment, request_changes.
"""


def decide_verdict(comments: list) -> dict:
    if not comments:
        return {"verdict": "approve", "justification": "No issues found.", "source": "rule"}

    prompt = JUDGE_PROMPT.format(comments=comments)
    try:
        result = call_llm_json(prompt)
        return {
            "verdict": result.get("verdict", "comment"),
            "justification": result.get("justification", ""),
            "source": "llm",
        }
    except LLMError as e:
        has_blocking = any(c.get("severity") == "blocking" for c in comments)
        return {
            "verdict": "request_changes" if has_blocking else "comment",
            "justification": (
                "Fallback rule: blocking severity present."
                if has_blocking
                else "Fallback rule: only minor comments."
            ),
            "source": "fallback",
            "error": str(e),
        }
