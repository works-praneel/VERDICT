# Verdict

Verdict is a lightweight, fully offline pull-request review agent built around
three cooperating LLM-driven roles: a **Scanner** that decides which static
analysis tools apply to a given diff, a **Reviewer** that drafts comments
grounded in both the diff and the scan results, and a **Judge** that weighs
those comments into a single verdict — approve, comment, or request changes.

Unlike a fixed lint-and-report pipeline, each stage makes a genuine decision
based on the state of the PR: a documentation-only change skips code scanners
entirely, a clean PR produces zero comments, and severity is reasoned about
rather than thresholded. Verdict runs entirely on a local LLM via
[Ollama](https://ollama.com), requires no external APIs, and logs every agent
decision to `verdict_runs.jsonl` for full observability into how and why it
reached its verdict.

## Architecture

```
Diff  ->  Scanner (decides which tools to run)
                |
                v
      Bandit / Ruff / test-delta check
                |
                v
      Reviewer (drafts comments, or none)
                |
                v
      Judge (approve / comment / request_changes)
```

Each arrow is a decision, not a fixed pipeline step — see `verdict/agents/`.

## Setup

```bash
./setup.sh                       # installs deps, pulls the local model
python -m verdict.cli review feature/hardcoded-secret
```

By default Verdict looks for a git repo at `./sample_repo`, which ships with
four planted scenarios used to demonstrate autonomy. Verified outcomes below
are from the **deterministic fallback path** (no Ollama needed to reproduce
these); the LLM path is expected to differ in one deliberate way — see the
note underneath.

| Branch | Verified verdict (fallback) | Why |
|---|---|---|
| `feature/hardcoded-secret` | `comment` | Bandit only rates this LOW severity, and the fallback rule just mirrors that |
| `feature/style-issue` | `comment` | Ruff nitpicks (unused import, unsorted imports), nothing blocking |
| `feature/missing-test` | `comment` | New `clamp()` function has no matching test |
| `feature/clean-pr` | `approve` | Zero comments |

**Worth demoing explicitly:** the hardcoded-secret case is the one place the
fallback path and the LLM path should disagree, on purpose. The fallback
rule naively mirrors Bandit's own severity label (LOW), so it under-reacts.
The Judge's actual prompt tells it a hardcoded credential should be treated
as blocking *regardless of the scanner's severity label* — so with a live
model this one should come back as `request_changes`. That gap is the
clearest evidence that the reasoning layer adds real judgment on top of
static analysis, rather than just relabeling its output.

Run `cat verdict_runs.jsonl | python -m json.tool` after a run to see every
decision each agent made along the way.

## Why this counts as agentic, not just a pipeline

- The **Scanner** picks tool subsets per PR (a docs-only change runs nothing)
- The **Reviewer** can — and should — return an empty comment list
- The **Judge** weighs comment severity rather than counting comments
- If Ollama is unreachable, each stage falls back to a clearly-labeled
  deterministic rule (`"source": "fallback"` in the logs) so the pipeline is
  still demoable, but the real decision-making happens in the LLM path
  (`"source": "llm"`)

## Status

Phase 2 (Coding) scaffold — tool wrappers and agent modules are implemented
and unit-tested against fallback logic; LLM-path testing requires a local
Ollama install (see `setup.sh`).
