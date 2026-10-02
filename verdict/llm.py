"""Thin client for a local Ollama model, plus a JSON-forcing helper.

Local models don't have native function-calling like hosted APIs, so we
prompt for a JSON object and parse it out of the raw text response,
retrying if the model wraps it in prose or code fences.
"""

import json
import os
import re

import requests


OLLAMA_URL = "http://localhost:11434/api/generate"

# Override with:
#   set VERDICT_MODEL=qwen3:8b
# or:
#   $env:VERDICT_MODEL="qwen3:8b"
#
# Keep this aligned with setup.sh and the model used for the evaluation.
DEFAULT_MODEL = os.getenv(
    "VERDICT_MODEL",
    "qwen2.5-coder:14b",
)


# Qwen3 is a hybrid-reasoning model: unless told not to, it can prepend a
# <think>...</think> reasoning block before the actual answer. We ask it not
# to via the "think" request field (ignored harmlessly by models that don't
# support it) AND strip any <think> block defensively before JSON parsing,
# since relying on a single request flag to always suppress it is fragile.
THINK_TAG_RE = re.compile(
    r"<think>.*?</think>",
    re.DOTALL,
)


# Models sometimes add reasoning prose around the JSON answer, and that prose
# can itself contain braces (e.g. quoting a code snippet), which breaks a
# naive "first { to last }" scan. Asking for an explicit delimiter is far
# more robust than relying on brace matching alone.
JSON_MARKER_RE = re.compile(
    r"<VERDICT_JSON>(.*?)</VERDICT_JSON>",
    re.DOTALL,
)


class LLMError(Exception):
    """Raised when the local model can't be reached or won't return usable JSON."""


def call_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
) -> str:
    """Call the local Ollama model and return its raw text response."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "options": {
                    "temperature": temperature,
                },
            },
            timeout=180,
        )

        response.raise_for_status()

        payload = response.json()

        raw_response = payload.get("response")

        if not isinstance(raw_response, str):
            raise LLMError(
                "Ollama returned a response without a valid "
                "string 'response' field."
            )

        return raw_response

    except requests.exceptions.ConnectionError as error:
        raise LLMError(
            "Could not reach Ollama at "
            "http://localhost:11434 — is Ollama running, "
            f"and have you pulled the model with "
            f"`ollama pull {model}`?"
        ) from error

    except requests.exceptions.RequestException as error:
        raise LLMError(
            f"Ollama request failed: {error}"
        ) from error

    except ValueError as error:
        raise LLMError(
            f"Ollama returned invalid JSON: {error}"
        ) from error


def call_llm_json(
    prompt: str,
    model: str = DEFAULT_MODEL,
    retries: int = 2,
) -> dict:
    """Call the LLM and force-parse a JSON object from its response.

    Processing order:

    1. Call Ollama.
    2. Remove <think>...</think> blocks.
    3. Prefer explicit <VERDICT_JSON>...</VERDICT_JSON> markers.
    4. Fall back to brace-based JSON extraction.
    5. Parse the candidate as a JSON object.
    6. Retry malformed responses.
    7. Raise LLMError after all attempts fail.
    """

    last_error: Exception | None = None
    raw = ""

    for _ in range(retries + 1):
        raw = call_llm(
            prompt,
            model=model,
        )

        text = THINK_TAG_RE.sub(
            "",
            raw,
        ).strip()

        marker_match = JSON_MARKER_RE.search(text)

        if marker_match:
            candidate = marker_match.group(1).strip()
        else:
            candidate = None

        # Fallback for models that ignore the explicit JSON markers.
        if candidate is None:
            start = text.find("{")
            end = text.rfind("}")

            if start != -1 and end != -1 and start < end:
                candidate = text[start : end + 1]

        if candidate is not None:
            try:
                parsed = json.loads(candidate)

                if isinstance(parsed, dict):
                    return parsed

                last_error = ValueError(
                    "Model returned valid JSON, but it was not "
                    "a JSON object."
                )

            except json.JSONDecodeError as error:
                last_error = error

        else:
            last_error = ValueError(
                "No JSON object found in model output."
            )

    raise LLMError(
        "Model did not return valid JSON after "
        f"{retries + 1} attempts: {last_error}. "
        f"Raw output (truncated): {raw[:300]!r}"
    )
