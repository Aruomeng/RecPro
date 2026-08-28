"""Dependency-free catalog values used by application services and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ResourceSummary:
    id: int
    resource_type: str
    external_id: str
    title: str
    authors: tuple[str, ...]
    abstract_text: str | None
    keywords: tuple[str, ...]
    category_code: str | None
    publication_year: int | None
    availability_status: str
    available_from: datetime
    access_url: str | None
    metadata_quality: float
    is_classic: bool
    metadata_version: int
    language: str | None
    difficulty_level: int | None


@dataclass(frozen=True, slots=True)
class ResourceTagEvidence:
    resource_id: int
    tag_id: int
    normalized_name: str
    weight: float
    confidence: float
    source: str


@dataclass(frozen=True, slots=True)
class GraphRecallEvidence:
    """A read-only graph hit keyed by the catalog's stable external ID."""

    external_id: str
    score: float
    matched_terms: tuple[str, ...]
    graph_version: str
    graph_path_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VectorRecallEvidence:
    """A read-only vector hit bound to one immutable index/version contract."""

    external_id: str
    vector_id: str
    score: float
    embedding_version: str
    index_version: str
    namespace_name: str


@dataclass(frozen=True, slots=True)
class IndexBuildPlan:
    build_id: str
    resource_id: int
    target: str
    index_version: str
    metadata_version: int
    content_hash: str
    namespace_name: str
    status: str = "PLANNED"
