"""Health HTTP routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from backend.app.api.errors import PublicAPIError
from backend.app.api.models import (
    ComponentReadinessResponse,
    ErrorResponse,
    LivenessResponse,
    ReadinessResponse,
)
from backend.app.observability.application.public import (
    ReadinessService,
    ServiceReadinessStatus,
)
from backend.app.shared_kernel.contracts.errors import ErrorCode


REQUEST_ID_PARAMETER = {
    "name": "X-Request-Id",
    "in": "header",
    "required": False,
    "schema": {"type": "string", "format": "uuid"},
    "description": (
        "Optional client-generated request UUID. The server echoes a valid UUID; "
        "when absent or malformed, the server safely generates a replacement."
    ),
}
CORRELATION_HEADERS = {
    "X-Request-Id": {
        "description": "The validated or server-generated request UUID.",
        "schema": {"type": "string", "format": "uuid"},
    },
    "X-Trace-Id": {
        "description": "The trace UUID used to correlate the complete operation.",
        "schema": {"type": "string", "format": "uuid"},
    },
}


def create_health_router(
    *,
    readiness_service: ReadinessService,
    app_version: str,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/health", tags=["Health"])

    @router.get(
        "/live",
        response_model=LivenessResponse,
        responses={
            200: {
                "description": "The API process is alive",
                "headers": CORRELATION_HEADERS,
            }
        },
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER], "security": []},
        operation_id="health_liveness_v1",
        summary="Process liveness",
    )
    async def liveness() -> LivenessResponse:
        return LivenessResponse(
            status="UP",
            service="recpro-backend",
            version=app_version,
            time=datetime.now(timezone.utc),
        )

    @router.get(
        "/ready",
        response_model=ReadinessResponse,
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Component state and truthful recommendation capability",
                "headers": CORRELATION_HEADERS,
            },
            503: {
                "model": ErrorResponse,
                "description": (
                    "Core configuration or MySQL storage is unavailable, so "
                    "recommendation cannot proceed"
                ),
                "headers": CORRELATION_HEADERS,
            },
        },
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER], "security": []},
        operation_id="health_readiness_v1",
        summary="Recommendation capability readiness",
    )
    async def readiness() -> ReadinessResponse:
        assessment = await readiness_service.evaluate()
        if assessment.status is ServiceReadinessStatus.NOT_READY:
            error_code = ErrorCode(
                assessment.failure_error_code
                or ErrorCode.CORE_STORAGE_UNAVAILABLE.value
            )
            raise PublicAPIError(
                status_code=503,
                code=error_code,
                message="A required service dependency is not ready.",
                retryable=error_code is ErrorCode.CORE_STORAGE_UNAVAILABLE,
                details={
                    "component": "configuration"
                    if error_code is ErrorCode.CONFIG_BUNDLE_INVALID
                    else "mysql"
                },
            )
        return ReadinessResponse(
            status=assessment.status,
            can_recommend=assessment.can_recommend,
            components={
                name: ComponentReadinessResponse(
                    status=component.status,
                    required=component.required,
                    active_version=component.active_version,
                    provider=component.provider,
                    error_code=component.error_code,
                )
                for name, component in assessment.components.items()
            },
            config_bundle_version=assessment.config_bundle_version,
            checked_at=datetime.now(timezone.utc),
        )

    return router
