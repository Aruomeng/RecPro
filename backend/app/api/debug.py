"""Opt-in research-admin Debug HTTP adapter.

The router is not mounted by default.  When mounted, every request still needs
an injected bearer-token resolver and the verified ``research_admin`` role.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Header

from backend.app.api.auth import (
    PrincipalResolver,
    reject_demo_identity_for_debug,
    require_bearer_principal,
)
from backend.app.api.errors import PublicAPIError
from backend.app.api.health import CORRELATION_HEADERS, REQUEST_ID_PARAMETER
from backend.app.api.models import ErrorResponse, StrictModel
from backend.app.recommendation.application.public import RecommendationTaskService
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal
from backend.app.shared_kernel.contracts.errors import ErrorCode


class DebugDocument(StrictModel):
    task_id: UUID
    schema_version: str
    payload: dict[str, Any]


async def _require_research_admin(
    *,
    authorization: str | None,
    demo_user_id: int | None,
    principal_resolver: PrincipalResolver | None,
) -> AuthenticatedPrincipal:
    reject_demo_identity_for_debug(demo_user_id)
    principal = await require_bearer_principal(
        authorization,
        resolver=principal_resolver,
    )
    if not principal.has_role("research_admin"):
        raise PublicAPIError(
            status_code=403,
            code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
            message="The research-admin role is required for Debug API access.",
            retryable=False,
            details={},
        )
    return principal


def create_debug_router(
    *,
    service: RecommendationTaskService,
    principal_resolver: PrincipalResolver | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/debug", tags=["Debug"])

    async def read_document(
        *,
        task_id: UUID,
        authorization: str | None,
        demo_user_id: int | None,
        getter: Callable[..., Awaitable[dict[str, Any]]],
    ) -> DebugDocument:
        principal = await _require_research_admin(
            authorization=authorization,
            demo_user_id=demo_user_id,
            principal_resolver=principal_resolver,
        )
        try:
            payload = await getter(task_id, actor=principal)
        except LookupError as exc:
            raise PublicAPIError(
                status_code=404,
                code=ErrorCode.NOT_FOUND,
                message="The requested recommendation task was not found.",
                retryable=False,
                details={},
            ) from exc
        except PermissionError as exc:
            raise PublicAPIError(
                status_code=403,
                code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
                message="The research-admin role is required for Debug API access.",
                retryable=False,
                details={},
            ) from exc
        except (AttributeError, NotImplementedError) as exc:
            raise PublicAPIError(
                status_code=503,
                code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
                message="Debug data is not available in this runtime.",
                retryable=True,
                details={"debug": "UNAVAILABLE"},
            ) from exc
        return DebugDocument.model_validate(payload)

    response_config = {
        200: {"model": DebugDocument, "headers": CORRELATION_HEADERS},
        401: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        403: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        404: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        422: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        429: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        503: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        504: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
    }

    @router.get(
        "/tasks/{task_id}/context",
        response_model=DebugDocument,
        responses=response_config,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="debug_get_task_context_v1",
        summary="Read the versioned task context for research audit",
    )
    async def get_context(
        task_id: UUID,
        authorization: str | None = Header(default=None, alias="Authorization"),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
    ) -> DebugDocument:
        getter = getattr(service, "get_debug_context", None)
        if getter is None:
            raise PublicAPIError(
                status_code=503,
                code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
                message="Debug data is not available in this runtime.",
                retryable=True,
                details={"debug": "UNAVAILABLE"},
            )
        return await read_document(
            task_id=task_id,
            authorization=authorization,
            demo_user_id=demo_user_id,
            getter=getter,
        )

    @router.get(
        "/tasks/{task_id}/trace",
        response_model=DebugDocument,
        responses=response_config,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="debug_get_task_trace_v1",
        summary="Read the ordered Agent trace for research audit",
    )
    async def get_trace(
        task_id: UUID,
        authorization: str | None = Header(default=None, alias="Authorization"),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
    ) -> DebugDocument:
        async def getter(
            task: UUID, *, actor: AuthenticatedPrincipal
        ) -> dict[str, Any]:
            # The application port keeps owner and research-admin trace reads
            # separate.  This adapter intentionally never supplies a demo user.
            return await service.get_debug_trace(task, actor=actor)

        if not hasattr(service, "get_debug_trace"):
            raise PublicAPIError(
                status_code=503,
                code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
                message="Debug trace is not available in this runtime.",
                retryable=True,
                details={"debug": "TRACE_UNAVAILABLE"},
            )
        return await read_document(
            task_id=task_id,
            authorization=authorization,
            demo_user_id=demo_user_id,
            getter=getter,
        )

    @router.get(
        "/tasks/{task_id}/policy-decision",
        response_model=DebugDocument,
        responses=response_config,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="debug_get_policy_decision_v1",
        summary="Read policy inputs and decision for research audit",
    )
    async def get_policy_decision(
        task_id: UUID,
        authorization: str | None = Header(default=None, alias="Authorization"),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
    ) -> DebugDocument:
        getter = getattr(service, "get_debug_policy_decision", None)
        if getter is None:
            raise PublicAPIError(
                status_code=503,
                code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
                message="Debug policy data is not available in this runtime.",
                retryable=True,
                details={"debug": "POLICY_UNAVAILABLE"},
            )
        return await read_document(
            task_id=task_id,
            authorization=authorization,
            demo_user_id=demo_user_id,
            getter=getter,
        )

    return router


__all__ = ["DebugDocument", "create_debug_router"]
