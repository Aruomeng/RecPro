"""Stable Catalog repository and unit-of-work ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.catalog.domain.models import (
    GraphRecallEvidence,
    ResourceSummary,
    ResourceTagEvidence,
    VectorRecallEvidence,
)


class CatalogRepository(Protocol):
    """Read-only catalog queries required by G2/G3 application services."""

    async def list_resources(
        self,
        *,
        available_at: datetime | None = None,
        resource_type: str | None = None,
    ) -> tuple[ResourceSummary, ...]: ...

    async def list_resource_tags(
        self,
        *,
        resource_ids: tuple[int, ...],
    ) -> tuple[ResourceTagEvidence, ...]: ...


@dataclass(frozen=True, slots=True)
class CatalogEvidenceSnapshot:
    """One immutable, read-only catalog view reused during a task."""

    resources: tuple[ResourceSummary, ...]
    tags: tuple[ResourceTagEvidence, ...]
    available_at: datetime | None = None


class CatalogEvidenceReader(Protocol):
    """Read the resource metadata and tag evidence needed by Agents."""

    async def read_evidence_snapshot(
        self,
        *,
        available_at: datetime | None = None,
        resource_type: str | None = None,
    ) -> CatalogEvidenceSnapshot: ...


class CatalogProjectionReader(Protocol):
    """Read only the resources selected for a persisted recommendation."""

    async def list_resources_by_ids(
        self,
        *,
        resource_ids: tuple[int, ...],
        available_at: datetime | None = None,
    ) -> tuple[ResourceSummary, ...]: ...


class CatalogUnitOfWork(Protocol):
    """Transaction boundary for catalog reads and future append-only imports."""

    catalog: CatalogRepository

    async def __aenter__(self) -> "CatalogUnitOfWork": ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class GraphRecallPort(Protocol):
    """Read-only graph recall boundary; it never owns a write transaction."""

    async def check_readiness(self, *, graph_version: str) -> None: ...

    async def recall(
        self,
        *,
        terms: tuple[str, ...],
        graph_version: str,
        limit: int,
    ) -> tuple[GraphRecallEvidence, ...]: ...


class VectorRecallPort(Protocol):
    """Read-only vector recall boundary for one immutable collection version."""

    async def recall(
        self,
        *,
        query_vector: tuple[float, ...],
        embedding_version: str,
        index_version: str,
        limit: int,
    ) -> tuple[VectorRecallEvidence, ...]: ...


class QueryEmbeddingPort(Protocol):
    """Create a bounded query vector for one versioned vector index."""

    @property
    def embedding_version(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, text: str) -> tuple[float, ...]: ...
