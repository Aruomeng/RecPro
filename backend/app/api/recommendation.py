"""HTTP adapter for the first recommendation task vertical slice.

The adapter owns validation, demo identity and idempotency headers.  It never
opens a database connection and delegates persistence to the application port.
The router is opt-in from the composition root so the default G1 runtime keeps
the recommendation surface disabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from fastapi import APIRouter, Header, Response
from pydantic import Field, field_validator

from backend.app.api.auth import PrincipalResolver, resolve_user_principal
from backend.app.api.errors import PublicAPIError
from backend.app.api.health import CORRELATION_HEADERS, REQUEST_ID_PARAMETER
from backend.app.api.models import AgentActionResponse, ErrorResponse, StrictModel
from backend.app.recommendation.application.public import (
    IdempotencyConflictError,
    RecommendationTaskCommand,
    RecommendationTaskService,
    StaleContextVersionError,
    TaskStateConflictError,
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
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal
from backend.app.shared_kernel.contracts.errors import ErrorCode, WarningCode


IDEMPOTENCY_HEADERS = {
    **CORRELATION_HEADERS,
    "Idempotency-Replayed": {
        "description": "Whether the response replays a previously persisted task.",
        "schema": {"type": "boolean"},
    },
}

# Agent implementations can retain fine-grained diagnostic warnings for their
# trace/audit records.  The HTTP contract deliberately exposes a smaller,
# stable vocabulary: it must never turn an otherwise durable recommendation
# into a 500 merely because an internal warning is newly introduced.
_PUBLIC_WARNING_ALIASES = {
    "LLM_EXPLANATION_FALLBACK": ("LLM_FALLBACK_USED", "TEMPLATE_EXPLANATION"),
    "EVIDENCE_VALIDATION_FAILED": ("TEMPLATE_EXPLANATION",),
    "LLM_INTENT_FALLBACK": ("LLM_FALLBACK_USED", "RULE_INTENT_FALLBACK"),
    "LLM_INTENT_SKIPPED_EMPTY_INPUT": ("RULE_INTENT_FALLBACK",),
    "REPLAN_REQUIRED": ("REPLAN_EXHAUSTED",),
    "REPLAN_BUDGET_EXHAUSTED": ("REPLAN_EXHAUSTED",),
    "GRAPH_RECALL_UNAVAILABLE": ("KG_CHANNEL_UNAVAILABLE",),
    "VECTOR_RECALL_UNAVAILABLE": ("VECTOR_CHANNEL_UNAVAILABLE",),
    "VECTOR_QUERY_UNAVAILABLE": ("VECTOR_CHANNEL_UNAVAILABLE",),
    "CATALOG_EMPTY": ("INSUFFICIENT_RESOURCE_COVERAGE",),
    "CATALOG_READ_UNAVAILABLE": ("LIMITED_EVIDENCE",),
    "PROFILE_READ_UNAVAILABLE": ("SESSION_ONLY_PROFILE",),
    "PROFILE_PROJECTION_CURRENT_AS_OF": ("SESSION_ONLY_PROFILE",),
}
_PUBLIC_WARNING_VALUES = frozenset(code.value for code in WarningCode)


def _project_public_warnings(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Map internal Agent diagnostics onto the closed public warning contract."""

    projected = dict(payload)
    raw_warnings = projected.get("warnings", [])
    if not isinstance(raw_warnings, list) or any(
        not isinstance(warning, str) or not warning.strip() for warning in raw_warnings
    ):
        # Preserve malformed input so the response model can reject it with a
        # normal validation error instead of silently changing its meaning.
        return projected
    warnings: list[str] = []
    for warning in raw_warnings:
        candidates = _PUBLIC_WARNING_ALIASES.get(warning, (warning,))
        for candidate in candidates:
            public_code = candidate if candidate in _PUBLIC_WARNING_VALUES else "LIMITED_EVIDENCE"
            if public_code not in warnings:
                warnings.append(public_code)
    projected["warnings"] = warnings
    return projected


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


