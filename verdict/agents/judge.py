"""Judge: independently weighs diff, normalized evidence, and review advice."""
from ..evidence import Evidence
from ..llm import LLMError, call_llm_json

VALID_VERDICTS = {"approve", "comment", "request_changes"}

JUDGE_PROMPT = """You are the Judge stage of a PR review agent. Independently decide the final verdict from the diff and structured evidence from trusted checks. Reviewer comments are advisory: verify that they are supported by the diff and evidence rather than relying on them alone.

Diff:
{diff}

Evidence:
{evidence}

Reviewer comments (advisory):
{comments}

Respond with ONLY a JSON object like:
{{"verdict": "approve", "justification": "..."}}
Valid verdicts are: approve, comment, request_changes.
"""


def decide_verdict(diff_text: str, evidence: list[Evidence], comments: list[dict]) -> dict:
    if not comments and not _supported_evidence(evidence):
        return {"verdict": "approve", "justification": "No issues found.", "source": "rule"}

    prompt = JUDGE_PROMPT.format(diff=diff_text[:4000], evidence=evidence, comments=comments)
    try:
        result = call_llm_json(prompt)
        verdict = result.get("verdict", "comment")
        return {
            "verdict": verdict if verdict in VALID_VERDICTS else "comment",
            "justification": result.get("justification", ""),
            "source": "llm",
        }
    except LLMError as error:
        has_blocking_comment = any(
            isinstance(comment, dict) and comment.get("severity") == "blocking" for comment in comments
        )
        has_serious_evidence = any(
            isinstance(item, dict)
            and item.get("kind") == "security"
            and item.get("severity") in ("high", "medium")
            for item in evidence
        )
        return {
            "verdict": "request_changes" if has_blocking_comment or has_serious_evidence else "comment",
            "justification": (
                "Fallback rule: blocking severity present."
                if has_blocking_comment or has_serious_evidence
                else "Fallback rule: only minor comments or evidence."
            ),
            "source": "fallback",
            "error": str(error),
        }


def _supported_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Ignore malformed Evidence when deciding whether review input exists."""
    return [
        item
        for item in evidence
        if isinstance(item, dict)
        and isinstance(item.get("kind"), str)
        and isinstance(item.get("message"), str)
    ]
