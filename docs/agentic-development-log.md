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

## Phase 2 step 1: normalized evidence adapters

Phase 2 step 1 added `verdict/evidence.py` without changing the existing tool
implementations, Planner, ToolRegistry, CLI, Reviewer, or Judge. It defines a
minimal JSON-serializable `Evidence` contract and deterministic adapters for
the current Bandit, Ruff, and test-delta result shapes.

The adapters preserve capability and source-tool attribution, return no
evidence for clean results, and skip malformed records rather than raising.
Bandit source severities normalize to `high`, `medium`, or `low`; Ruff and
test-delta evidence use `info`. The test-delta adapter emits evidence only
when its existing `missing_coverage` flag is exactly `True`.

Focused tests cover one normalized finding for each existing tool, clean
results, malformed inputs, allowed normalized severities, and JSON
serialization. Dockerfile capability work, ToolRegistry evidence wiring, and
Reviewer migration remain later Phase 2 steps.

During focused-test collection, pytest treated helper names beginning with
`test_` as test functions and attempted to supply their `result` argument as a
fixture. The test-delta adapter therefore uses the non-test-prefixed name
`coverage_delta_to_evidence`; no production tool output or pipeline interface
changed.

## Phase 2 step 2: trusted registry evidence wiring

Phase 2 Step 2 attaches each existing Evidence adapter to its fixed trusted
ToolRegistry registration. Registry execution now returns both unchanged raw
Bandit, Ruff, and test-delta outputs and normalized Evidence aggregated by
those registration-owned adapters. ReviewContext stores that Evidence beside
its raw tool results, and both the Planner path and retained Scanner fallback
use the same registry execution mechanism.

Focused tests cover fixed adapter ownership, normalized Bandit/Ruff/test-delta
results, clean output, ReviewContext storage, unsupported capabilities, the
forged-registration boundary, and Scanner fallback evidence. No arbitrary
shell execution, dynamic imports, LLM-selected callables/adapters, or dynamic
tool discovery was introduced.

Planner, Reviewer severity handling, Judge behavior, and `verdict/tools.py`
are intentionally unchanged. Only the three existing Python-oriented tools
are registered; unsupported capabilities and Docker capability work remain out
of scope.

## Phase 2 step 3: Dockerfile base-image pinning

Phase 2 Step 3 adds the semantic capability
`check_container_base_image_pinning`. Its trusted deterministic checker reads
only changed Dockerfile diff lines and flags added `FROM` instructions that
are untagged or explicitly use `:latest`; ordinary version tags such as
`python:3.12` and `ubuntu:24.04` are accepted. Findings are normalized through
the registry-owned Evidence adapter with Dockerfile source location, image,
and reason attribution.

Docker Engine, Docker Desktop, image builds, containers, network calls, and
new dependencies are not required because the policy is static diff analysis.
Focused tests cover untagged and `:latest` findings, accepted version tags,
clean diffs, registry resolution, and normalized Evidence. The trusted
registration boundary remains unchanged: the Planner selects only semantic
capabilities, while fixed registrations own the callable and adapter.

Version tags themselves can still be mutable; digest pinning is a stronger
future policy and is intentionally not implemented here. Scanner fallback,
Reviewer severity logic, Judge behavior, the Evidence contract, and all later
Phase 2 work remain unchanged.

## Phase 3: Reviewer Evidence Migration

Phase 3 migrates Reviewer to accept the diff and normalized Evidence rather
than tool-specific raw Bandit, Ruff, and test-delta inputs. Raw tool results
remain in ReviewContext for diagnostics and backwards compatibility, while the
normal CLI path supplies `context.evidence` to Reviewer.

The deterministic fallback preserves the existing mapping: high/medium
security Evidence produces blocking comments, lower-severity security and lint
Evidence produce nitpicks, and test-coverage Evidence produces notes. Focused
tests cover the normalized prompt input, each fallback mapping, clean
Evidence, and normal CLI evidence propagation; `pytest -q --ignore=sample_repo`
completed with 54 passing tests.

Planner, ToolRegistry, Evidence, Docker checking, Scanner fallback, logging,
and Judge behavior remain unchanged. Judge still receives Reviewer comments,
rather than independently consuming the evidence bundle.

## Phase 4: Independent Judge

