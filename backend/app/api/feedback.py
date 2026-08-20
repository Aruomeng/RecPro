"""Opt-in HTTP adapters for append-only impressions, feedback, and behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Path, Response
from pydantic import Field, field_validator, model_validator

from backend.app.api.auth import PrincipalResolver, resolve_user_principal
from backend.app.api.errors import PublicAPIError
from backend.app.api.health import CORRELATION_HEADERS, REQUEST_ID_PARAMETER
from backend.app.api.models import AgentActionResponse, ErrorResponse, StrictModel
from backend.app.feedback.application.public import (
    BehaviorApplicationService,
    BehaviorAppendCommand,
    FeedbackApplicationService,
    FeedbackCommand,
    ImpressionCommand,
    feedback_learning_decision,
)
from backend.app.shared_kernel.contracts.enums import (
    BehaviorEventType,
    FeedbackType,
    NegativeReasonCode,
    ResourceStateType,
)
from backend.app.shared_kernel.contracts.errors import ErrorCode


INTERACTION_HEADERS = {
    **CORRELATION_HEADERS,
    "Idempotency-Replayed": {
        "description": "Whether every item in this request replayed an existing fact.",
        "schema": {"type": "boolean"},
    },
}


DIRECT_BEHAVIOR_TYPES = frozenset(
    {
        BehaviorEventType.SEARCH,
        BehaviorEventType.VIEW_RESOURCE,
        BehaviorEventType.VIEW_EXPLANATION,
        BehaviorEventType.CLICK_RECOMMENDATION,
        BehaviorEventType.ACCESS_PAPER_FULLTEXT,
    }
)


def _feedback_event_type(feedback_type: FeedbackType, rating: float | None) -> str:
    if feedback_type is FeedbackType.FAVORITE:
        return BehaviorEventType.FAVORITE_RESOURCE.value
    if feedback_type is FeedbackType.BORROW:
        return BehaviorEventType.BORROW_BOOK.value
    if feedback_type is FeedbackType.REJECT:
        return BehaviorEventType.REJECT_RECOMMENDATION.value
    if feedback_type is FeedbackType.NOT_INTERESTED:
        return BehaviorEventType.NOT_INTERESTED.value
    if rating is None:
        raise ValueError("RATE feedback requires rating")
    if rating >= 4:
        return BehaviorEventType.RATE_HIGH.value
    if rating <= 2:
        return BehaviorEventType.RATE_LOW.value
    return BehaviorEventType.RATE_NEUTRAL.value


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value


class ImpressionInput(StrictModel):
    impression_uuid: UUID
    recommendation_item_id: int = Field(ge=1)
    position: int = Field(ge=1)
    rendered_at: datetime
    visible_started_at: datetime | None = None
    visible_ms: int = Field(ge=0)
    max_visible_ratio: float = Field(ge=0, le=1)

    @field_validator("rendered_at")
    @classmethod
    def rendered_at_is_aware(cls, value: datetime) -> datetime:
        return _aware(value, "rendered_at")

    @field_validator("visible_started_at")
    @classmethod
    def visible_started_at_is_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value, "visible_started_at") if value is not None else None

    @model_validator(mode="after")
    def visible_start_matches_duration(self) -> "ImpressionInput":
        if self.visible_ms > 0 and self.visible_started_at is None:
            raise ValueError("visible_started_at is required when visible_ms is positive")
        return self


class ImpressionBatchRequest(StrictModel):
    impressions: list[ImpressionInput] = Field(min_length=1, max_length=100)


class ImpressionResult(StrictModel):
    impression_uuid: UUID
    status: Literal["ACCEPTED", "REPLAYED", "REJECTED"]
    is_valid_exposure: bool = False
    error_code: str | None = None
    agent_action: AgentActionResponse | None = None


class ImpressionBatchResponse(StrictModel):
    accepted_count: int = Field(ge=0)
    replayed_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    results: list[ImpressionResult]


class FeedbackRequest(StrictModel):
    feedback_uuid: UUID
    impression_uuid: UUID | None = None
    feedback_type: FeedbackType
    reason_code: NegativeReasonCode | None = None
    rating: float | None = Field(default=None, ge=1, le=5)
    content: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def rating_matches_type(self) -> "FeedbackRequest":
        if self.feedback_type is FeedbackType.RATE and self.rating is None:
            raise ValueError("RATE feedback requires rating")
        if self.feedback_type is not FeedbackType.RATE and self.rating is not None:
            raise ValueError("only RATE feedback accepts rating")
        return self


class ResourceStateResponse(StrictModel):
    state_type: ResourceStateType
    suppress_until: datetime | None = None


class FeedbackReceiptResponse(StrictModel):
    feedback_uuid: UUID
    feedback_id: int = Field(ge=1)
    status: Literal["ACCEPTED", "APPLIED", "REPLAYED"]
    behavior_event_id: int = Field(ge=1)
    resource_state: ResourceStateResponse | None = None
    profile_update_status: Literal["APPLIED", "PENDING", "NOT_REQUIRED"]
    profile_version_before: int | None = Field(default=None, ge=1)
    profile_version_after: int | None = Field(default=None, ge=1)
    agent_action: AgentActionResponse | None = None


class BehaviorEventRequest(StrictModel):
    event_uuid: UUID
    session_id: UUID
    task_id: UUID | None = None
    event_type: BehaviorEventType
    resource_id: int | None = Field(default=None, ge=1)
    recommendation_item_id: int | None = Field(default=None, ge=1)
    impression_uuid: UUID | None = None
    query_text: str | None = Field(default=None, max_length=1000)
    dwell_ms: int | None = Field(default=None, ge=0)
    position: int | None = Field(default=None, ge=1)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_aware(cls, value: datetime) -> datetime:
        return _aware(value, "occurred_at")

    @field_validator("event_type")
    @classmethod
    def event_type_is_client_allowed(cls, value: BehaviorEventType) -> BehaviorEventType:
        return value

    @model_validator(mode="after")
    def references_match_event_type(self) -> "BehaviorEventRequest":
        if self.impression_uuid is not None and self.recommendation_item_id is None:
            raise ValueError("impression_uuid requires recommendation_item_id")
        if self.event_type is BehaviorEventType.SEARCH and not (self.query_text or "").strip():
            raise ValueError("SEARCH requires query_text")
        if self.event_type in {
            BehaviorEventType.CLICK_RECOMMENDATION,
            BehaviorEventType.VIEW_EXPLANATION,
        } and (
            self.recommendation_item_id is None
            or self.impression_uuid is None
            or self.resource_id is None
        ):
            raise ValueError("click and explanation events require resource, item, and impression")
        if self.event_type in {
            BehaviorEventType.VIEW_RESOURCE,
            BehaviorEventType.ACCESS_PAPER_FULLTEXT,
        } and self.resource_id is None:
            raise ValueError("resource events require resource_id")
        return self


class BehaviorEventReceiptResponse(StrictModel):
    event_uuid: UUID
    event_id: int = Field(ge=1)
    status: Literal["ACCEPTED", "APPLIED", "REPLAYED"]
    profile_update_status: Literal["APPLIED", "PENDING", "NOT_REQUIRED"]
    agent_action: AgentActionResponse | None = None


def _api_error_for_value(exc: ValueError) -> PublicAPIError:
    message = str(exc).lower()
    if "impression" in message:
        code = ErrorCode.INVALID_IMPRESSION_REFERENCE
    elif "borrow" in message or "book" in message or "resource type" in message:
        code = ErrorCode.RESOURCE_TYPE_MISMATCH
    elif "reason" in message or "difficulty" in message:
        code = ErrorCode.INVALID_FEEDBACK_REASON
    elif "rating" in message:
        code = ErrorCode.RATING_OUT_OF_RANGE
    else:
        code = ErrorCode.INVALID_JSON
    return PublicAPIError(
        status_code=422,
        code=code,
        message="The interaction payload is invalid.",
        retryable=False,
        details={},
    )


async def _principal(
    *,
    authorization: str | None,
    demo_user_id: int | None,
    app_env: str,
    demo_identity_enabled: bool,
    principal_resolver: PrincipalResolver | None,
):
    return await resolve_user_principal(
        authorization=authorization,
        demo_user_id=demo_user_id,
        app_env=app_env,
        demo_identity_enabled=demo_identity_enabled,
        resolver=principal_resolver,
    )


def _require_enabled(service: object | None, *, pipeline_enabled: bool) -> None:
    if service is None or not pipeline_enabled:
        raise PublicAPIError(
            status_code=503,
            code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
            message="The interaction pipeline is disabled in this runtime.",
            retryable=False,
            details={"feedback_pipeline": "DISABLED"},
        )


def _state_response(state: dict[str, object] | None) -> ResourceStateResponse | None:
    if state is None:
        return None
    suppress_until = state.get("suppress_until")
    if isinstance(suppress_until, datetime) and suppress_until.tzinfo is None:
        suppress_until = suppress_until.replace(tzinfo=UTC)
    return ResourceStateResponse(
        state_type=ResourceStateType(str(state["state_type"])),
        suppress_until=suppress_until,
    )


def create_feedback_router(
    *,
    feedback_service: FeedbackApplicationService | None,
    behavior_service: BehaviorApplicationService | None,
    app_env: str,
    demo_identity_enabled: bool = False,
    pipeline_enabled: bool = False,
    principal_resolver: PrincipalResolver | None = None,
    workspace_broker: Any | None = None,
) -> APIRouter:
    """Build opt-in interaction routes without opening persistence in the adapter."""

    router = APIRouter(prefix="/api/v1", tags=["Interaction"])

    @router.post(
        "/recommendation-impressions/batch",
        response_model=ImpressionBatchResponse,
        responses={
            200: {"model": ImpressionBatchResponse, "headers": INTERACTION_HEADERS},
            401: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            422: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            503: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
        },
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="interaction_append_impressions_v1",
        summary="Append a batch of observed card impressions",
    )
    async def append_impressions(
        request: ImpressionBatchRequest,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
        agent_workspace_id: UUID | None = Header(default=None, alias="X-Agent-Workspace-Id"),
    ) -> ImpressionBatchResponse:
        _require_enabled(feedback_service, pipeline_enabled=pipeline_enabled)
        principal = await _principal(
            authorization=authorization,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
            principal_resolver=principal_resolver,
        )
        if workspace_broker is not None and agent_workspace_id is not None:
            try:
                workspace_broker.snapshot(agent_workspace_id, user_id=principal.user_id)
            except LookupError as exc:
                raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The Agent workspace was not found or has expired.", False, {}) from exc
        accepted = 0
        replayed = 0
        rejected = 0
        results: list[ImpressionResult] = []
        for item in request.impressions:
            try:
                receipt = await feedback_service.record_impression(
                    ImpressionCommand(
                        impression_uuid=item.impression_uuid,
                        recommendation_item_id=item.recommendation_item_id,
                        user_id=principal.user_id,
                        position=item.position,
                        rendered_at=item.rendered_at,
                        visible_started_at=item.visible_started_at,
                        visible_ms=item.visible_ms,
                        max_visible_ratio=item.max_visible_ratio,
                    )
                )
            except LookupError:
                rejected += 1
                results.append(
                    ImpressionResult(
                        impression_uuid=item.impression_uuid,
                        status="REJECTED",
                        error_code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN.value,
                    )
                )
                continue
            except ValueError as exc:
                rejected += 1
                results.append(
                    ImpressionResult(
                        impression_uuid=item.impression_uuid,
                        status="REJECTED",
                        error_code=_api_error_for_value(exc).code.value,
                    )
                )
                continue
            if receipt.replayed:
                replayed += 1
                status: Literal["ACCEPTED", "REPLAYED", "REJECTED"] = "REPLAYED"
            else:
                accepted += 1
                status = "ACCEPTED"
            action = feedback_learning_decision(
                event_type=BehaviorEventType.RECOMMENDATION_IMPRESSION.value,
                replayed=receipt.replayed,
                profile_update_pending=False,
            )
            results.append(
                ImpressionResult(
                    impression_uuid=receipt.impression_uuid,
                    status=status,
                    is_valid_exposure=receipt.is_valid_exposure,
                    agent_action=action,
                )
            )
            if workspace_broker is not None and agent_workspace_id is not None:
                workspace_broker.bridge_feedback_action(agent_workspace_id, user_id=principal.user_id, action=action)
        response.headers["Idempotency-Replayed"] = (
            "true" if replayed == len(results) and not rejected else "false"
        )
        return ImpressionBatchResponse(
            accepted_count=accepted,
            replayed_count=replayed,
            rejected_count=rejected,
            results=results,
        )

    @router.post(
        "/recommendation-items/{item_id}/feedback",
        response_model=FeedbackReceiptResponse,
        responses={
            200: {"model": FeedbackReceiptResponse, "headers": INTERACTION_HEADERS},
            202: {"model": FeedbackReceiptResponse, "headers": INTERACTION_HEADERS},
            401: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            403: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            404: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            409: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            422: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            503: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
        },
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="interaction_append_feedback_v1",
        summary="Append recommendation feedback",
    )
    async def append_feedback(
        request: FeedbackRequest,
        response: Response,
        item_id: int = Path(ge=1),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
        agent_workspace_id: UUID | None = Header(default=None, alias="X-Agent-Workspace-Id"),
    ) -> FeedbackReceiptResponse:
        _require_enabled(feedback_service, pipeline_enabled=pipeline_enabled)
        if idempotency_key != str(request.feedback_uuid):
            raise PublicAPIError(
                status_code=409,
                code=ErrorCode.REQUEST_ID_MISMATCH,
                message="Idempotency-Key must equal feedback_uuid.",
                retryable=False,
                details={},
            )
        principal = await _principal(
            authorization=authorization,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
            principal_resolver=principal_resolver,
        )
        if workspace_broker is not None and agent_workspace_id is not None:
            try:
                workspace_broker.snapshot(agent_workspace_id, user_id=principal.user_id)
            except LookupError as exc:
                raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The Agent workspace was not found or has expired.", False, {}) from exc
        try:
            receipt = await feedback_service.record_feedback(
                FeedbackCommand(
                    feedback_uuid=request.feedback_uuid,
                    recommendation_item_id=item_id,
                    user_id=principal.user_id,
                    feedback_type=request.feedback_type,
                    occurred_at=datetime.now(UTC),
                    impression_uuid=request.impression_uuid,
                    reason_code=request.reason_code,
                    rating=request.rating,
                    content=request.content,
                )
            )
        except LookupError as exc:
            raise PublicAPIError(
                status_code=404,
                code=ErrorCode.NOT_FOUND,
                message="The recommendation item was not found for this user.",
                retryable=False,
                details={},
            ) from exc
        except ValueError as exc:
            raise _api_error_for_value(exc) from exc
        response.status_code = 200 if receipt.replayed else 202
        response.headers["Idempotency-Replayed"] = "true" if receipt.replayed else "false"
        action = feedback_learning_decision(
            event_type=_feedback_event_type(request.feedback_type, request.rating),
            replayed=receipt.replayed,
            profile_update_pending=receipt.outbox_id is not None,
            state_type=(
                str(receipt.resource_state.get("state_type"))
                if receipt.resource_state is not None
                else None
            ),
        )
        result = FeedbackReceiptResponse(
            feedback_uuid=receipt.feedback_uuid,
            feedback_id=receipt.feedback_id,
            status="REPLAYED" if receipt.replayed else "ACCEPTED",
            behavior_event_id=receipt.behavior_event_id,
            resource_state=_state_response(receipt.resource_state),
            profile_update_status="PENDING" if receipt.outbox_id is not None else "NOT_REQUIRED",
            profile_version_before=None,
            profile_version_after=None,
            agent_action=action,
        )
        if workspace_broker is not None and agent_workspace_id is not None:
            workspace_broker.bridge_feedback_action(agent_workspace_id, user_id=principal.user_id, action=action)
        return result

    @router.post(
        "/behavior-events",
        response_model=BehaviorEventReceiptResponse,
        responses={
            200: {"model": BehaviorEventReceiptResponse, "headers": INTERACTION_HEADERS},
            202: {"model": BehaviorEventReceiptResponse, "headers": INTERACTION_HEADERS},
            401: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            403: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            404: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            409: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            422: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
            503: {"model": ErrorResponse, "headers": INTERACTION_HEADERS},
        },
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="interaction_append_behavior_event_v1",
        summary="Append an allowed independent behavior event",
    )
    async def append_behavior_event(
        request: BehaviorEventRequest,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
        agent_workspace_id: UUID | None = Header(default=None, alias="X-Agent-Workspace-Id"),
    ) -> BehaviorEventReceiptResponse:
        _require_enabled(behavior_service, pipeline_enabled=pipeline_enabled)
        if request.event_type not in DIRECT_BEHAVIOR_TYPES:
            raise PublicAPIError(
                status_code=422,
                code=ErrorCode.DERIVED_EVENT_NOT_ALLOWED,
                message="Derived behavior events must use the feedback endpoint.",
                retryable=False,
                details={"event_type": request.event_type.value},
            )
        if idempotency_key != str(request.event_uuid):
            raise PublicAPIError(
                status_code=409,
                code=ErrorCode.REQUEST_ID_MISMATCH,
                message="Idempotency-Key must equal event_uuid.",
                retryable=False,
                details={},
            )
        principal = await _principal(
            authorization=authorization,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
            principal_resolver=principal_resolver,
        )
        if workspace_broker is not None and agent_workspace_id is not None:
            try:
                workspace_broker.snapshot(agent_workspace_id, user_id=principal.user_id)
            except LookupError as exc:
                raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The Agent workspace was not found or has expired.", False, {}) from exc
        try:
            receipt = await behavior_service.append(
                BehaviorAppendCommand(
                    event_uuid=request.event_uuid,
                    user_id=principal.user_id,
                    session_id=request.session_id,
                    task_id=request.task_id,
                    event_type=request.event_type,
                    occurred_at=request.occurred_at,
                    resource_id=request.resource_id,
                    recommendation_item_id=request.recommendation_item_id,
                    impression_uuid=request.impression_uuid,
                    query_text=request.query_text,
                    dwell_ms=request.dwell_ms,
                    position=request.position,
                )
            )
        except LookupError as exc:
            raise PublicAPIError(
                status_code=404,
                code=ErrorCode.NOT_FOUND,
                message="The referenced recommendation item was not found for this user.",
                retryable=False,
                details={},
            ) from exc
        except ValueError as exc:
            raise _api_error_for_value(exc) from exc
        response.status_code = 200 if receipt.replayed else 202
        response.headers["Idempotency-Replayed"] = "true" if receipt.replayed else "false"
        action = feedback_learning_decision(
            event_type=request.event_type.value,
            replayed=receipt.replayed,
            profile_update_pending=receipt.outbox_id is not None,
        )
        result = BehaviorEventReceiptResponse(
            event_uuid=receipt.event_uuid,
            event_id=receipt.event_id,
            status="REPLAYED" if receipt.replayed else "ACCEPTED",
            profile_update_status="PENDING" if receipt.outbox_id is not None else "NOT_REQUIRED",
            agent_action=action,
        )
        if workspace_broker is not None and agent_workspace_id is not None:
            workspace_broker.bridge_feedback_action(agent_workspace_id, user_id=principal.user_id, action=action)
        return result

    return router


__all__ = [
    "BehaviorEventReceiptResponse",
    "BehaviorEventRequest",
    "FeedbackReceiptResponse",
    "FeedbackRequest",
    "ImpressionBatchRequest",
    "ImpressionBatchResponse",
    "ImpressionInput",
    "create_feedback_router",
]
