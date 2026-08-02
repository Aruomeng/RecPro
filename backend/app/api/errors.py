"""Uniform public error mapping with sanitized details."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.models import ErrorBody, ErrorResponse
from backend.app.logging import get_logger
from backend.app.shared_kernel.contracts.errors import ErrorCode


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PublicAPIError(Exception):
    status_code: int
    code: ErrorCode
    message: str
    retryable: bool
    details: dict[str, Any] = field(default_factory=dict)


def _correlation_ids(request: Request) -> tuple[UUID, UUID]:
    request_id = getattr(request.state, "request_id", uuid4())
    trace_id = getattr(request.state, "trace_id", uuid4())
    return request_id, trace_id


def error_response(
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    retryable: bool,
    request_id: UUID,
    trace_id: UUID,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or {},
            retryable=retryable,
        ),
        request_id=request_id,
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={
            "X-Request-Id": str(request_id),
            "X-Trace-Id": str(trace_id),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(PublicAPIError)
    async def handle_public_error(request: Request, exc: PublicAPIError) -> JSONResponse:
        request_id, trace_id = _correlation_ids(request)
        return error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
            request_id=request_id,
            trace_id=trace_id,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id, trace_id = _correlation_ids(request)
        return error_response(
            status_code=422,
            code=ErrorCode.INVALID_JSON,
            message="Request validation failed.",
            retryable=False,
            details={"issue_count": len(exc.errors())},
            request_id=request_id,
            trace_id=trace_id,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        request_id, trace_id = _correlation_ids(request)
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INVALID_JSON
        return error_response(
            status_code=exc.status_code,
            code=code,
            message="The requested endpoint was not found."
            if exc.status_code == 404
            else "The request could not be processed.",
            retryable=False,
            request_id=request_id,
            trace_id=trace_id,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id, trace_id = _correlation_ids(request)
        logger.error("unhandled_request_error", error_type=type(exc).__name__)
        return error_response(
            status_code=503,
            code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
            message="The service is temporarily unavailable.",
            retryable=True,
            request_id=request_id,
            trace_id=trace_id,
        )