The human-supplied Phase 4 requirement was for Judge to independently assess
the PR diff and normalized Evidence, treating Reviewer comments as advisory.
Codex implemented that interface and prompt migration, updated the CLI to pass
`context.diff`, `context.evidence`, and Reviewer comments, and retained raw
tool results solely for diagnostics and backwards compatibility.

The deterministic fallback preserves the established blocking treatment for
high/medium security Evidence and blocking comments, while minor supported
Evidence or comments yield `comment`; empty or malformed Evidence with no
comments yields `approve`. Focused tests cover Judge prompt inputs, empty
input approval, serious Evidence without Reviewer comments, malformed
Evidence, and normal CLI wiring. Autonomous investigation loops remain out of
scope.

`pytest -q --ignore=sample_repo` completed with 58 passing tests.

Planner, ToolRegistry, Evidence adapters, Docker checking, Reviewer, Scanner
fallback, logging, and the verdict vocabulary remain unchanged. The Judge is
still bounded by the supplied diff and Evidence; it does not independently
collect new facts.

## Phase 4 evaluation / retrospective

The human supplied the Phase 4 architectural requirements. Codex implemented
the independent Judge interface and wiring described above. The following
evaluation was performed manually against the live local LLM; it was not
performed by Codex.

- **Hardcoded-secret:** Planner source was `llm`. Evidence was a Bandit
  hardcoded-password finding at low severity; Reviewer produced a blocking
  security comment; Judge returned `request_changes` with source `llm`. Judge
  explicitly recognized the hardcoded credential as a security violation
  despite Bandit's `LOW` severity.
- **Missing-test:** Planner source was `llm`. Evidence was `test_coverage` for
  `clamp` with no matching tests. Reviewer produced a test-coverage comment
  but incorrectly referenced `app.py` line 12 rather than the changed
  `utils.py` location. Judge returned `request_changes` with source `llm` and
  correctly reasoned from the missing-test Evidence.
- **Clean-pr:** Evidence and Reviewer comments were both empty. Judge returned
  `approve` with source `rule`, confirming that the empty-input fast path
  avoids an unnecessary LLM Judge call.
- **Style-issue:** Evidence contained Ruff lint findings plus missing-test
  coverage; Reviewer produced nitpick/note comments; Judge returned
  `request_changes` with source `llm`. This is a known policy/severity
  limitation, not a Phase 4 implementation failure.
- **Controlled adversarial Reviewer test:** With an added unused import and
  informational lint Evidence only, Reviewer deliberately claimed a critical
  security vulnerability. Judge returned `request_changes` with source `llm`,
  explicitly stated that no evidence supported a security vulnerability, and
  rejected the Reviewer's blocking claim. It nevertheless judged the unused
  import sufficient to require correction, demonstrating that Judge does not
  blindly copy Reviewer comments.

Phase 4 demonstrated independent use of the diff and normalized Evidence,
including resistance to an unsupported Reviewer claim and the empty-input
fast path. It did not demonstrate autonomous fact gathering, broader policy
calibration, or corrected source grounding. The missing-test Reviewer location
error is a known grounding limitation, and the style-issue outcome is a known
severity/policy limitation; neither is a reason to undo the independent Judge
architecture. Phase 4 implementation and controlled evaluation passed and is
ready for checkpoint v0.4.0. Phase 5 should be designed separately;
autonomous investigation remains out of scope.

## Phase 5 Step 1: investigation goal and state

The human architectural requirement for this step was a minimal bounded
representation for semantic investigation goals and state, without an
investigation loop or new capabilities. Codex added immutable
`InvestigationGoal` records with a question, semantic required capability, and
reason; concrete known tool names and malformed capability IDs are rejected.

Codex also added `InvestigationState` to `ReviewContext`, recording the
current/next round, requested goals, completed capabilities, and unresolved
goals. This is pipeline state only: no Planner, Reviewer, Judge, ToolRegistry,
CLI, LLM, tool, or execution behavior changed. Focused tests cover valid and
invalid goals, empty state initialization, completed-capability tracking, and
unresolved goals. Autonomous investigation, persistence, web access, shell
execution, and code modification remain out of scope.

`pytest -q --ignore=sample_repo` completed with 64 passing tests.
The capability validation was subsequently decoupled from the context model so that ToolRegistry remains authoritative for supported capabilities; the regression suite remained green with 64 passing tests.