class ClarificationRequest(StrictModel):
    context_version: int = Field(ge=1)
    answers: dict[str, str] = Field(min_length=1)

    @field_validator("answers")
    @classmethod
    def answers_are_non_blank(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not item.strip() for key, item in value.items()):
            raise ValueError("clarification answers must contain non-blank strings")
        return value


class ClarificationQuestionResponse(StrictModel):
    slot: str = Field(min_length=1)
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=1)
    required: bool


class ResourceSummaryResponse(StrictModel):
    resource_id: int = Field(ge=1)
    resource_type: ResourceType
    title: str = Field(min_length=1)
    authors: list[str]
    publication_year: int | None = Field(default=None, ge=1)
    availability_status: AvailabilityStatus
    difficulty_level: int | None = Field(default=None, ge=1, le=4)


class RecommendationEvidenceResponse(StrictModel):
    score: float = Field(ge=0, le=1)
    channels: list[str] = Field(min_length=1)
    channel_scores: dict[str, float]
    channel_ranks: dict[str, int]
    primary_channel: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    negative_penalty: float = Field(ge=0, le=1)


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
    evidence: RecommendationEvidenceResponse | None = None


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
    questions: list[ClarificationQuestionResponse] | None = None
    warnings: list[WarningCode]
    agent_actions: list[AgentActionResponse] = Field(default_factory=list)
    versions: VersionBundleResponse | None = None


class RecommendationTaskStatusResponse(StrictModel):
    task_id: UUID
    trace_id: UUID
    status: TaskStatus
    context_version: int = Field(ge=1)
    record_id: int | None = Field(default=None, ge=1)
    evaluation_at: datetime
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    warnings: list[WarningCode]
    versions: VersionBundleResponse


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
    resolved_user_id = _require_demo_identity(
        demo_user_id=demo_user_id,
        app_env=app_env,
        demo_identity_enabled=demo_identity_enabled,
    )
    if request.user_id is not None and request.user_id != resolved_user_id:
        raise PublicAPIError(
            status_code=403,
            code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
            message="The request user does not match the authenticated user.",
            retryable=False,
            details={},
        )
    return resolved_user_id


