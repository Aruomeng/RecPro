"""HTTP boundary for the session-scoped global Agent workspace."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Literal
from uuid import UUID

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import Field

from backend.app.agent_workspace.application.public import (
    AgentWorkspaceBroker,
    WorkspaceCapacityError,
    WorkspaceNotFoundError,
    agent_catalog,
)
from backend.app.api.auth import PrincipalResolver, resolve_user_principal
from backend.app.api.errors import PublicAPIError
from backend.app.api.models import ErrorResponse, StrictModel
from backend.app.shared_kernel.contracts.errors import ErrorCode


ObservationType = Literal[
    "SESSION_STARTED", "ROUTE_CHANGED", "QUERY_SUBMITTED", "GRAPH_NODE_SELECTED",
    "RESOURCE_OPENED", "RECOMMENDATION_STARTED", "RECOMMENDATION_COMPLETED",
    "FEEDBACK_RECORDED", "READINESS_CHANGED", "EXTERNAL_CONTEXT_UPDATED",
]


class WorkspaceCreateRequest(StrictModel):
    session_id: UUID
    mode: Literal["guest", "demo"]


class WorkspaceSnapshotResponse(StrictModel):
    schema_version: Literal["agent-workspace-v1"]
    workspace_id: UUID
    session_id: UUID
    mode: Literal["guest", "demo"]
    context_version: int = Field(ge=1)
    orchestrator: dict[str, Any]
    agents: list[dict[str, Any]] = Field(min_length=8, max_length=8)
    directives: list[dict[str, Any]]
    recent_events: list[dict[str, Any]] = Field(max_length=40)
    sources: list[dict[str, Any]]
    context_summary: dict[str, Any]


class WorkspaceCreatedResponse(StrictModel):
    workspace: WorkspaceSnapshotResponse
    events_url: str
    replayed: bool


class WorkspaceObservationRequest(StrictModel):
    observation_id: UUID
    event_type: ObservationType
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkspaceObservationResponse(StrictModel):
    workspace: WorkspaceSnapshotResponse
    replayed: bool


class DirectiveActionRequest(StrictModel):
    action: Literal["ACCEPT", "DISMISS", "UNDO"]


class DirectiveActionResponse(StrictModel):
    directive: dict[str, Any]


class AgentCatalogResponse(StrictModel):
    schema_version: Literal["agent-catalog-v1"] = "agent-catalog-v1"
    agents: list[dict[str, Any]] = Field(min_length=8, max_length=8)


def _not_found(exc: Exception) -> PublicAPIError:
    return PublicAPIError(404, ErrorCode.NOT_FOUND, "The Agent workspace was not found or has expired.", False, {"error_type": type(exc).__name__})


def create_agent_workspace_router(
    *,
    broker: AgentWorkspaceBroker,
    app_env: str,
    demo_identity_enabled: bool,
    principal_resolver: PrincipalResolver | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Agent Workspace"])
    errors = {code: {"model": ErrorResponse} for code in (401, 404, 409, 422, 429, 503)}

    async def principal(demo_user_id: int | None, authorization: str | None):
        return await resolve_user_principal(
            authorization=authorization,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
            resolver=principal_resolver,
        )

    @router.get("/agents", response_model=AgentCatalogResponse, operation_id="agent_catalog_v1")
    async def agents() -> AgentCatalogResponse:
        return AgentCatalogResponse(agents=agent_catalog())

    @router.post("/agent-workspaces", response_model=WorkspaceCreatedResponse, status_code=202, responses=errors, operation_id="agent_workspace_create_v1")
    async def create_workspace(
        request: WorkspaceCreateRequest,
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> WorkspaceCreatedResponse:
        actor = await principal(demo_user_id, authorization)
        try:
            snapshot, replayed = broker.create(session_id=request.session_id, user_id=actor.user_id, mode=request.mode)
        except WorkspaceCapacityError as exc:
            raise PublicAPIError(429, ErrorCode.REQUEST_DEADLINE_EXCEEDED, "The bounded Agent workspace capacity has been reached.", True, {"max_workspaces": 32}) from exc
        workspace_id = str(snapshot["workspace_id"])
        return WorkspaceCreatedResponse(
            workspace=WorkspaceSnapshotResponse.model_validate(snapshot),
            events_url=f"/api/v1/agent-workspaces/{workspace_id}/events",
            replayed=replayed,
        )

    @router.get("/agent-workspaces/{workspace_id}", response_model=WorkspaceSnapshotResponse, responses=errors, operation_id="agent_workspace_get_v1")
    async def get_workspace(
        workspace_id: UUID,
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> WorkspaceSnapshotResponse:
        actor = await principal(demo_user_id, authorization)
        try:
            return WorkspaceSnapshotResponse.model_validate(broker.snapshot(workspace_id, user_id=actor.user_id))
        except WorkspaceNotFoundError as exc:
            raise _not_found(exc) from exc

    @router.post("/agent-workspaces/{workspace_id}/observations", response_model=WorkspaceObservationResponse, status_code=202, responses=errors, operation_id="agent_workspace_observe_v1")
    async def observe_workspace(
        workspace_id: UUID,
        request: WorkspaceObservationRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> WorkspaceObservationResponse:
        if idempotency_key != str(request.observation_id):
            raise PublicAPIError(409, ErrorCode.REQUEST_ID_MISMATCH, "Idempotency-Key must equal observation_id.", False, {})
        actor = await principal(demo_user_id, authorization)
        try:
            snapshot, replayed = broker.observe(
                workspace_id, user_id=actor.user_id, event_type=request.event_type,
                idempotency_key=idempotency_key, payload=request.payload,
            )
        except WorkspaceNotFoundError as exc:
            raise _not_found(exc) from exc
        except ValueError as exc:
            raise PublicAPIError(422, ErrorCode.INVALID_JSON, "The public workspace observation is invalid.", False, {"error_type": type(exc).__name__}) from exc
        return WorkspaceObservationResponse(workspace=WorkspaceSnapshotResponse.model_validate(snapshot), replayed=replayed)

    @router.post("/agent-workspaces/{workspace_id}/directives/{directive_id}/actions", response_model=DirectiveActionResponse, responses=errors, operation_id="agent_workspace_directive_action_v1")
    async def action_directive(
        workspace_id: UUID,
        directive_id: UUID,
        request: DirectiveActionRequest,
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> DirectiveActionResponse:
        actor = await principal(demo_user_id, authorization)
        try:
            return DirectiveActionResponse(directive=broker.directive_action(workspace_id, user_id=actor.user_id, directive_id=directive_id, action=request.action))
        except WorkspaceNotFoundError as exc:
            raise _not_found(exc) from exc

    @router.get("/agent-workspaces/{workspace_id}/events", responses=errors, operation_id="agent_workspace_stream_events_v1")
    async def stream_workspace(
        workspace_id: UUID,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> StreamingResponse:
        actor = await principal(demo_user_id, authorization)
        try:
            broker.snapshot(workspace_id, user_id=actor.user_id)
        except WorkspaceNotFoundError as exc:
            raise _not_found(exc) from exc
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

        async def body() -> AsyncIterator[str]:
            async for event in broker.events(workspace_id, user_id=actor.user_id, after_sequence=after):
                if event is None:
                    yield ": heartbeat\n\n"
                else:
                    yield f"id: {event['sequence']}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"

        return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router


__all__ = ["create_agent_workspace_router"]
