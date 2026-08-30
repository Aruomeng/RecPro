"""Asynchronous recommendation runs with truthful, bounded SSE progress."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from typing import Any, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import Field

from backend.app.agent_workspace.application.public import WorkspaceNotFoundError
from backend.app.api.auth import PrincipalResolver
from backend.app.api.errors import PublicAPIError
from backend.app.api.health import CORRELATION_HEADERS, REQUEST_ID_PARAMETER
from backend.app.api.models import ErrorResponse, StrictModel
from backend.app.api.recommendation import (
    ClarificationRequest,
    RecommendationExecutionResponse,
    RecommendationTaskCreateRequest,
    _project_public_warnings,
    _require_recommendation_access,
    _resolve_principal,
    _validate_request_shape,
    build_recommendation_command,
)
from backend.app.recommendation.application.public import (
    RecommendationProgressBrokerPort,
    RunCapacityError,
    RunContextConflictError,
    RunIdempotencyConflictError,
    RunNotFoundError,
    derive_task_identity_values,
)
from backend.app.shared_kernel.contracts.errors import ErrorCode


class RecommendationRunAccepted(StrictModel):
    task_id: UUID
    trace_id: UUID
    context_version: int = Field(ge=1)
    status: str
    events_url: str
    replayed: bool


class RecommendationRunState(StrictModel):
    task_id: UUID
    trace_id: UUID
    context_version: int = Field(ge=1)
    status: str
    terminal: bool
    error_code: str | None = None
    result: RecommendationExecutionResponse | None = None


def _public_result(payload: dict[str, Any]) -> dict[str, Any]:
    return RecommendationExecutionResponse.model_validate(
        _project_public_warnings(payload)
    ).model_dump(mode="json", exclude_none=True)


def _capacity_error(exc: Exception) -> PublicAPIError:
    return PublicAPIError(
        429,
        ErrorCode.REQUEST_DEADLINE_EXCEEDED,
        "The research runtime has reached its bounded concurrent run limit.",
        True,
        {"max_concurrent_runs": 8, "error_type": type(exc).__name__},
    )


def _fingerprint(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _run_conflict(exc: Exception) -> PublicAPIError:
    return PublicAPIError(409, ErrorCode.IDEMPOTENCY_KEY_REUSED, "The run identity was reused with different content or context.", False, {"error_type": type(exc).__name__})


def create_recommendation_run_router(
    *,
    service: Any,
    broker: RecommendationProgressBrokerPort,
    app_env: str,
    demo_identity_enabled: bool,
    pipeline_enabled: bool,
    principal_resolver: PrincipalResolver | None,
    workspace_broker: Any | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/recommendation-runs", tags=["Recommendation Runs"])
    errors = {
        code: {"model": ErrorResponse, "headers": CORRELATION_HEADERS}
        for code in (401, 403, 404, 409, 422, 429, 503, 504)
    }

    async def principal(demo_user_id: int | None, authorization: str | None):
        actor = await _resolve_principal(
            request_user_id=None,
            authorization=authorization,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
            principal_resolver=principal_resolver,
        )
        _require_recommendation_access(actor, formal_auth=authorization is not None)
        return actor

    async def execute(command: RecommendationTaskCommand, idempotency_key: str, sink: Any, workspace_id: UUID | None, user_id: int) -> None:
        task_id, trace_id = derive_task_identity_values(command)
        try:
            result = await service.create_task(command, idempotency_key=idempotency_key, progress_sink=sink)
            broker.complete(task_id, result=_public_result(dict(result.payload)), replayed=result.replayed)
            if workspace_broker is not None and workspace_id is not None:
                if result.replayed:
                    workspace_broker.bridge_historical_actions(
                        workspace_id,
                        user_id=user_id,
                        task_id=task_id,
                        actions=result.payload.get("agent_actions", []),
                    )
                workspace_broker.bridge_task_terminal(workspace_id, user_id=user_id, status=str(result.payload.get("status", "COMPLETED")), task_id=task_id, trace_id=trace_id)
        except Exception as exc:
            code = "REQUEST_DEADLINE_EXCEEDED" if isinstance(exc, TimeoutError) else "CORE_STORAGE_UNAVAILABLE"
            broker.fail(task_id, error_code=code)
            if workspace_broker is not None and workspace_id is not None:
                workspace_broker.bridge_task_terminal(workspace_id, user_id=user_id, status="FAILED", task_id=task_id, trace_id=trace_id)

    @router.post(
        "",
        response_model=RecommendationRunAccepted,
        status_code=202,
        responses=errors,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="recommendation_create_run_v1",
    )
    async def create_run(
        request: RecommendationTaskCreateRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
        agent_workspace_id: UUID | None = Header(default=None, alias="X-Agent-Workspace-Id"),
    ) -> RecommendationRunAccepted:
        if not pipeline_enabled:
            raise PublicAPIError(503, ErrorCode.CORE_STORAGE_UNAVAILABLE, "The recommendation pipeline is disabled.", False, {})
        if idempotency_key != str(request.request_id):
            raise PublicAPIError(409, ErrorCode.REQUEST_ID_MISMATCH, "Idempotency-Key must equal request_id.", False, {})
        _validate_request_shape(request)
        actor = await principal(demo_user_id, authorization)
        command = build_recommendation_command(
            request,
            principal=actor,
            app_env=app_env,
        )
        task_id, trace_id = derive_task_identity_values(command)
        if workspace_broker is not None and agent_workspace_id is not None:
            try:
                workspace_broker.snapshot(agent_workspace_id, user_id=actor.user_id)
            except WorkspaceNotFoundError as exc:
                raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The Agent workspace was not found or has expired.", False, {}) from exc
        try:
            sink, replayed = broker.reserve(
                task_id=task_id, trace_id=trace_id, context_version=1, user_id=actor.user_id,
                request_fingerprint=_fingerprint({"user_id": actor.user_id, "request": request.model_dump(mode="json")}),
            )
        except RunCapacityError as exc:
            raise _capacity_error(exc) from exc
        except (RunContextConflictError, RunIdempotencyConflictError) as exc:
            raise _run_conflict(exc) from exc
        if workspace_broker is not None and agent_workspace_id is not None:
            sink = workspace_broker.mirror_sink(sink, agent_workspace_id, user_id=actor.user_id)
            workspace_broker.bridge_recommendation_event(agent_workspace_id, user_id=actor.user_id, event_type="STATE_CHANGED", payload={"status": "ACCEPTED", "task_id": str(task_id), "trace_id": str(trace_id)})
        if not replayed:
            task = asyncio.create_task(execute(command, idempotency_key, sink, agent_workspace_id, actor.user_id), name=f"recommendation-run:{task_id}")
            broker.attach_task(task_id, task)
        return RecommendationRunAccepted(
            task_id=task_id,
            trace_id=trace_id,
            context_version=1,
            status="ACCEPTED",
            events_url=f"/api/v1/recommendation-runs/{task_id}/events?context_version=1",
            replayed=replayed,
        )

    async def execute_clarification(
        *, task_id: UUID, request: ClarificationRequest, idempotency_key: str, user_id: int, sink: Any, workspace_id: UUID | None
    ) -> None:
        try:
            result = await service.submit_clarification(
                task_id,
                context_version=request.context_version,
                answers=dict(request.answers),
                idempotency_key=idempotency_key,
                user_id=user_id,
                progress_sink=sink,
            )
            broker.complete(task_id, result=_public_result(dict(result.payload)), replayed=result.replayed)
            if workspace_broker is not None and workspace_id is not None:
                if result.replayed:
                    workspace_broker.bridge_historical_actions(
                        workspace_id,
                        user_id=user_id,
                        task_id=task_id,
                        actions=result.payload.get("agent_actions", []),
                    )
                workspace_broker.bridge_task_terminal(workspace_id, user_id=user_id, status=str(result.payload.get("status", "COMPLETED")), task_id=task_id)
        except Exception as exc:
            code = "REQUEST_DEADLINE_EXCEEDED" if isinstance(exc, TimeoutError) else "CORE_STORAGE_UNAVAILABLE"
            broker.fail(task_id, error_code=code)
            if workspace_broker is not None and workspace_id is not None:
                workspace_broker.bridge_task_terminal(workspace_id, user_id=user_id, status="FAILED", task_id=task_id)

    @router.post(
        "/{task_id}/clarifications",
        response_model=RecommendationRunAccepted,
        status_code=202,
        responses=errors,
        operation_id="recommendation_run_clarification_v1",
    )
    async def clarify_run(
        task_id: UUID,
        request: ClarificationRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
        agent_workspace_id: UUID | None = Header(default=None, alias="X-Agent-Workspace-Id"),
    ) -> RecommendationRunAccepted:
        actor = await principal(demo_user_id, authorization)
        try:
            task_state = await service.get_task(task_id, user_id=actor.user_id)
        except LookupError as exc:
            raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The recommendation task was not found.", False, {}) from exc
        trace_id = UUID(str(task_state["trace_id"]))
        next_context = request.context_version + 1
        if workspace_broker is not None and agent_workspace_id is not None:
            try:
                workspace_broker.snapshot(agent_workspace_id, user_id=actor.user_id)
            except WorkspaceNotFoundError as exc:
                raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The Agent workspace was not found or has expired.", False, {}) from exc
        try:
            sink, replayed = broker.reserve(
                task_id=task_id, trace_id=trace_id, context_version=next_context, user_id=actor.user_id,
                request_fingerprint=_fingerprint({"user_id": actor.user_id, "idempotency_key": idempotency_key, "request": request.model_dump(mode="json")}),
            )
        except RunCapacityError as exc:
            raise _capacity_error(exc) from exc
        except (RunContextConflictError, RunIdempotencyConflictError) as exc:
            raise _run_conflict(exc) from exc
        if workspace_broker is not None and agent_workspace_id is not None:
            sink = workspace_broker.mirror_sink(sink, agent_workspace_id, user_id=actor.user_id)
        if not replayed:
            task = asyncio.create_task(
                execute_clarification(task_id=task_id, request=request, idempotency_key=idempotency_key, user_id=actor.user_id, sink=sink, workspace_id=agent_workspace_id),
                name=f"recommendation-clarification:{task_id}:{next_context}",
            )
            broker.attach_task(task_id, task)
        return RecommendationRunAccepted(
            task_id=task_id, trace_id=trace_id, context_version=next_context, status="ACCEPTED",
            events_url=f"/api/v1/recommendation-runs/{task_id}/events?context_version={next_context}", replayed=replayed,
        )

    @router.get("/{task_id}", response_model=RecommendationRunState, responses=errors, operation_id="recommendation_get_run_v1")
    async def get_run(
        task_id: UUID,
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> RecommendationRunState:
        actor = await principal(demo_user_id, authorization)
        try:
            return RecommendationRunState.model_validate(broker.state(task_id, user_id=actor.user_id))
        except RunNotFoundError as exc:
            raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The recommendation run was not found or has expired.", False, {}) from exc

    @router.get("/{task_id}/events", responses=errors, operation_id="recommendation_stream_run_events_v1")
    async def stream_events(
        task_id: UUID,
        context_version: int = Query(ge=1),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> StreamingResponse:
        actor = await principal(demo_user_id, authorization)
        try:
            state = broker.state(task_id, user_id=actor.user_id)
        except RunNotFoundError as exc:
            raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The recommendation run was not found or has expired.", False, {}) from exc
        if int(state["context_version"]) != context_version:
            raise PublicAPIError(409, ErrorCode.STALE_CONTEXT_VERSION, "The requested event context is stale.", False, {})
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

        async def body() -> AsyncIterator[str]:
            async for event in broker.events(task_id, user_id=actor.user_id, after_sequence=after):
                if event is None:
                    yield ": heartbeat\n\n"
                    continue
                yield f"id: {event['sequence']}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"

        return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router


__all__ = ["RecommendationRunAccepted", "RecommendationRunState", "create_recommendation_run_router"]
