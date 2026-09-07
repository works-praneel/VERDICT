"""Diagnostic runner for the real LLM path.

Unlike `verdict.cli`, this calls each agent stage directly (not through the
fallback-catching wrapper) so failures are loud and specific, and prints the
model's raw text whenever JSON parsing fails — that raw text is what you
actually need to see to fix a prompt.

Usage:
    python verify_llm.py
"""
import json
import sys

from git import Repo

from verdict.agents import judge, reviewer, scanner
from verdict.llm import LLMError, call_llm
from verdict.tools import check_test_delta, get_diff, run_bandit, run_ruff

REPO_PATH = "sample_repo"

SCENARIOS = [
    ("feature/hardcoded-secret", "request_changes", "LLM should override Bandit's LOW rating and block"),
    ("feature/style-issue", "comment", "nitpicks only, not blocking"),
    ("feature/missing-test", "comment", "missing coverage is a note, not blocking"),
    ("feature/clean-pr", "approve", "zero comments expected"),
]


def check_ollama_reachable():
    try:
        call_llm("Reply with exactly: OK")
        print("[OK] Ollama is reachable.\n")
    except LLMError as e:
        print(f"[FAIL] Cannot reach Ollama: {e}")
        sys.exit(1)


def run_scenario(branch, expected_verdict, expected_reason):
    print(f"{'=' * 70}\n{branch}\nExpected: {expected_verdict}  ({expected_reason})\n{'=' * 70}")

    diff = get_diff(REPO_PATH, branch, "main")
    print(f"Changed files: {diff['changed_files']}")

    # --- Scanner ---
    scan_decision = scanner.decide_tools(diff["changed_files"])
    print(f"\n[Scanner] source={scan_decision['source']} tools={scan_decision['tools']}")
    print(f"[Scanner] reason: {scan_decision['reason']}")
    if scan_decision["source"] != "llm":
        print(f"  >> LLM path did NOT run for Scanner. Error: {scan_decision.get('error', 'unknown')}")

    # --- Run tools on the actual branch content ---
    repo = Repo(REPO_PATH)
    original_ref = repo.active_branch.name
    bandit_findings, ruff_findings, test_delta = [], [], {}
    try:
        repo.git.checkout(branch)
        if "bandit" in scan_decision["tools"]:
            bandit_findings = run_bandit(REPO_PATH, diff["changed_files"])
        if "ruff" in scan_decision["tools"]:
            ruff_findings = run_ruff(REPO_PATH, diff["changed_files"])
        if "check_test_delta" in scan_decision["tools"]:
            test_delta = check_test_delta(diff["diff_text"], diff["changed_files"])
    finally:
        repo.git.checkout(original_ref)
    print(f"\nBandit findings: {bandit_findings}")
    print(f"Ruff findings: {ruff_findings}")
    print(f"Test delta: {test_delta}")

    # --- Reviewer ---
    review_result = reviewer.draft_comments(diff["diff_text"], bandit_findings, ruff_findings, test_delta)
    print(f"\n[Reviewer] source={review_result['source']}")
    for c in review_result["comments"]:
        print(f"  - {c['severity']}: {c['comment']}")
    if review_result["source"] != "llm":
        print(f"  >> LLM path did NOT run for Reviewer. Error: {review_result.get('error', 'unknown')}")

    # --- Judge ---
    verdict_result = judge.decide_verdict(review_result["comments"])
    print(f"\n[Judge] source={verdict_result['source']} verdict={verdict_result['verdict']}")
    print(f"[Judge] justification: {verdict_result['justification']}")
    if verdict_result["source"] != "llm" and verdict_result["source"] != "rule":
        print(f"  >> LLM path did NOT run for Judge. Error: {verdict_result.get('error', 'unknown')}")

    match = verdict_result["verdict"] == expected_verdict
    print(f"\n{'MATCH' if match else 'MISMATCH'}: got '{verdict_result['verdict']}', expected '{expected_verdict}'")
    print()
    return {
        "branch": branch,
        "expected": expected_verdict,
        "actual": verdict_result["verdict"],
        "match": match,
        "scanner_source": scan_decision["source"],
        "reviewer_source": review_result["source"],
        "judge_source": verdict_result["source"],
    }


def main():
    print("Checking Ollama connection...\n")
    check_ollama_reachable()

    results = [run_scenario(*s) for s in SCENARIOS]

    print(f"{'=' * 70}\nSUMMARY\n{'=' * 70}")
    for r in results:
        status = "MATCH   " if r["match"] else "MISMATCH"
        all_llm = all(r[k] == "llm" for k in ("scanner_source", "reviewer_source", "judge_source"))
        print(f"{status}  {r['branch']:35s}  got={r['actual']:16s}  all_llm={all_llm}")

    with open("llm_verification_report.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nFull report written to llm_verification_report.json")


if __name__ == "__main__":
    main()
