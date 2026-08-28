"""Ports for bounded, context-versioned Workspace Agent handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkspaceObservation:
    workspace_id: UUID
    user_id: int
    mode: str
    context_version: int
    event_type: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class WorkspaceDirectiveProposal:
    directive_type: str
    scope: str
    behavior: str
    payload: Mapping[str, object]
    reason_code: str
    confidence: float
    evidence_refs: tuple[str, ...]
    reversible: bool


@dataclass(frozen=True, slots=True)
class WorkspaceAgentResult:
    agent_name: str
    action: str
    target: str
    reason_code: str
    confidence: float
    evidence_refs: tuple[str, ...]
    tool_calls: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    directives: tuple[WorkspaceDirectiveProposal, ...] = field(default_factory=tuple)
    outcome: str = "SUCCESS"


@dataclass(frozen=True, slots=True)
class WorkspaceHandlerContext:
    route: str
    query: str
    top_topics: tuple[str, ...]
    external_context: tuple[Mapping[str, object], ...]
    source_statuses: Mapping[str, str]
    personalization_enabled: bool


class WorkspaceAgentHandler(Protocol):
    agent_name: str
    observation_types: frozenset[str]

    async def handle(
        self,
        observation: WorkspaceObservation,
        context: WorkspaceHandlerContext,
    ) -> WorkspaceAgentResult: ...


class WorkspaceReadToolPort(Protocol):
    async def resource(self, resource_id: int) -> Mapping[str, object]: ...

    async def graph_neighbors(self, entity_id: str, *, limit: int) -> Mapping[str, object]: ...


class WorkspaceProfileReadPort(Protocol):
    async def summary(self, user_id: int) -> Mapping[str, object]: ...


__all__ = [
    "WorkspaceAgentHandler",
    "WorkspaceAgentResult",
    "WorkspaceDirectiveProposal",
    "WorkspaceHandlerContext",
    "WorkspaceObservation",
    "WorkspaceReadToolPort",
    "WorkspaceProfileReadPort",
]
