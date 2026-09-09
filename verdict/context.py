"""State passed between stages of a single PR review."""
from dataclasses import dataclass, field


@dataclass
class ReviewContext:
    """Pipeline data only; dependency wiring belongs outside this object."""

    changed_files: list[str] = field(default_factory=list)
    diff: str = ""
    capabilities: list[str] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)
    unsupported_capabilities: list[str] = field(default_factory=list)
    tool_results: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
