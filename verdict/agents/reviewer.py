"""Reviewer: drafts comments from the diff plus scan results.

The important behavior here is restraint — a clean diff should come back
with an empty comment list, not padded filler comments. Severity per
comment (blocking / nitpick / note) is what the Judge will weigh next.
"""
from ..llm import LLMError, call_llm_json

REVIEWER_PROMPT = """You are the Reviewer stage of a PR review agent. You are \
given a diff and the results of automated scans. Draft review comments only \
for things that genuinely matter — if the PR is clean, return an empty list. \
Never invent issues that aren't supported by the diff or scan results.

Diff:
{diff}

Bandit findings:
{bandit}

Ruff findings:
{ruff}

Test coverage check:
{test_delta}

Respond with ONLY a JSON object like:
{{"comments": [{{"severity": "blocking", "file": "app.py", "line": 12, "comment": "..."}}]}}
If there is nothing worth commenting on, respond with {{"comments": []}}.
Valid severities are: blocking, nitpick, note.
"""


def draft_comments(diff_text: str, bandit_findings: list, ruff_findings: list, test_delta: dict) -> dict:
    prompt = REVIEWER_PROMPT.format(
        diff=diff_text[:4000],  # keep the prompt bounded for local models
        bandit=bandit_findings,
        ruff=ruff_findings,
        test_delta=test_delta,
    )
    try:
        result = call_llm_json(prompt)
        return {"comments": result.get("comments", []), "source": "llm"}
    except LLMError as e:
        result = _fallback_comments(bandit_findings, ruff_findings, test_delta)
        result["error"] = str(e)
        return result


def _fallback_comments(bandit_findings: list, ruff_findings: list, test_delta: dict) -> dict:
    comments = []
    for f in bandit_findings:
        # respect bandit's own severity rather than treating every finding as blocking —
        # this is exactly the kind of naive thresholding the LLM-driven Judge is meant to
        # improve on (e.g. recognizing a hardcoded credential matters even at LOW severity)
        severity = "blocking" if f["severity"] in ("HIGH", "MEDIUM") else "nitpick"
        comments.append(
            {"severity": severity, "file": f["file"], "line": f["line"], "comment": f["issue"]}
        )
    for f in ruff_findings:
        comments.append(
            {"severity": "nitpick", "file": f["file"], "line": f["line"], "comment": f["issue"]}
        )
    if test_delta.get("missing_coverage"):
        comments.append(
            {
                "severity": "note",
                "file": "",
                "line": 0,
                "comment": f"New function(s) {test_delta['new_functions']} have no matching tests.",
            }
        )
    return {"comments": comments, "source": "fallback"}
