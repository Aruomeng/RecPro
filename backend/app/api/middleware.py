"""Request correlation and structured access logging middleware."""

from __future__ import annotations

from time import monotonic
from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from backend.app.logging import get_logger


logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        clear_contextvars()
        trace_id = uuid4()
        raw_request_id = request.headers.get("X-Request-Id")
        try:
            request_id = UUID(raw_request_id) if raw_request_id else uuid4()
        except ValueError:
            request_id = uuid4()

        request.state.request_id = request_id
        request.state.trace_id = trace_id
        bind_contextvars(request_id=str(request_id), trace_id=str(trace_id))
        started = monotonic()
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = str(request_id)
            response.headers["X-Trace-Id"] = str(trace_id)
            logger.info(
                "http_request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((monotonic() - started) * 1000, 3),
            )
            return response
        finally:
            clear_contextvars()
