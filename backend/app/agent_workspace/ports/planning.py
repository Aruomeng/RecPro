"""Ports and public value objects for bounded background planning.

The planning port is deliberately smaller than the recommendation LLM port.
It accepts a sanitized, versioned session context and can only return the
existing allow-listed interaction directives.  It does not expose a generic
chat or tool-execution surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Mapping, Protocol, Sequence
from uuid import UUID

from backend.app.agent_workspace.ports.handlers import WorkspaceDirectiveProposal


BACKGROUND_PLANNING_TRIGGERS = frozenset(
    {
        "SESSION_STARTED",
        "READINESS_CHANGED",
        "EXTERNAL_CONTEXT_UPDATED",
        "GRAPH_NODE_SELECTED",
        "RESOURCE_OPENED",
    }
)

BACKGROUND_DIRECTIVE_TYPES = frozenset(
    {
        "SUGGEST_TOPICS",
        "SET_PRIMARY_ENTRY",
        "PREFER_OUTPUT_TYPE",
        "SET_EXPLANATION_DENSITY",
        "SHOW_GUIDANCE",
        "SHOW_DEGRADED_NOTICE",
        "SUGGEST_NEXT_ACTION",
    }
)


@dataclass(frozen=True, slots=True)
class PlanningContext:
    """The internal context captured at one observation boundary."""

    workspace_id: UUID
    session_id: UUID
    device_id: str
    mode: Literal["guest", "demo", "authenticated"]
    context_version: int
    trigger: str
    route: str
    query: str
    top_topics: tuple[str, ...] = field(default_factory=tuple)
    source_statuses: Mapping[str, str] = field(default_factory=dict)
    external_context: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    personalization_enabled: bool = False
    profile_summary: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.context_version < 1:
            raise ValueError("planning context version must be positive")
        if self.trigger not in BACKGROUND_PLANNING_TRIGGERS:
            raise ValueError("planning trigger is not allow-listed")
        if not self.device_id.strip() or len(self.device_id) > 128:
            raise ValueError("planning device id is invalid")
        if not self.route.startswith("/") or len(self.route) > 128:
            raise ValueError("planning route is invalid")
        if len(self.query) > 4000:
            raise ValueError("planning query is too large")
        if not isinstance(self.personalization_enabled, bool):
            raise ValueError("planning personalization flag must be boolean")
        if self.profile_summary is not None and not self.personalization_enabled:
            raise ValueError("profile summary requires explicit personalization consent")


@dataclass(frozen=True, slots=True)
class SanitizedPlanningContext:
    """Safe model-facing context with no account or raw credential fields."""

    mode: Literal["guest", "demo", "authenticated"]
    context_version: int
    trigger: str
    route: str
    query: str
    top_topics: tuple[str, ...]
    source_statuses: Mapping[str, str]
    external_context: tuple[Mapping[str, object], ...]
    profile_summary: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class BackgroundPlanningResult:
    """Bounded planner output before it is applied to the Workspace."""

    directives: tuple[WorkspaceDirectiveProposal, ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    provider: str = "rule"
    model: str = "background-rule-v1"
    model_requests: int = 0


@dataclass(frozen=True, slots=True)
class PlanningBudgetSnapshot:
    session_calls: int
    session_limit: int
    device_calls_today: int
    device_limit_today: int
    last_call_at: datetime | None
    next_allowed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PlanningReservation:
    allowed: bool
    reason_code: str
    snapshot: PlanningBudgetSnapshot


@dataclass(frozen=True, slots=True)
class BackgroundPlanningOutcome:
    status: Literal["PLANNED", "SKIPPED", "DEGRADED", "FAILED"]
    reason_code: str
    decision_id: UUID | None
    context_version: int
    directives: tuple[WorkspaceDirectiveProposal, ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    provider: str = "none"
    model: str = "none"
    model_requests: int = 0
    budget: PlanningBudgetSnapshot | None = None


class BackgroundPlanningPort(Protocol):
    """A planner that cannot perform persistence or arbitrary tool calls."""

    async def plan(self, context: SanitizedPlanningContext) -> BackgroundPlanningResult: ...


class PlanningBudgetPort(Protocol):
    """Reserve a bounded model-attempt budget before dispatch."""

    def reserve(
        self,
        *,
        session_id: UUID,
        device_id: str,
        now: datetime,
    ) -> PlanningReservation: ...


__all__ = [
    "BACKGROUND_DIRECTIVE_TYPES",
    "BACKGROUND_PLANNING_TRIGGERS",
    "BackgroundPlanningOutcome",
    "BackgroundPlanningPort",
    "BackgroundPlanningResult",
    "PlanningBudgetPort",
    "PlanningBudgetSnapshot",
    "PlanningContext",
    "PlanningReservation",
    "SanitizedPlanningContext",
]
