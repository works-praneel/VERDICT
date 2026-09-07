"""CLI entry point: `python -m verdict.cli review <branch>`

Runs the full pipeline end to end: diff -> scanner -> tools -> reviewer ->
judge, logging every decision along the way.
"""
import argparse
import json

from git import Repo

from .agents import judge, reviewer, scanner
from .logger import DecisionLogger
from .tools import check_test_delta, get_diff, run_bandit, run_ruff


def review(repo_path: str, branch: str, base: str = "main", log_path: str = "verdict_runs.jsonl") -> dict:
    logger = DecisionLogger(log_path)

    diff = get_diff(repo_path, branch, base)
    logger.log("diff", {"branch": branch, "base": base, "changed_files": diff["changed_files"]})

    scan_decision = scanner.decide_tools(diff["changed_files"])
    logger.log("scanner", scan_decision)

    # bandit/ruff read the working tree, not git history directly, so the branch
    # under review must actually be checked out first — restore whatever was
    # checked out before, even if a scan raises.
    repo = Repo(repo_path)
    original_ref = repo.active_branch.name if not repo.head.is_detached else repo.head.commit.hexsha

    bandit_findings, ruff_findings, test_delta = [], [], {}
    try:
        repo.git.checkout(branch)
        if "bandit" in scan_decision["tools"]:
            bandit_findings = run_bandit(repo_path, diff["changed_files"])
        if "ruff" in scan_decision["tools"]:
            ruff_findings = run_ruff(repo_path, diff["changed_files"])
        if "check_test_delta" in scan_decision["tools"]:
            test_delta = check_test_delta(diff["diff_text"], diff["changed_files"])
    finally:
        repo.git.checkout(original_ref)

    logger.log(
        "scan_results",
        {"bandit": bandit_findings, "ruff": ruff_findings, "test_delta": test_delta},
    )

    review_result = reviewer.draft_comments(diff["diff_text"], bandit_findings, ruff_findings, test_delta)
    logger.log("reviewer", review_result)

    verdict_result = judge.decide_verdict(review_result["comments"])
    logger.log("judge", verdict_result)

    return {
        "branch": branch,
        "changed_files": diff["changed_files"],
        "scanner": scan_decision,
        "comments": review_result["comments"],
        "verdict": verdict_result,
    }


def main():
    parser = argparse.ArgumentParser(prog="verdict", description="Autonomous local PR review agent")
    sub = parser.add_subparsers(dest="command", required=True)

    review_parser = sub.add_parser("review", help="Review a branch against a base branch")
    review_parser.add_argument("branch", help="Branch to review")
    review_parser.add_argument("--repo", default="sample_repo", help="Path to the git repo")
    review_parser.add_argument("--base", default="main", help="Base branch to diff against")
    review_parser.add_argument("--log", default="verdict_runs.jsonl", help="Decision log path")

    args = parser.parse_args()

    if args.command == "review":
        result = review(args.repo, args.branch, args.base, args.log)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
