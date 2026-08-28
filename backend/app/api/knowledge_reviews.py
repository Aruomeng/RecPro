"""Bearer-only librarian API for append-only knowledge review actions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from pydantic import Field

from backend.app.api.auth import PrincipalResolver, require_bearer_principal
from backend.app.api.errors import PublicAPIError
from backend.app.api.health import CORRELATION_HEADERS, REQUEST_ID_PARAMETER
from backend.app.api.models import ErrorResponse, StrictModel
from backend.app.knowledge_review.domain import KnowledgeReviewAction, KnowledgeReviewStatus
from backend.app.knowledge_review.service import KnowledgeReviewService
from backend.app.shared_kernel.contracts.errors import ErrorCode


class KnowledgeReviewActionView(StrictModel):
    fact_uuid: UUID
    version: int = Field(ge=1)
    action: KnowledgeReviewAction
    librarian_user_id: int = Field(ge=1)
    reason_code: str
    occurred_at: datetime


class KnowledgeReviewView(StrictModel):
    proposal_uuid: UUID
    proposal_type: str
    graph_version: str
    subject_id: str
    relation_type: str
    object_id: str
    source_refs: list[str] = Field(min_length=1, max_length=20)
    reason_codes: list[str] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0, le=1)
    agent_name: str
    task_id: UUID | None = None
    workspace_id: UUID | None = None
    idempotency_sha256: str = Field(min_length=64, max_length=64)
    occurred_at: datetime
    status: KnowledgeReviewStatus
    actions: list[KnowledgeReviewActionView]


class KnowledgeReviewList(StrictModel):
    items: list[KnowledgeReviewView] = Field(max_length=100)


class KnowledgeReviewActionRequest(StrictModel):
    action: KnowledgeReviewAction
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")


class KnowledgeReviewActionResponse(StrictModel):
    review: KnowledgeReviewView
    replayed: bool
    neo4j_write_count: int = 0


def _forbidden() -> PublicAPIError:
    return PublicAPIError(
        403, ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
        "The catalog knowledge review permission is required.", False, {},
    )


def create_knowledge_review_router(
    *, service: KnowledgeReviewService,
    principal_resolver: PrincipalResolver,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/librarian/knowledge-reviews", tags=["KnowledgeReview"])
    responses = {
        status: {"model": ErrorResponse, "headers": CORRELATION_HEADERS}
        for status in (401, 403, 404, 409, 422, 429, 503)
    }

    async def actor(authorization: str | None):
        principal = await require_bearer_principal(authorization, resolver=principal_resolver)
        try:
            service.authorize(principal)
        except PermissionError as exc:
            raise _forbidden() from exc
        return principal

    @router.get("", response_model=KnowledgeReviewList, responses=responses, openapi_extra={"parameters": [REQUEST_ID_PARAMETER]})
    async def list_reviews(
        status: KnowledgeReviewStatus | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=100),
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> KnowledgeReviewList:
        principal = await actor(authorization)
        return KnowledgeReviewList(items=[
            KnowledgeReviewView.model_validate(item)
            for item in await service.list_reviews(actor=principal, status=status, limit=limit)
        ])

    @router.get("/{proposal_id}", response_model=KnowledgeReviewView, responses=responses, openapi_extra={"parameters": [REQUEST_ID_PARAMETER]})
    async def get_review(
        proposal_id: UUID,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> KnowledgeReviewView:
        principal = await actor(authorization)
        try:
            return KnowledgeReviewView.model_validate(await service.get_review(proposal_id, actor=principal))
        except LookupError as exc:
            raise PublicAPIError(404, ErrorCode.NOT_FOUND, "Knowledge review proposal was not found.", False, {}) from exc

    @router.post("/{proposal_id}/actions", response_model=KnowledgeReviewActionResponse, responses=responses, openapi_extra={"parameters": [REQUEST_ID_PARAMETER]})
    async def append_action(
        proposal_id: UUID,
        payload: KnowledgeReviewActionRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> KnowledgeReviewActionResponse:
        principal = await actor(authorization)
        try:
            view, replayed = await service.act(
                proposal_id, action=payload.action, reason_code=payload.reason_code,
                idempotency_key=idempotency_key, actor=principal,
            )
            return KnowledgeReviewActionResponse(
                review=KnowledgeReviewView.model_validate(view),
                replayed=replayed, neo4j_write_count=0,
            )
        except LookupError as exc:
            raise PublicAPIError(404, ErrorCode.NOT_FOUND, "Knowledge review proposal was not found.", False, {}) from exc
        except ValueError as exc:
            raise PublicAPIError(409, ErrorCode.IDEMPOTENCY_CONFLICT, "Knowledge review action conflicts with existing facts.", False, {}) from exc
        except OverflowError as exc:
            raise PublicAPIError(429, ErrorCode.CAPACITY_EXCEEDED, "Knowledge review capacity is temporarily full.", True, {}) from exc

    return router


__all__ = ["create_knowledge_review_router"]
