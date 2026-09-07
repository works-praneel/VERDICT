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
# Override with: set VERDICT_MODEL=qwen3:8b  (cmd)  or  $env:VERDICT_MODEL="qwen3:8b"  (PowerShell)
DEFAULT_MODEL = os.environ.get("VERDICT_MODEL", "qwen3:8b")

# Qwen3 is a hybrid-reasoning model: unless told not to, it can prepend a
# <think>...</think> reasoning block before the actual answer. We ask it not
# to via the "think" request field (ignored harmlessly by models that don't
# support it) AND strip any <think> block defensively before JSON parsing,
# since relying on a single request flag to always suppress it is fragile.
THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Models sometimes add reasoning prose around the JSON answer, and that prose
# can itself contain braces (e.g. quoting a code snippet), which breaks a
# naive "first { to last }" scan. Asking for an explicit delimiter is far
# more robust than relying on brace matching alone.
JSON_MARKER_RE = re.compile(r"<VERDICT_JSON>(.*?)</VERDICT_JSON>", re.DOTALL)


class LLMError(Exception):
    """Raised when the local model can't be reached or won't return usable JSON."""


def call_llm(prompt: str, model: str = DEFAULT_MODEL, temperature: float = 0.1) -> str:
    """Call the local Ollama model and return its raw text response."""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "options": {"temperature": temperature},
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["response"]
    except requests.exceptions.ConnectionError as e:
        raise LLMError(
            "Could not reach Ollama at http://localhost:11434 — is Ollama "
            f"running, and have you pulled the model with `ollama pull {model}`?"
        ) from e
    except requests.exceptions.RequestException as e:
        raise LLMError(f"Ollama request failed: {e}") from e


def call_llm_json(prompt: str, model: str = DEFAULT_MODEL, retries: int = 2) -> dict:
    """Call the LLM and force-parse a JSON object out of its response.

    Strips any <think>...</think> reasoning block first (Qwen3 and similar
    hybrid-reasoning models), then looks for the answer wrapped in
    <VERDICT_JSON> markers (robust to stray braces in surrounding prose),
    falling back to plain brace-scanning if the model didn't use the markers.
    Retries a couple of times since local models occasionally produce
    malformed output.
    """
    last_error = None
    raw = ""
    for _ in range(retries + 1):
        raw = call_llm(prompt, model=model)
        text = THINK_TAG_RE.sub("", raw).strip()

        marker_match = JSON_MARKER_RE.search(text)
        candidate = marker_match.group(1).strip() if marker_match else None

        if candidate is None:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                candidate = text[start : end + 1]

        if candidate is not None:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                last_error = e
                continue
        last_error = ValueError("no JSON object found in model output")
    raise LLMError(
        f"Model did not return valid JSON after {retries + 1} attempts: {last_error}. "
        f"Raw output (truncated): {raw[:300]!r}"
    )
