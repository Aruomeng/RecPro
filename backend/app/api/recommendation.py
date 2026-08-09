"""HTTP adapter for the first recommendation task vertical slice.

The adapter owns validation, demo identity and idempotency headers.  It never
opens a database connection and delegates persistence to the application port.
The router is opt-in from the composition root so the default G1 runtime keeps
the recommendation surface disabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Response
from pydantic import Field, field_validator

from backend.app.api.errors import PublicAPIError
from backend.app.api.health import CORRELATION_HEADERS, REQUEST_ID_PARAMETER
from backend.app.api.models import ErrorResponse, StrictModel
from backend.app.recommendation.application.public import (
    RecommendationTaskCommand,
    RecommendationTaskService,
)
from backend.app.shared_kernel.contracts.enums import (
    AdaptationState,
    AvailabilityStatus,
    DeliveryStrategy,
    ExplanationLevel,
    OutputType,
    ResourceType,
    TaskStatus,
    TriggerScene,
)
from backend.app.shared_kernel.contracts.errors import ErrorCode, WarningCode


IDEMPOTENCY_HEADERS = {
    **CORRELATION_HEADERS,
    "Idempotency-Replayed": {
        "description": "Whether the response replays a previously persisted task.",
        "schema": {"type": "boolean"},
    },
}


class RecommendationTaskCreateRequest(StrictModel):
    request_id: UUID
    user_id: int | None = Field(default=None, ge=1)
    session_id: UUID
    scene: TriggerScene
    input_text: str | None = Field(default=None, max_length=2000)
    requested_resource_types: list[ResourceType] = Field(
        default_factory=lambda: [ResourceType.BOOK, ResourceType.PAPER]
    )
    requested_output_type: OutputType | None = None
    source_resource_id: int | None = Field(default=None, ge=1)
    source_item_id: int | None = Field(default=None, ge=1)
    as_of_time: datetime | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("requested_resource_types")
    @classmethod
    def resource_types_are_unique(
        cls, value: list[ResourceType]
    ) -> list[ResourceType]:
        if len(value) != len(set(value)):
            raise ValueError("requested_resource_types must not contain duplicates")
        return value


class ResourceSummaryResponse(StrictModel):
    resource_id: int = Field(ge=1)
    resource_type: ResourceType
    title: str = Field(min_length=1)
    authors: list[str]
    publication_year: int | None = Field(default=None, ge=1)
    availability_status: AvailabilityStatus


class RecommendationGroupResponse(StrictModel):
    group_id: int = Field(ge=1)
    group_type: str = Field(min_length=1)
    group_key: str
    title: str
    goal: str | None = None
    order_no: int = Field(ge=1)


class RecommendationItemResponse(StrictModel):
    item_id: int = Field(ge=1)
    resource: ResourceSummaryResponse
    rank_no: int = Field(ge=1)
    group_id: int | None = Field(default=None, ge=1)
    reason_summary: str = Field(min_length=1)
    evidence_confidence: float = Field(ge=0, le=1)
    unavailable_now: bool = False


class InteractionDecisionResponse(StrictModel):
    output_type: OutputType
    delivery_strategy: DeliveryStrategy
    explanation_level: ExplanationLevel
    adaptation_state: AdaptationState
    decision_reason_codes: list[str] = Field(min_length=1)
    decision_reason: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)


class VersionBundleResponse(StrictModel):
    config_bundle: str = Field(min_length=1)
    policy: str = Field(min_length=1)
    ranking: str = Field(min_length=1)
    behavior_formula: str = Field(min_length=1)
    embedding: str | None = Field(default=None, min_length=1)
    graph: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    dataset: str = Field(min_length=1)


class RecommendationExecutionResponse(StrictModel):
    task_id: UUID
    record_id: int | None = Field(default=None, ge=1)
    trace_id: UUID
    status: TaskStatus
    context_version: int = Field(ge=1)
    evaluation_at: datetime | None = None
    decision: InteractionDecisionResponse
    groups: list[RecommendationGroupResponse] | None = None
    items: list[RecommendationItemResponse] | None = None
    questions: list[dict[str, Any]] | None = None
    warnings: list[WarningCode]
    versions: VersionBundleResponse | None = None


def _invalid_scene(message: str, *, scene: TriggerScene) -> PublicAPIError:
    return PublicAPIError(
        status_code=422,
        code=ErrorCode.INVALID_SCENE_SOURCE,
        message=message,
        retryable=False,
        details={"scene": scene.value},
    )


def _validate_request_shape(request: RecommendationTaskCreateRequest) -> None:
    if request.as_of_time is not None:
        raise PublicAPIError(
            status_code=403,
            code=ErrorCode.AS_OF_TIME_FORBIDDEN,
            message="Historical evaluation time requires research-admin authorization.",
            retryable=False,
            details={},
        )

    has_resource = request.source_resource_id is not None
    has_item = request.source_item_id is not None
    if request.scene is TriggerScene.HOME and (has_resource or has_item):
        raise _invalid_scene("HOME does not accept a source reference.", scene=request.scene)
    if request.scene is TriggerScene.SEARCH_AFTER:
        if has_resource or has_item:
            raise _invalid_scene(
                "SEARCH_AFTER does not accept a source reference.", scene=request.scene
            )
        if not (request.input_text or "").strip():
            raise _invalid_scene(
                "SEARCH_AFTER requires non-empty input_text.", scene=request.scene
            )
    elif request.scene is TriggerScene.RESOURCE_DETAIL:
        if not has_resource or has_item:
            raise _invalid_scene(
                "RESOURCE_DETAIL requires source_resource_id only.", scene=request.scene
            )
    elif request.scene in (TriggerScene.FEEDBACK_REFRESH, TriggerScene.EXPLANATION):
        if not has_item or has_resource:
            raise _invalid_scene(
                f"{request.scene.value} requires source_item_id only.", scene=request.scene
            )

    if request.requested_output_type is OutputType.BOOKLIST and request.limit < 8:
        raise PublicAPIError(
            status_code=422,
            code=ErrorCode.LIMIT_TOO_SMALL_FOR_BOOKLIST,
            message="BOOKLIST requires at least eight items.",
            retryable=False,
            details={"minimum": 8, "requested": request.limit},
        )
    if request.requested_output_type is OutputType.READING_PATH and request.limit < 6:
        raise PublicAPIError(
            status_code=422,
            code=ErrorCode.LIMIT_TOO_SMALL_FOR_READING_PATH,
            message="READING_PATH requires at least six items.",
            retryable=False,
            details={"minimum": 6, "requested": request.limit},
        )


def _resolve_demo_user(
    *,
    request: RecommendationTaskCreateRequest,
    demo_user_id: int | None,
    app_env: str,
    demo_identity_enabled: bool,
) -> int:
    if app_env != "demo" or not demo_identity_enabled:
        raise PublicAPIError(
            status_code=401,
            code=ErrorCode.AUTHENTICATION_REQUIRED,
            message="A valid authenticated user is required.",
            retryable=False,
            details={},
        )
    if demo_user_id is None:
        raise PublicAPIError(
            status_code=401,
            code=ErrorCode.AUTHENTICATION_REQUIRED,
            message="X-Demo-User-Id is required for the local demo.",
            retryable=False,
            details={},
        )
    if request.user_id is not None and request.user_id != demo_user_id:
        raise PublicAPIError(
            status_code=403,
            code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
            message="The request user does not match the authenticated user.",
            retryable=False,
            details={},
        )
    return demo_user_id


def create_recommendation_router(
    *,
    service: RecommendationTaskService,
    app_env: str,
    demo_identity_enabled: bool = False,
    pipeline_enabled: bool = False,
) -> APIRouter:
    """Build the opt-in task route around an application port."""

    router = APIRouter(prefix="/api/v1", tags=["Recommendation"])

    @router.post(
        "/recommendation-tasks",
        response_model=RecommendationExecutionResponse,
        response_model_exclude_none=True,
        responses={
            200: {"model": RecommendationExecutionResponse, "headers": IDEMPOTENCY_HEADERS},
            201: {"model": RecommendationExecutionResponse, "headers": IDEMPOTENCY_HEADERS},
            400: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            401: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            403: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            409: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            422: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            503: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
        },
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="recommendation_create_task_v1",
        summary="Create or replay a recommendation task",
        status_code=201,
    )
    async def create_task(
        request: RecommendationTaskCreateRequest,
        response: Response,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=8, max_length=255
        ),
        demo_user_id: int | None = Header(
            default=None, alias="X-Demo-User-Id", ge=1
        ),
    ) -> RecommendationExecutionResponse:
        if not pipeline_enabled:
            raise PublicAPIError(
                status_code=503,
                code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
                message="The recommendation pipeline is disabled in this runtime.",
                retryable=False,
                details={"recommendation_pipeline": "DISABLED"},
            )
        if idempotency_key != str(request.request_id):
            raise PublicAPIError(
                status_code=409,
                code=ErrorCode.REQUEST_ID_MISMATCH,
                message="Idempotency-Key must equal request_id.",
                retryable=False,
                details={},
            )
        _validate_request_shape(request)
        user_id = _resolve_demo_user(
            request=request,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
        )
        result = await service.create_task(
            RecommendationTaskCommand(
                request_id=request.request_id,
                session_id=request.session_id,
                user_id=user_id,
                scene=request.scene.value,
                input_text=request.input_text,
                resource_types=tuple(item.value for item in request.requested_resource_types),
                output_type=(
                    request.requested_output_type.value
                    if request.requested_output_type is not None
                    else None
                ),
                source_resource_id=request.source_resource_id,
                source_item_id=request.source_item_id,
                evaluation_at=None,
                constraints=dict(request.constraints),
                limit=request.limit,
            ),
            idempotency_key=idempotency_key,
        )
        response.status_code = result.status_code
        response.headers["Idempotency-Replayed"] = "true" if result.replayed else "false"
        return RecommendationExecutionResponse.model_validate(result.payload)

    return router
