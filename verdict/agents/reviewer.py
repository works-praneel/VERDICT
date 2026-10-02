"""Reviewer: drafts comments from the diff plus normalized evidence."""

from ..evidence import Evidence
from ..llm import LLMError, call_llm_json


REVIEWER_PROMPT = """
You are the Reviewer stage of a PR review agent.

You are given:
1. A pull-request diff.
2. Structured Evidence produced by trusted deterministic tools.

Draft review comments only for issues genuinely supported by the diff
or Evidence.

Evidence is authoritative.

Do NOT invent:
- issues
- file names
- line numbers
- rule IDs
- severity
- test coverage facts
- security facts
- any other technical facts

LOCATION GROUNDING:

- Evidence locations are authoritative.
- If Evidence provides a file, use exactly that file.
- If Evidence provides a line number, use exactly that line number.
- Never estimate or infer a line number.
- Never substitute a nearby line.
- Never derive a line number from the surrounding diff.
- If Evidence provides file="", preserve file="".
- If Evidence provides line=null, preserve line=null.
- Do not copy a file name or line number from the JSON example below.
- Do not create a location merely because the issue appears related to a
  particular line in the diff.

For every review comment:

- "severity" must be exactly one of:
  "blocking", "nitpick", "note".

- "file" must be:
  1. an exact file path explicitly provided by Evidence, or
  2. an exact file path explicitly present in the relevant diff.

- "line" must be:
  1. an exact integer explicitly provided by Evidence, or
  2. an exact integer explicitly supported by the relevant diff.

- If Evidence provides file="" or line=null, preserve those values.

- Never guess or estimate a missing location.

Evidence kinds may include:

- "security"
- "lint"
- "test_coverage"
- "missing_python_test_reference"
- "docker_base_image_pinning"
- "container"

For "missing_python_test_reference":
- The evidence establishes that an existing test search found no reference
  to the newly added function.
- Do not invent a source file or line for the missing reference.
- Use file="" and line=null unless the Evidence explicitly provides a
  trustworthy location.

For "test_coverage":
- Do not invent a source location for the missing test.
- Use file="" and line=null when those values are absent from Evidence.

For Docker/container findings:
- Use the exact Dockerfile path and line from Evidence when available.
- Do not replace an Evidence line with another line from the diff.

If the Evidence contains no supported issue, return:

{{"comments": []}}

Respond with ONLY a JSON object.

The required structure is:

{{
  "comments": [
    {{
      "severity": "blocking",
      "file": "app.py",
      "line": 15,
      "comment": "..."
    }}
  ]
}}

If a finding has no supported file or line, use:

{{
  "comments": [
    {{
      "severity": "note",
      "file": "",
      "line": null,
      "comment": "..."
    }}
  ]
}}

Do not include additional JSON fields.

Diff:
{diff}

Evidence:
{evidence}
"""


def draft_comments(
    diff_text: str,
    evidence: list[Evidence],
) -> dict:
    """Draft review comments from trusted Evidence.

    The LLM is responsible for explaining the findings, but deterministic
    Evidence remains authoritative for technical facts and locations.
    """

    prompt = REVIEWER_PROMPT.format(
        diff=diff_text[:4000],
        evidence=evidence,
    )

    try:
        result = call_llm_json(prompt)

        if not isinstance(result, dict) or "comments" not in result:
            raise ValueError(
                "Reviewer response must include a 'comments' list."
            )

        comments = result["comments"]

        if not isinstance(comments, list):
            raise ValueError(
                "Reviewer response contains a non-list 'comments' field."
            )

        validated_comments = _validate_comments(
            comments,
            evidence,
        )

        return {
            "comments": validated_comments,
            "source": "llm",
        }

    except (LLMError, ValueError, TypeError) as error:
        result = _fallback_comments(evidence)
        result["error"] = str(error)
        return result


def _validate_comments(
    comments: list,
    evidence: list[Evidence],
) -> list[dict]:
    """Validate LLM comments against trusted Evidence.

    The Reviewer may explain an established finding, but it must not
    fabricate a location. If a comment cannot be grounded safely, it is
    discarded and the deterministic fallback can be used by the caller.
    """

    validated = []

    supported_locations = {
        (
            item.get("file", ""),
            item.get("line"),
        )
        for item in evidence
        if isinstance(item, dict)
    }

    supported_files = {
        item.get("file")
        for item in evidence
        if isinstance(item, dict)
        and isinstance(item.get("file"), str)
        and item.get("file")
    }

    evidence_messages = [
        item.get("message", "")
        for item in evidence
        if isinstance(item, dict)
        and isinstance(item.get("message"), str)
    ]

    for comment in comments:
        if not isinstance(comment, dict):
            continue

        severity = comment.get("severity")
        file = comment.get("file")
        line = comment.get("line")
        message = comment.get("comment")

        if severity not in {
            "blocking",
            "nitpick",
            "note",
        }:
            continue

        if not isinstance(file, str):
            continue

        if line is not None and not isinstance(line, int):
            continue

        if not isinstance(message, str) or not message.strip():
            continue

        # A blank location is explicitly valid when Evidence has no
        # trustworthy location. It must remain blank/null.
        if file == "":
            has_unlocated_evidence = any(
                isinstance(item, dict)
                and item.get("file") == ""
                and item.get("line") is None
                and isinstance(item.get("message"), str)
                for item in evidence
            )
            if line is not None or not has_unlocated_evidence:
                continue

            validated.append(
                {
                    "severity": severity,
                    "file": "",
                    "line": None,
                    "comment": message,
                }
            )
            continue

        # A non-empty file must be supported by Evidence.
        if file not in supported_files:
            continue

        # If the comment provides a line, require the exact Evidence
        # location. This prevents the LLM from moving a finding to a nearby
        # line.
        if line is not None:
            if (file, line) not in supported_locations:
                continue

        # If the Evidence for this file has no line, the LLM must not
        # manufacture one.
        file_locations = {
            evidence_line
            for evidence_file, evidence_line in supported_locations
            if evidence_file == file
        }

        if file_locations == {None}:
            if line is not None:
                continue

        validated.append(
            {
                "severity": severity,
                "file": file,
                "line": line,
                "comment": message,
            }
        )

    # If the LLM returned comments but none survived grounding, use the
    # deterministic evidence fallback rather than silently losing findings.
    if comments and not validated and evidence_messages:
        return _fallback_comments(evidence)["comments"]

    return validated


def _fallback_comments(
    evidence: list[Evidence],
) -> dict:
    """Map established Evidence kinds to deterministic comment severities."""

    comments = []

    for item in evidence:
        if not isinstance(item, dict):
            continue

        kind = item.get("kind")
        message = item.get("message")
        file = item.get("file")
        line = item.get("line")

        if not isinstance(message, str):
            continue

        if not isinstance(file, str):
            continue

        if kind == "security":
            severity = (
                "blocking"
                if item.get("severity") in ("high", "medium")
                else "nitpick"
            )

        elif kind == "lint":
            severity = "nitpick"

        elif kind in {
            "test_coverage",
            "missing_python_test_reference",
        }:
            severity = "note"

        elif kind in {
            "docker_base_image_pinning",
            "container",
        }:
            severity = "blocking"

        else:
            continue

        comments.append(
            {
                "severity": severity,
                "file": file,
                "line": (
                    line
                    if isinstance(line, int)
                    else None
                ),
                "comment": message,
            }
        )

    return {
        "comments": comments,
        "source": "fallback",
    }
