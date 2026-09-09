"""CLI entry point for the Planner-first PR review pipeline."""
import argparse
import json

from git import Repo

from .agents import judge, planner, reviewer, scanner
from .context import ReviewContext
from .logger import DecisionLogger
from .tools import check_test_delta, get_diff, run_bandit, run_ruff
from .tool_registry import ToolRegistry


def _plan_or_fallback(diff: dict) -> dict:
    """Use semantic planning, retaining Scanner as the v0 failure fallback."""
    try:
        decision = planner.plan(diff["changed_files"], diff["diff_text"])
        return {"path": "planner", "decision": decision}
    except planner.PlannerError as error:
        decision = scanner.decide_tools(diff["changed_files"])
        decision["planner_error"] = str(error)
        return {"path": "scanner_fallback", "decision": decision}


def _run_legacy_tools(scan_decision: dict, repo_path: str, diff: dict) -> dict:
    """Preserve the v0 Scanner-to-tools execution contract for Planner failure."""
    results = {"bandit": [], "ruff": [], "test_delta": {}}
    if "bandit" in scan_decision["tools"]:
        results["bandit"] = run_bandit(repo_path, diff["changed_files"])
    if "ruff" in scan_decision["tools"]:
        results["ruff"] = run_ruff(repo_path, diff["changed_files"])
    if "check_test_delta" in scan_decision["tools"]:
        results["test_delta"] = check_test_delta(diff["diff_text"], diff["changed_files"])
    return results


def review(repo_path: str, branch: str, base: str = "main", log_path: str = "verdict_runs.jsonl") -> dict:
    logger = DecisionLogger(log_path)

    diff = get_diff(repo_path, branch, base)
    logger.log("diff", {"branch": branch, "base": base, "changed_files": diff["changed_files"]})

    context = ReviewContext(changed_files=diff["changed_files"], diff=diff["diff_text"])
    route = _plan_or_fallback(diff)
    decision = route["decision"]
    logger.log("planner" if route["path"] == "planner" else "scanner", decision)

    # bandit/ruff read the working tree, not git history directly, so the branch
    # under review must actually be checked out first — restore whatever was
    # checked out before, even if a scan raises.
    repo = Repo(repo_path)
    original_ref = repo.active_branch.name if not repo.head.is_detached else repo.head.commit.hexsha

    try:
        repo.git.checkout(branch)
        if route["path"] == "planner":
            context.capabilities = decision["capabilities"]
            registry = ToolRegistry()
            resolution = registry.resolve(context.capabilities)
            context.selected_tools = [tool.tool_name for tool in resolution.supported]
            context.unsupported_capabilities = list(resolution.unsupported)
            context.tool_results = registry.execute(
                resolution, repo_path, context.changed_files, context.diff
            )
            logger.log(
                "tool_registry",
                {
                    "capabilities": context.capabilities,
                    "selected_tools": context.selected_tools,
                    "unsupported_capabilities": context.unsupported_capabilities,
                },
            )
        else:
            context.selected_tools = decision["tools"]
            context.tool_results = _run_legacy_tools(decision, repo_path, diff)
    finally:
        repo.git.checkout(original_ref)

    logger.log("scan_results", context.tool_results)

    review_result = reviewer.draft_comments(
        context.diff,
        context.tool_results["bandit"],
        context.tool_results["ruff"],
        context.tool_results["test_delta"],
    )
    logger.log("reviewer", review_result)
    context.comments = review_result["comments"]

    verdict_result = judge.decide_verdict(context.comments)
    logger.log("judge", verdict_result)
    context.verdict = verdict_result

    return {
        "branch": branch,
        "changed_files": diff["changed_files"],
        "planner": decision if route["path"] == "planner" else None,
        "scanner": decision if route["path"] == "scanner_fallback" else None,
        "comments": context.comments,
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
