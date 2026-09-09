"""Trusted mapping from semantic capabilities to existing tool functions."""
from dataclasses import dataclass
from typing import Callable

from . import tools


@dataclass(frozen=True)
class ToolRegistration:
    capability: str
    tool_name: str
    function: Callable
    argument_style: str


@dataclass(frozen=True)
class ToolResolution:
    supported: tuple[ToolRegistration, ...]
    unsupported: tuple[str, ...]


class ToolRegistry:
    """Resolve only explicitly registered capabilities; never run commands."""

    def __init__(self):
        self._registrations = {
            "detect_python_security": ToolRegistration(
                "detect_python_security", "bandit", tools.run_bandit, "repo_files"
            ),
            "lint_python": ToolRegistration(
                "lint_python", "ruff", tools.run_ruff, "repo_files"
            ),
            "check_new_python_test_coverage": ToolRegistration(
                "check_new_python_test_coverage",
                "check_test_delta",
                tools.check_test_delta,
                "diff_files",
            ),
        }

    def resolve(self, capabilities: list[str]) -> ToolResolution:
        """Separate registered capabilities from unsupported requests."""
        supported = []
        unsupported = []
        for capability in capabilities:
            registration = self._registrations.get(capability)
            if registration is None:
                unsupported.append(capability)
            elif registration not in supported:
                supported.append(registration)
        return ToolResolution(tuple(supported), tuple(unsupported))

    def execute(
        self, resolution: ToolResolution, repo_path: str, changed_files: list[str], diff_text: str
    ) -> dict:
        """Run resolved trusted functions with fixed, capability-specific arguments."""
        results = {"bandit": [], "ruff": [], "test_delta": {}}
        for registration in resolution.supported:
            if registration not in self._registrations.values():
                raise RuntimeError(f"Untrusted tool registration: {registration.capability}")
            if registration.argument_style == "repo_files":
                results[registration.tool_name] = registration.function(repo_path, changed_files)
            elif registration.argument_style == "diff_files":
                results["test_delta"] = registration.function(diff_text, changed_files)
            else:  # Defensive: registrations are internal and must declare a known calling convention.
                raise RuntimeError(f"Unsupported trusted tool registration: {registration.capability}")
        return results
