"""Trusted mapping from semantic capabilities to existing tool functions.

The ToolRegistry is the security boundary between agent-generated semantic
capability requests and deterministic tool execution.

Agents may request capabilities, but they never select arbitrary Python
functions, shell commands, or executable programs. Only capabilities
explicitly registered here can execute.
"""

from dataclasses import dataclass
from typing import Callable

from . import tools
from .evidence import (
    Evidence,
    bandit_to_evidence,
    docker_base_image_to_evidence,
    python_test_references_to_evidence,
    ruff_to_evidence,
    test_delta_to_evidence,
)


EvidenceAdapter = Callable[[object], list[Evidence]]


@dataclass(frozen=True)
class ToolRegistration:
    capability: str
    tool_name: str
    function: Callable
    argument_style: str
    evidence_adapter: EvidenceAdapter


@dataclass(frozen=True)
class ToolResolution:
    supported: tuple[ToolRegistration, ...]
    unsupported: tuple[str, ...]


@dataclass(frozen=True)
class ToolExecution:
    """Raw trusted tool output and its normalized evidence."""

    raw_results: dict
    evidence: list[Evidence]


class ToolRegistry:
    """Resolve only explicitly registered capabilities; never run commands."""

    def __init__(self):
        self._registrations = {
            "detect_python_security": ToolRegistration(
                "detect_python_security",
                "bandit",
                tools.run_bandit,
                "repo_files",
                bandit_to_evidence,
            ),
            "lint_python": ToolRegistration(
                "lint_python",
                "ruff",
                tools.run_ruff,
                "repo_files",
                ruff_to_evidence,
            ),
            "check_new_python_test_coverage": ToolRegistration(
                "check_new_python_test_coverage",
                "check_test_delta",
                tools.check_test_delta,
                "diff_files",
                test_delta_to_evidence,
            ),
            "check_container_base_image_pinning": ToolRegistration(
                "check_container_base_image_pinning",
                "check_container_base_image_pinning",
                tools.check_container_base_image_pinning,
                "diff_files",
                docker_base_image_to_evidence,
            ),
            "inspect_python_test_references": ToolRegistration(
                "inspect_python_test_references",
                "inspect_python_test_references",
                tools.inspect_python_test_references,
                "repo_files_diff",
                python_test_references_to_evidence,
            ),
        }

        self._scanner_tool_capabilities = {
            "bandit": "detect_python_security",
            "ruff": "lint_python",
            "check_test_delta": "check_new_python_test_coverage",
            "check_container_base_image_pinning": (
                "check_container_base_image_pinning"
            ),
        }

    def resolve(
        self,
        capabilities: list[str],
    ) -> ToolResolution:
        """Separate registered capabilities from unsupported requests."""
        supported = []
        unsupported = []

        for capability in capabilities:
            registration = self._registrations.get(capability)

            if registration is None:
                unsupported.append(capability)
            elif registration not in supported:
                supported.append(registration)

        return ToolResolution(
            tuple(supported),
            tuple(unsupported),
        )

    def resolve_scanner_tools(
        self,
        tool_names: list[str],
    ) -> ToolResolution:
        """Map Scanner's fixed legacy names through trusted registrations."""
        capabilities = [
            self._scanner_tool_capabilities[name]
            for name in tool_names
            if name in self._scanner_tool_capabilities
        ]

        return self.resolve(capabilities)

    def execute(
        self,
        resolution: ToolResolution,
        repo_path: str,
        changed_files: list[str],
        diff_text: str,
    ) -> ToolExecution:
        """Run fixed trusted functions and normalize their registered output."""

        results = {
            "bandit": [],
            "ruff": [],
            "test_delta": {},
        }

        evidence: list[Evidence] = []

        for registration in resolution.supported:
            if registration not in self._registrations.values():
                raise RuntimeError(
                    f"Untrusted tool registration: "
                    f"{registration.capability}"
                )

            if registration.argument_style == "repo_files":
                raw_result = registration.function(
                    repo_path,
                    changed_files,
                )

                results[registration.tool_name] = raw_result

            elif registration.argument_style == "diff_files":
                raw_result = registration.function(
                    diff_text,
                    changed_files,
                )

                result_key = (
                    "test_delta"
                    if registration.tool_name == "check_test_delta"
                    else registration.tool_name
                )

                results[result_key] = raw_result

            elif registration.argument_style == "repo_files_diff":
                raw_result = registration.function(
                    repo_path,
                    changed_files,
                    diff_text,
                )

                results[registration.tool_name] = raw_result

            else:
                raise RuntimeError(
                    f"Unsupported trusted tool registration: "
                    f"{registration.capability}"
                )

            evidence.extend(
                registration.evidence_adapter(raw_result)
            )

        return ToolExecution(
            raw_results=results,
            evidence=evidence,
        )
