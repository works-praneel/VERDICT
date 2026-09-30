"""CLI entry point for the Planner-first PR review pipeline."""
import argparse
import json

from git import Repo

from .agents import investigation_planner, judge, planner, reviewer, scanner
from .context import ReviewContext
from .logger import DecisionLogger
from .tools import get_diff
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


def _run_legacy_tools(scan_decision: dict, repo_path: str, diff: dict):
    """Run Scanner's fixed names through the trusted registry."""
    registry = ToolRegistry()
    resolution = registry.resolve_scanner_tools(scan_decision["tools"])
    return registry.execute(resolution, repo_path, diff["changed_files"], diff["diff_text"])


DEFAULT_MAX_ROUNDS = 2


def review(
    repo_path: str,
    branch: str,
    base: str = "main",
    log_path: str = "verdict_runs.jsonl",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> dict:
    logger = DecisionLogger(log_path)

    diff = get_diff(repo_path, branch, base)
    logger.log("diff", {"branch": branch, "base": base, "changed_files": diff["changed_files"]})

    context = ReviewContext(changed_files=diff["changed_files"], diff=diff["diff_text"])
    route = _plan_or_fallback(diff)
    decision = route["decision"]
    logger.log("planner" if route["path"] == "planner" else "scanner", decision)

    repo = Repo(repo_path)
    original_ref = repo.active_branch.name if not repo.head.is_detached else repo.head.commit.hexsha

    try:
        repo.git.checkout(branch)
        registry = ToolRegistry()
        if route["path"] == "planner":
            context.capabilities = decision["capabilities"]
            resolution = registry.resolve(context.capabilities)
            context.selected_tools = [tool.tool_name for tool in resolution.supported]
            context.unsupported_capabilities = list(resolution.unsupported)
            execution = registry.execute(
                resolution, repo_path, context.changed_files, context.diff
            )
            context.tool_results = execution.raw_results
            context.evidence = list(execution.evidence)
            context.investigation.completed_capabilities.update(
                tool.capability for tool in resolution.supported
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
            execution = _run_legacy_tools(decision, repo_path, diff)
            context.tool_results = execution.raw_results
            context.evidence = list(execution.evidence)
            for t in decision["tools"]:
                cap = registry._scanner_tool_capabilities.get(t)
                if cap:
                    context.investigation.completed_capabilities.add(cap)

        context.investigation.evidence = list(context.evidence)
        logger.log("scan_results", context.tool_results)

        review_result = reviewer.draft_comments(context.diff, context.evidence)
        logger.log("reviewer", review_result)
        context.comments = review_result["comments"]

        while context.investigation.current_round < max_rounds:
            investigation_decision = investigation_planner.plan_investigation(
                context.diff,
                context.evidence,
                context.comments,
                context.investigation,
            )
            round_num = context.investigation.next_round
            goals = investigation_decision.get("goals", [])
            investigate = investigation_decision.get("investigate", False)

            logger.log(
                "investigation_planner",
                {
                    "round": round_num,
                    "investigate": investigate,
                    "goals": [
                        {
                            "question": g.question,
                            "required_capability": g.required_capability,
                            "reason": g.reason,
                        }
                        for g in goals
                    ],
                    "source": investigation_decision.get("source", "fallback"),
                },
            )

            if not investigate or not goals:
                break

            context.investigation.current_round = round_num
            context.investigation.requested_goals.extend(goals)

            requested_capabilities = [g.required_capability for g in goals]
            resolution = registry.resolve(requested_capabilities)

            supported_caps = {tool.capability for tool in resolution.supported}
            for g in goals:
                if g.required_capability not in supported_caps:
                    context.investigation.unresolved_goals.append(g)

            logger.log(
                "investigation_registry",
                {
                    "round": round_num,
                    "capabilities": requested_capabilities,
                    "selected_tools": [tool.tool_name for tool in resolution.supported],
                    "unsupported_capabilities": list(resolution.unsupported),
                },
            )

            if resolution.supported:
                execution = registry.execute(
                    resolution, repo_path, context.changed_files, context.diff
                )
                for tool in resolution.supported:
                    context.investigation.completed_capabilities.add(tool.capability)
                context.evidence.extend(execution.evidence)
                context.investigation.evidence.extend(execution.evidence)
                for k, v in execution.raw_results.items():
                    if k in context.tool_results:
                        if isinstance(context.tool_results[k], list) and isinstance(v, list):
                            context.tool_results[k].extend(v)
                        elif isinstance(context.tool_results[k], dict) and isinstance(v, dict):
                            context.tool_results[k].update(v)
                    else:
                        context.tool_results[k] = v

                logger.log(
                    "investigation_results",
                    {
                        "round": round_num,
                        "raw_results": execution.raw_results,
                        "new_evidence": execution.evidence,
                    },
                )

                review_result = reviewer.draft_comments(context.diff, context.evidence)
                logger.log("reviewer", {"round": round_num, **review_result})
                context.comments = review_result["comments"]

    finally:
        repo.git.checkout(original_ref)

    verdict_result = judge.decide_verdict(context.diff, context.evidence, context.comments)
    logger.log("judge", verdict_result)
    context.verdict = verdict_result

    return {
        "branch": branch,
        "changed_files": diff["changed_files"],
        "planner": decision if route["path"] == "planner" else None,
        "scanner": decision if route["path"] == "scanner_fallback" else None,
        "evidence": context.evidence,
        "investigation": {
            "current_round": context.investigation.current_round,
            "completed_capabilities": sorted(context.investigation.completed_capabilities),
            "requested_goals": [
                {
                    "question": g.question,
                    "required_capability": g.required_capability,
                    "reason": g.reason,
                }
                for g in context.investigation.requested_goals
            ],
            "unresolved_goals": [
                {
                    "question": g.question,
                    "required_capability": g.required_capability,
                    "reason": g.reason,
                }
                for g in context.investigation.unresolved_goals
            ],
            "evidence": context.investigation.evidence,
        },
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
    review_parser.add_argument(
        "--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS, help="Maximum investigation rounds"
    )

    args = parser.parse_args()

    if args.command == "review":
        result = review(args.repo, args.branch, args.base, args.log, args.max_rounds)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