def _require_demo_identity(
    *,
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
    return demo_user_id


async def _resolve_principal(
    *,
    request_user_id: int | None,
    authorization: str | None,
    demo_user_id: int | None,
    app_env: str,
    demo_identity_enabled: bool,
    principal_resolver: PrincipalResolver | None,
) -> AuthenticatedPrincipal:
    principal = await resolve_user_principal(
        authorization=authorization,
        demo_user_id=demo_user_id,
        app_env=app_env,
        demo_identity_enabled=demo_identity_enabled,
        resolver=principal_resolver,
    )
    if request_user_id is not None and request_user_id != principal.user_id:
        raise PublicAPIError(
            status_code=403,
            code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
            message="The request user does not match the authenticated user.",
            retryable=False,
            details={},
        )
    return principal


def create_recommendation_router(
    *,
    service: RecommendationTaskService,
    app_env: str,
    demo_identity_enabled: bool = False,
    pipeline_enabled: bool = False,
    principal_resolver: PrincipalResolver | None = None,
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
        authorization: str | None = Header(default=None, alias="Authorization"),
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
        principal = await _resolve_principal(
            request_user_id=request.user_id,
            authorization=authorization,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
            principal_resolver=principal_resolver,
        )
        try:
            result = await service.create_task(
                RecommendationTaskCommand(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    user_id=principal.user_id,
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
        except IdempotencyConflictError as exc:
            raise PublicAPIError(
                status_code=409,
                code=ErrorCode.IDEMPOTENCY_KEY_REUSED,
                message="The idempotency key was already used with a different payload.",
                retryable=False,
                details={},
            ) from exc
        response.status_code = result.status_code
        response.headers["Idempotency-Replayed"] = "true" if result.replayed else "false"
        return RecommendationExecutionResponse.model_validate(
            _project_public_warnings(result.payload)
        )

    @router.get(
        "/recommendation-tasks/{task_id}",
        response_model=RecommendationTaskStatusResponse,
        response_model_exclude_none=True,
        responses={
            200: {"model": RecommendationTaskStatusResponse, "headers": CORRELATION_HEADERS},
            401: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
            403: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
            404: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
            422: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
            503: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        },
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="recommendation_get_task_v1",
        summary="Read recommendation task state",
    )
    async def get_task(
        task_id: UUID,
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> RecommendationTaskStatusResponse:
        if not pipeline_enabled:
            raise PublicAPIError(
                status_code=503,
                code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
                message="The recommendation pipeline is disabled in this runtime.",
                retryable=False,
                details={"recommendation_pipeline": "DISABLED"},
            )
        principal = await _resolve_principal(
            request_user_id=None,
            authorization=authorization,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
            principal_resolver=principal_resolver,
        )
        try:
            payload = await service.get_task(task_id, user_id=principal.user_id)
        except LookupError as exc:
            raise PublicAPIError(
                status_code=404,
                code=ErrorCode.NOT_FOUND,
                message="The requested recommendation task was not found.",
                retryable=False,
                details={},
            ) from exc
        return RecommendationTaskStatusResponse.model_validate(
            _project_public_warnings(payload)
        )

    @router.post(
        "/recommendation-tasks/{task_id}/clarifications",
        response_model=RecommendationExecutionResponse,
        response_model_exclude_none=True,
        responses={
            200: {"model": RecommendationExecutionResponse, "headers": IDEMPOTENCY_HEADERS},
            400: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            401: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            403: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            404: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            409: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            422: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            429: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            503: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
            504: {"model": ErrorResponse, "headers": IDEMPOTENCY_HEADERS},
        },
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
        operation_id="recommendation_submit_clarification_v1",
        summary="Resume the same task with clarification answers",
        status_code=200,
    )
    async def submit_clarification(
        task_id: UUID,
        request: ClarificationRequest,
        response: Response,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=8, max_length=255
        ),
        demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id", ge=1),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> RecommendationExecutionResponse:
        if not pipeline_enabled:
            raise PublicAPIError(
                status_code=503,
                code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
                message="The recommendation pipeline is disabled in this runtime.",
                retryable=False,
                details={"recommendation_pipeline": "DISABLED"},
            )
        principal = await _resolve_principal(
            request_user_id=None,
            authorization=authorization,
            demo_user_id=demo_user_id,
            app_env=app_env,
            demo_identity_enabled=demo_identity_enabled,
            principal_resolver=principal_resolver,
        )
        submit = getattr(service, "submit_clarification", None)
        if submit is None:
            raise PublicAPIError(
                status_code=503,
                code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
                message="Clarification is not available in this runtime.",
                retryable=True,
                details={"clarification": "UNAVAILABLE"},
            )
        try:
            result = await submit(
                task_id,
                context_version=request.context_version,
                answers=dict(request.answers),
                idempotency_key=idempotency_key,
                user_id=principal.user_id,
            )
        except IdempotencyConflictError as exc:
            raise PublicAPIError(
                status_code=409,
                code=ErrorCode.IDEMPOTENCY_KEY_REUSED,
                message="The idempotency key was already used with different answers.",
                retryable=False,
                details={},
            ) from exc
        except StaleContextVersionError as exc:
            raise PublicAPIError(
                status_code=409,
                code=ErrorCode.STALE_CONTEXT_VERSION,
                message="The clarification context version is stale.",
                retryable=False,
                details={"context_version": request.context_version},
            ) from exc
        except TaskStateConflictError as exc:
            raise PublicAPIError(
                status_code=409,
                code=ErrorCode.TASK_STATE_CONFLICT,
                message="The task is not waiting for clarification.",
                retryable=False,
                details={},
            ) from exc
        except LookupError as exc:
            raise PublicAPIError(
                status_code=404,
                code=ErrorCode.NOT_FOUND,
                message="The requested recommendation task was not found.",
                retryable=False,
                details={},
            ) from exc
        except ValueError as exc:
            raise PublicAPIError(
                status_code=422,
                code=ErrorCode.INVALID_JSON,
                message="Clarification answers are invalid.",
                retryable=False,
                details={},
            ) from exc
        response.headers["Idempotency-Replayed"] = "true" if result.replayed else "false"
        return RecommendationExecutionResponse.model_validate(
            _project_public_warnings(result.payload)
        )

    return router
