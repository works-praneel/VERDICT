# VERDICT

**An offline pull-request reviewer powered by a local LLM.**
Point it at a git branch and it runs trusted checks, writes review comments, and returns a verdict: `approve`, `comment`, or `request_changes`. It runs on [Ollama](https://ollama.com), so there are no API keys and no code leaves your machine.

## How it works

Four cooperating LLM-driven roles:

| Role | Job |
|---|---|
| **Planner** | Reads the diff and decides which checks are relevant (a docs-only change runs none) |
| **Reviewer** | Writes comments grounded in the diff and the tool results, or none if the PR is clean |
| **Investigation Planner** | If the evidence is insufficient, requests one more check (max 2 rounds) |
| **Judge** | Independently weighs the diff, the evidence and the Reviewer's comments, then decides |

```
PR diff
  │
  ▼
Planner (LLM) ──► Tool Registry ──► Evidence ──► Reviewer (LLM)
                  (allow-list of        │              │
                   trusted tools)       │              ▼
                       ▲                │      Investigation Planner (LLM)
                       └── extra check ─┴───── loop, max 2 rounds
                                                       │
                                                       ▼
                                                 Judge (LLM) ──► verdict
```

Key design choices:
- **Agents request capabilities, not commands.** The Planner outputs names like `lint_python`; the Tool Registry maps them to fixed, pre-written functions. The LLM can never run arbitrary code.
- **Normalized evidence.** Output from every tool is converted to one common format.
- **Safe fallbacks.** If the model is unreachable or returns bad output, simple deterministic rules take over and the log marks them `"source": "fallback"`.
- **Full observability.** Every decision is appended to `verdict_runs.jsonl`.

## What it can check

| Capability | Checks for | Backed by |
|---|---|---|
| `detect_python_security` | Security issues such as hardcoded secrets | Bandit |
| `lint_python` | Style issues such as unused or unsorted imports | Ruff |
| `check_new_python_test_coverage` | New functions without a matching test | Built-in heuristic |
| `check_container_base_image_pinning` | Dockerfile `FROM` lines that are untagged or `:latest` | Built-in diff check |
| `inspect_python_test_references` | Follow-up: is a new function referenced by any existing test? | Built-in read-only search |

## Quick start

**Requirements:** Python 3.10+, git, [Ollama](https://ollama.com/download).

```bash
git clone https://github.com/works-praneel/VERDICT.git
cd VERDICT
./setup.sh                        # installs dependencies, pulls qwen2.5-coder:14b
```

On Windows, run the two steps by hand: `pip install -r requirements.txt` and `ollama pull qwen2.5-coder:14b`.

Make sure Ollama is running, then review a branch:

```bash
python -m verdict.cli review <branch> --repo <path-to-git-repo> --base main
```

The target repo must have a base branch (default `main`) and a clean working tree.

| Option | Default | Meaning |
|---|---|---|
| `--repo` | `sample_repo` | Path to the git repo |
| `--base` | `main` | Branch to diff against |
| `--log` | `verdict_runs.jsonl` | Decision log file |
| `--max-rounds` | `2` | Maximum investigation rounds |

To use another model, set `VERDICT_MODEL` **before** starting Python (it is read at import time):
```bash
export VERDICT_MODEL="qwen3:8b"        # PowerShell: $env:VERDICT_MODEL="qwen3:8b"
```

### Reading the output

The command prints JSON with `planner`, `evidence`, `investigation`, `comments` and `verdict`. Each decision has a `source`:
- `llm`: decided by the model
- `rule`: a simple shortcut (for example, nothing found, so approve without calling the model)
- `fallback`: the model failed and a safety rule took over

### Try it on a demo repo

`sample_repo/` is not included in this repository, so create a small one:

```bash
mkdir sample_repo && cd sample_repo
git init -b main
printf 'def add(a, b):\n    return a + b\n' > app.py
git add . && git commit -m "base"
git checkout -b feature/hardcoded-secret
printf '\nAPI_TOKEN = "sk-live-12345-secret"\n' >> app.py
git commit -am "add secret"
git checkout main && cd ..

python -m verdict.cli review feature/hardcoded-secret --repo sample_repo
```

### Tests

```bash
pytest -q --ignore=sample_repo
```
The tests do not need Ollama.

### Troubleshooting

| Problem | Fix |
|---|---|
| `Could not reach Ollama` | Start Ollama and run `ollama pull <model>` |
| Everything shows `"source": "fallback"` | Check that Ollama is running and the model name is correct |
| `has uncommitted changes` | Commit or stash changes in the repo being reviewed |
| Empty diff or branch not found | Check branch names; the default base is `main`, not `master` |

## Results

On four planted scenarios with `qwen2.5-coder:14b` (local Ollama), every run completed using the LLM path:

| Branch | Verdict |
|---|---|
| `feature/clean-pr` | `approve` |
| `feature/hardcoded-secret` | `request_changes` |
| `feature/missing-test` | `request_changes` |
| `feature/style-issue` | `request_changes` |

Notable behaviours: the Judge blocked a hardcoded secret even though Bandit rated it only `LOW`, and it rejected a deliberately false "critical vulnerability" claim from the Reviewer. Run logs are in [`evaluation/`](evaluation/).

## Motivation

Most automated review tools run a fixed lint-and-report pipeline. VERDICT explores whether each stage can make a real decision instead, such as what to check, how serious a finding is, and whether more evidence is needed, while staying private, free to run, and constrained to a safe set of tools.

## How it was built

VERDICT was built with an agentic coding workflow. The human set the architecture, constraints and phase scope, and ran the live-model evaluations. A coding agent (Codex) implemented the code and tests. Details are in [`docs/agentic-development-log.md`](docs/agentic-development-log.md).

At runtime it is **agentic but bounded**: the Planner, Investigation Planner and Judge make real decisions in a loop, but they can only use a fixed tool allow-list, the loop is capped at 2 rounds, and some mandatory checks are enforced by plain code.

## Known limitations

- The test-coverage check is a naming-based heuristic, not real coverage.
- The Reviewer sometimes cites an incorrect file or line.
- The Investigation Planner occasionally requests capability IDs that don't exist; these are safely ignored but waste a round.
- A style-only change can be marked `request_changes`, which is stricter than a human likely would be.
- Only Python and Dockerfile checks exist.
- Evaluation covers four hand-built scenarios, so it shows behaviour rather than general accuracy.

## Project layout

```
verdict/
├── cli.py               # entry point and review loop
├── llm.py               # Ollama client with JSON extraction and retries
├── tool_registry.py     # capability -> trusted tool (security boundary)
├── tools.py             # Bandit, Ruff, test and Docker checks
├── evidence.py          # normalizes tool output
├── context.py           # pipeline state
├── logger.py            # writes verdict_runs.jsonl
└── agents/              # planner, reviewer, investigation_planner, judge, scanner (legacy fallback)
tests/                   # pytest suite
evaluation/              # recorded run logs
docs/                    # development log
```
