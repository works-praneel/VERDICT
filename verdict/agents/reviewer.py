"""Reviewer: drafts comments from the diff plus normalized evidence."""
from ..evidence import Evidence
from ..llm import LLMError, call_llm_json

REVIEWER_PROMPT = """You are the Reviewer stage of a PR review agent. You are given a diff and structured evidence from trusted automated checks. Draft review comments only for things that genuinely matter -- if the PR is clean, return an empty list. Never invent issues that are not supported by the diff or evidence.

Diff:
{diff}

Evidence:
{evidence}

Respond with ONLY a JSON object like:
{{"comments": [{{"severity": "blocking", "file": "app.py", "line": 12, "comment": "..."}}]}}
If there is nothing worth commenting on, respond with {{"comments": []}}.
Valid severities are: blocking, nitpick, note.
"""


def draft_comments(diff_text: str, evidence: list[Evidence]) -> dict:
    prompt = REVIEWER_PROMPT.format(diff=diff_text[:4000], evidence=evidence)
    try:
        result = call_llm_json(prompt)
        return {"comments": result.get("comments", []), "source": "llm"}
    except LLMError as error:
        result = _fallback_comments(evidence)
        result["error"] = str(error)
        return result


def _fallback_comments(evidence: list[Evidence]) -> dict:
    """Map established Evidence kinds to the existing comment severities."""
    comments = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        message = item.get("message")
        file = item.get("file")
        line = item.get("line")
        if not isinstance(message, str) or not isinstance(file, str):
            continue
        if kind == "security":
            severity = "blocking" if item.get("severity") in ("high", "medium") else "nitpick"
        elif kind == "lint":
            severity = "nitpick"
        elif kind == "test_coverage":
            severity = "note"
        else:
            continue
        comments.append(
            {
                "severity": severity,
                "file": file,
                "line": line if isinstance(line, int) else 0,
                "comment": message,
            }
        )
    return {"comments": comments, "source": "fallback"}
