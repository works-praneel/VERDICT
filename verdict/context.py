"""State passed between stages of a single PR review."""
from dataclasses import dataclass, field
import re


_CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CONCRETE_TOOL_NAMES = frozenset({"bandit", "ruff", "check_test_delta"})


@dataclass(frozen=True)
class InvestigationGoal:
    """A requested fact expressed through a semantic capability ID only."""

    question: str
    required_capability: str
    reason: str

    def __post_init__(self):
        if not all(isinstance(value, str) and value.strip() for value in (self.question, self.reason)):
            raise ValueError("Investigation goal question and reason must be non-empty strings.")
        if (
            not isinstance(self.required_capability, str)
            or not _CAPABILITY_ID_RE.fullmatch(self.required_capability)
            or self.required_capability in _CONCRETE_TOOL_NAMES
        ):
            raise ValueError("Investigation goal requires a semantic capability ID.")


@dataclass
class InvestigationState:
    """Bounded investigation state only; it does not execute investigations."""

    current_round: int = 0
    requested_goals: list[InvestigationGoal] = field(default_factory=list)
    completed_capabilities: set[str] = field(default_factory=set)
    unresolved_goals: list[InvestigationGoal] = field(default_factory=list)

    @property
    def next_round(self) -> int:
        return self.current_round + 1


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
    investigation: InvestigationState = field(default_factory=InvestigationState)
    comments: list[dict] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
