# Phase 5 Evaluation

## Scope

Phase 5 evaluates VERDICT's bounded agentic investigation loop, including:

- initial semantic planning
- deterministic tool execution through the Tool Registry
- normalized evidence accumulation
- LLM-based review
- bounded investigation rounds
- unsupported-capability handling
- repeated-capability prevention
- final judgment
- JSONL audit logging
- deterministic fallback behavior

## Automated Tests

The final Phase 5 implementation passes:

- **89 tests passed**
- Test framework: `pytest`
- Python: 3.11.9

The suite covers:

- Planner behavior
- Evidence normalization
- Investigation state
- Investigation loop
- Investigation planner
- Phase 1 and Phase 2 regressions
- Tool Registry and tool execution
- LLM verification

## Final Real-Model Evaluation

The final real-model evaluations used:

- Model: `qwen2.5-coder:14b`
- Runtime: Ollama
- Maximum investigation rounds: `2`

### Hardcoded Secret

Input:

`feature/hardcoded-secret`

Observed behavior:

1. The Planner selected:
   - `detect_python_security`
   - `lint_python`
2. Bandit detected the hardcoded secret at `app.py:15`.
3. The Reviewer produced a blocking comment grounded at `app.py:15`.
4. The Investigation Planner requested `detect_environment_variables`.
5. The Tool Registry rejected the unsupported capability.
6. The unsupported goal was recorded as unresolved.
7. The Judge returned `request_changes`.

This demonstrates bounded investigation and the registry safety boundary.

### Missing Test Coverage

Input:

`feature/missing-test`

Observed behavior:

1. The Planner selected:
   - `lint_python`
   - `check_new_python_test_coverage`
2. The coverage tool detected that `clamp` had no matching tests.
3. The evidence contained no file or line location.
4. The Reviewer preserved this limitation:
   - `file: ""`
   - `line: null`
5. The Investigation Planner requested an unsupported capability.
6. The Tool Registry rejected it.
7. The Judge returned `request_changes`.

This evaluation also verifies the Reviewer grounding fix: the model did not invent a file or line number.

## Deterministic Fallback Evaluation

Additional evaluations were performed with Ollama unavailable.

The CLI correctly fell back to deterministic behavior.

Scenarios included:

- clean PR
- hardcoded secret
- style issues
- missing test coverage

The fallback path continued to produce structured evidence and safe review results.

## Investigation Safety

The investigation loop does not allow the LLM to execute arbitrary commands.

The LLM requests semantic capabilities. The Tool Registry determines whether those capabilities are registered.

Unsupported capabilities are recorded as unresolved rather than executed.

Previously completed capabilities and previously unresolved capabilities are not repeatedly investigated.

## Known Limitation

The Investigation Planner can generate semantic capability IDs that are not currently registered.

Examples observed during real-model evaluation include:

- `detect_environment_variables`
- `semantic_capability_id`

The current implementation handles these safely by rejecting them through the Tool Registry and recording them as unresolved.

This is a model-output limitation rather than an arbitrary-execution path.

## Historical Evaluation Runs

Intermediate experiments are retained under:

`historical/`

These include earlier runs used to identify and correct:

- repeated unsupported-capability investigation
- Planner selection of test-coverage analysis
- Reviewer location hallucination
- real-model investigation behavior

The historical runs are retained as development evidence rather than being treated as final benchmark results.
