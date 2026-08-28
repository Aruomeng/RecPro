"""Public, read-only library exploration endpoints for the kiosk UI."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import Field

from backend.app.api.errors import PublicAPIError
from backend.app.api.health import CORRELATION_HEADERS, REQUEST_ID_PARAMETER
from backend.app.api.models import ErrorResponse, StrictModel
from backend.app.shared_kernel.contracts.errors import ErrorCode


class CountBucket(StrictModel):
    name: str
    count: int = Field(ge=0)


class DecadeBucket(StrictModel):
    year: int = Field(ge=0)
    count: int = Field(ge=0)


class OverviewTotals(StrictModel):
    resources: int = Field(ge=0)
    books: int = Field(ge=0)
    papers: int = Field(ge=0)
    tags: int = Field(ge=0)


class GraphTotals(StrictModel):
    nodes: int = Field(ge=0)
    relationships: int = Field(ge=0)


class LibraryOverviewResponse(StrictModel):
    schema_version: str
    dataset_version: str
    graph_version: str
    generated_at: datetime
    totals: OverviewTotals
    graph: GraphTotals
    availability: list[CountBucket]
    categories: list[CountBucket]
    publication_decades: list[DecadeBucket]
    popular_topics: list[CountBucket]


class ResourceDetailResponse(StrictModel):
    resource_id: int = Field(ge=1)
    resource_type: str
    external_id: str
    title: str
    authors: list[str]
    abstract: str | None = None
    keywords: list[str]
    category_code: str | None = None
    publication_year: int | None = None
    publisher: str | None = None
    language: str | None = None
    difficulty_level: int | None = Field(default=None, ge=1, le=4)
    availability_status: str
    isbn: str | None = None
    call_number: str | None = None
    location: str | None = None
    borrowable_copies: int = Field(ge=0)
    tags: list[str]


class GraphNodeResponse(StrictModel):
    id: str
    type: str
    label: str
    subtitle: str | None = None
    resource_id: int | None = Field(default=None, ge=1)
    properties: dict[str, Any]


class GraphEdgeResponse(StrictModel):
    id: str
    source: str
    target: str
    type: str
    label: str


class GraphViewResponse(StrictModel):
    graph_version: str
    query: str
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    truncated: bool


class GraphPathResponse(StrictModel):
    path_id: str
    node_ids: list[str] = Field(min_length=2, max_length=4)
    edge_ids: list[str] = Field(min_length=1, max_length=3)
    hop_count: int = Field(ge=1, le=3)
    score: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(min_length=1)


class GraphPathViewResponse(StrictModel):
    graph_version: str
    source_id: str
    target_id: str
    paths: list[GraphPathResponse] = Field(max_length=10)
    graph: GraphViewResponse
    truncated: bool


def _unavailable(exc: Exception) -> PublicAPIError:
    return PublicAPIError(
        status_code=503,
        code=ErrorCode.CORE_STORAGE_UNAVAILABLE,
        message="Library exploration data is temporarily unavailable.",
        retryable=True,
        details={"boundary": "exploration", "error_type": type(exc).__name__},
    )


def create_exploration_router(*, service: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1/explore", tags=["Exploration"])
    errors = {
        404: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        422: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
        503: {"model": ErrorResponse, "headers": CORRELATION_HEADERS},
    }

    @router.get(
        "/overview",
        response_model=LibraryOverviewResponse,
        responses=errors,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER], "security": []},
        operation_id="exploration_overview_v1",
    )
    async def overview() -> LibraryOverviewResponse:
        try:
            return LibraryOverviewResponse.model_validate(await service.overview())
        except (ConnectionError, RuntimeError, OSError) as exc:
            raise _unavailable(exc) from exc

    @router.get(
        "/resources/{resource_id}",
        response_model=ResourceDetailResponse,
        responses=errors,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER], "security": []},
        operation_id="exploration_resource_detail_v1",
    )
    async def resource_detail(resource_id: int) -> ResourceDetailResponse:
        try:
            return ResourceDetailResponse.model_validate(await service.resource(resource_id))
        except LookupError as exc:
            raise PublicAPIError(404, ErrorCode.NOT_FOUND, "The resource was not found.", False, {}) from exc
        except (ConnectionError, RuntimeError, OSError) as exc:
            raise _unavailable(exc) from exc

    @router.get(
        "/graph/search",
        response_model=GraphViewResponse,
        responses=errors,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER], "security": []},
        operation_id="exploration_graph_search_v1",
    )
    async def graph_search(
        q: str = Query(min_length=1, max_length=120),
        limit: int = Query(default=30, ge=1, le=30),
    ) -> GraphViewResponse:
        try:
            return GraphViewResponse.model_validate(await service.search_graph(q, limit=limit))
        except (ConnectionError, RuntimeError, OSError) as exc:
            raise _unavailable(exc) from exc

    @router.get(
        "/graph/nodes/{entity_id:path}/neighbors",
        response_model=GraphViewResponse,
        responses=errors,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER], "security": []},
        operation_id="exploration_graph_neighbors_v1",
    )
    async def graph_neighbors(
        entity_id: str,
        limit: int = Query(default=40, ge=1, le=40),
    ) -> GraphViewResponse:
        try:
            return GraphViewResponse.model_validate(await service.graph_neighbors(entity_id, limit=limit))
        except (ConnectionError, RuntimeError, OSError) as exc:
            raise _unavailable(exc) from exc

    @router.get(
        "/graph/paths",
        response_model=GraphPathViewResponse,
        responses=errors,
        openapi_extra={"parameters": [REQUEST_ID_PARAMETER], "security": []},
        operation_id="exploration_graph_paths_v2",
    )
    async def graph_paths(
        source_id: str = Query(min_length=1, max_length=256),
        target_id: str = Query(min_length=1, max_length=256),
        max_hops: int = Query(default=3, ge=1, le=3),
        limit: int = Query(default=10, ge=1, le=10),
    ) -> GraphPathViewResponse:
        try:
            return GraphPathViewResponse.model_validate(
                await service.graph_paths(
                    source_id, target_id, max_hops=max_hops, limit=limit,
                )
            )
        except ValueError as exc:
            raise PublicAPIError(
                422, ErrorCode.INVALID_JSON,
                "The bounded graph path request is invalid.", False,
                {"error_type": type(exc).__name__},
            ) from exc
        except (ConnectionError, RuntimeError, OSError) as exc:
            raise _unavailable(exc) from exc

    return router


__all__ = ["create_exploration_router"]
