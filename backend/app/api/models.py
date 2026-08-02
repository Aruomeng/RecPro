"""Pydantic HTTP DTOs aligned with the frozen G0 OpenAPI contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

from backend.app.observability.application.public import (
    ComponentStatus,
    ServiceReadinessStatus,
)
from backend.app.shared_kernel.contracts.errors import ErrorCode


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LivenessResponse(StrictModel):
    status: Literal["UP"]
    service: Literal["recpro-backend"]
    version: str = Field(min_length=1)
    time: datetime


class ComponentReadinessResponse(StrictModel):
    status: ComponentStatus
    required: bool
    active_version: str | SkipJsonSchema[None] = None
    provider: str | SkipJsonSchema[None] = None
    error_code: str | SkipJsonSchema[None] = None


class ReadinessResponse(StrictModel):
    status: ServiceReadinessStatus
    can_recommend: bool
    components: dict[str, ComponentReadinessResponse] = Field(min_length=1)
    config_bundle_version: str = Field(min_length=1)
    checked_at: datetime


class ErrorBody(StrictModel):
    code: ErrorCode
    message: str = Field(min_length=1)
    details: dict[str, Any]
    retryable: bool


class ErrorResponse(StrictModel):
    error: ErrorBody
    request_id: UUID
    trace_id: UUID
