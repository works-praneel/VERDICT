# Phase 5 Evaluation

## Scope

Phase 5 evaluates VERDICT's bounded agentic investigation loop, including:

- semantic planning and trusted Tool Registry dispatch
- deterministic tools and normalized evidence
- Reviewer and Judge decisions
- bounded investigation rounds and evidence accumulation
- fallback and error handling
- JSONL decision logging

## Automated Tests

The current full test suite passes:

- **125 tests passed**
- Test framework: `pytest`

The suite covers Planner behavior, evidence normalization, investigation
state and execution, Reviewer and Judge behavior, Tool Registry dispatch,
deterministic tools, and fallback/error paths.

## Final Real-Model Regression

The final real-model regression used:

- Model: `qwen2.5-coder:14b`
- Runtime: local Ollama
- Branches tested: **4/4 successful**
- Maximum investigation rounds: **2**

All four branch runs completed with exit code 0. Planner, Investigation
Planner, Reviewer, and Judge used the LLM path in every run. No JSON parsing
errors, fallback responses, or logged errors occurred.

| Branch | Final verdict |
|---|---|
| `feature/clean-pr` | `approve` |
| `feature/hardcoded-secret` | `request_changes` |
| `feature/missing-test` | `request_changes` |
| `feature/style-issue` | `request_changes` |

Each run completed one investigation round followed by an explicit stop
decision. Investigation evidence was accumulated and propagated to the final
Reviewer and Judge.

The six targeted fallback/error regression tests also passed.

## Investigation Safety and Limits

Investigation requests use semantic capability IDs and are bounded to a
maximum of two rounds. The Tool Registry controls which requested
capabilities can execute.

Known limitations:

- `check_test_delta` is a naming-based heuristic; it does not measure actual
  runtime test coverage.
- Security-capability selection for sensitive Python changes remains
  model-driven.

## Historical Evaluation Runs

Historical evaluation runs are retained separately under `historical/`.
They are development records and are separate from the latest verified
real-model regression.

## Repository Status

`sample_repo` was returned to `main` and verified clean after the regression.
The root `README.md` is intentionally still pending its final rewrite.
