# Phase 1 agentic-development log

## 1. Phase 1 objective

Phase 1 introduced a Planner-first review path while preserving VERDICT's existing deterministic Scanner path as the v0 fallback. The approved normal flow is:

```text
PR diff -> Planner -> semantic capabilities -> Tool Registry -> trusted tools -> Reviewer -> Judge
```

## 2. Starting v0 architecture

The v0 CLI obtained a diff, asked `verdict/agents/scanner.py` to select the concrete checks `bandit`, `ruff`, and `check_test_delta`, ran those tools, then passed their results to the Reviewer and Judge. Scanner's deterministic rule was used when its LLM request failed.

## 3. Phase 1 target architecture

The normal path now asks `verdict/agents/planner.py` for semantic capability IDs. `verdict/tool_registry.py` resolves registered capability IDs to the existing trusted functions in `verdict/tools.py`. Reviewer continues to receive the actual diff and the established Bandit, Ruff, and test-delta result shapes; Judge remains the final decision stage.

If planning fails, the CLI uses the existing Scanner and its legacy direct tool execution path. Planner failure and an unsupported capability are deliberately separate states.

## 4. Human and architectural decisions

- Keep `verdict/agents/scanner.py` unchanged as the v0 fallback; do not rename or turn it into the Planner.
- Keep `verdict/tools.py` as the source of truth for current tool implementations.
- Keep the initial capability vocabulary small and grounded in existing tools: `detect_python_security`, `lint_python`, and `check_new_python_test_coverage`.
- Planner outputs capability IDs only. It must not select concrete tool names, executable commands, or Python callables.
- Unsupported capabilities are recorded and do not prevent supported capabilities from running.
- Do not add a general command runner, LangChain, LangGraph, memory, autonomous loops, self-evaluation, UI, or Phase 2 tools.

## 5. Codex implementation work

Codex added:

- `verdict/agents/planner.py`, which receives changed files and diff text, requests structured LLM output, and validates its capability list and reason.
- `verdict/tool_registry.py`, which contains explicit registrations to the existing Bandit, Ruff, and test-delta functions.
- `verdict/context.py`, a lightweight `ReviewContext` dataclass for pipeline state: diff data, capabilities, selected tools, unsupported capabilities, tool results, comments, verdict, and metadata.
- `tests/test_phase1.py`, covering Planner, registry, fallback, and context behavior.

Codex minimally updated `verdict/cli.py` to follow the Planner-first normal path and retain the Scanner-first legacy path for a Planner failure. Reviewer and Judge implementations were not redesigned.

## 6. Security-boundary issue discovered during audit

The final read-only audit identified that `ToolRegistry.execute()` accepted a caller-provided `ToolResolution` and invoked each contained registration's callable without first verifying that the registration belonged to that registry instance. The normal CLI path obtained resolutions through `resolve()`, but the method did not independently enforce the trusted-registration boundary.

## 7. Security fix and focused test

`ToolRegistry.execute()` now rejects a registration unless it is present in `self._registrations.values()` before dispatch. This enforces that only a registration owned by the registry can execute through the registry.

A focused regression test constructs a forged `ToolRegistration` containing a caller-supplied lambda inside a forged `ToolResolution`. The test asserts that execution raises `RuntimeError` and that the lambda is never called.

No arbitrary shell execution or LLM-provided command execution was added.

## 8. Tests and verification results

Recorded focused verification results:

- `pytest tests/test_phase1.py tests/test_agents.py tests/test_tools.py -q` completed with **33 passed**.
- `git diff --check` passed without whitespace errors. Git emitted an existing CRLF warning for `verdict/cli.py`.
- A controlled live run with `VERDICT_MODEL=gpt-oss:20b` explicitly present in the Python process completed the normal Phase 1 path for `feature/hardcoded-secret`: Planner source was `llm`, selected `detect_python_security` and `lint_python`, Reviewer emitted a blocking hardcoded-secret finding, and Judge returned `request_changes` with source `llm`.

The focused tests cover Python, TypeScript, Dockerfile, Terraform, docs-only, custom/unknown file types, mixed-language plans, Planner validation, Planner failure fallback, supported and unsupported resolution, unregistered capabilities, and the forged-registration execution boundary.

## 9. `sample_repo` pytest collection issue

This is a fixture-repository test-discovery issue, **not a Phase 1 regression**.

`sample_repo/tests/test_app.py` imports `from app import add, subtract`. Direct Python import succeeds after changing the process directory to `sample_repo`, because that directory then becomes an import root. Pytest collection from the VERDICT root fails with `ModuleNotFoundError: No module named 'app'` because the fixture repository has no package or pytest import-path configuration placing `sample_repo/` on that import path.

A separate fixture-repository fix can use a package-qualified import such as `from sample_repo.app import add, subtract` (optionally with explicit package metadata). It is not part of Phase 1.

## 10. What changed from v0

v0 used a Scanner-selected concrete-tool flow. Phase 1 adds a semantic Planner and a trusted Tool Registry on the normal path, plus explicit pipeline state in `ReviewContext`. It preserves Scanner and legacy tool execution as the fallback when planning fails.

## 11. What did not change or was explicitly deferred

- Scanner remains the v0 fallback.
- Existing tool implementations remain in `verdict/tools.py`.
- Reviewer and Judge remain LLM-driven; Phase 1 does not claim to fix their known quality limitations.
- No new real TypeScript, Dockerfile, Terraform, or custom-file tools were added. Such capabilities remain unsupported after registry resolution.
- No Phase 2 features were implemented.

## 12. Lessons learned from using Codex

- Keeping the v0 path intact made it possible to add the Planner path without redefining existing reviewer or judge behavior.
- Semantic planning and execution must have separate contracts: a valid but unsupported capability is not a planning failure.
- The execution boundary needs enforcement at dispatch time, not only an assumption that callers obtained a resolution through the normal path.
- Runtime environment checks must be performed in the Python process that imports VERDICT. `VERDICT_MODEL` is captured by `verdict.llm` at import time.

## 13. Current limitations and unknowns

- Only the three existing Python-oriented tools are registered. Non-Python semantic capabilities may be planned and are then explicitly unsupported.
- Live-model behavior has been demonstrated for the hardcoded-secret scenario; additional live-model scenarios remain useful evaluation work.
- An earlier Ollama 404 did not recur when `VERDICT_MODEL=gpt-oss:20b` was explicitly present in the Python process. The evidence supports a process/import-time model-environment difference as a likely factor, but does not prove the complete historical cause.
- The `sample_repo` pytest import-layout issue remains separate work.

## 14. Phase 1 acceptance status

Phase 1 is accepted based on the implemented Planner-first path, preserved v0 Scanner fallback, enforced trusted registry dispatch, focused regression tests, and the recorded controlled live run. Commit and push were intentionally not performed during development.
