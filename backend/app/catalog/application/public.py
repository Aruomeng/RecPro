"""Catalog application-level index planning use case."""

from __future__ import annotations

import asyncio
import hashlib
import re
from uuid import NAMESPACE_URL, uuid5

from backend.app.catalog.domain.models import (
    IndexBuildPlan,
    ResourceCandidateSummary,
    ResourceSummary,
)
from backend.app.catalog.ports.public import (
    CatalogEvidenceReader,
    CatalogEvidenceSnapshot,
    CatalogRepository,
)


_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")


def _candidate_summary(
    resource: ResourceSummary | ResourceCandidateSummary,
) -> ResourceCandidateSummary:
    """Convert legacy full resource values at the compatibility boundary.

    Older injected repositories still expose ``list_resources``. Keeping the
    conversion here lets those adapters participate in the lightweight
    evidence contract without making the Agent hot path depend on descriptive
    fields that are only needed by detail/index use cases.
    """

    if isinstance(resource, ResourceCandidateSummary):
        return resource
    return ResourceCandidateSummary(
        id=resource.id,
        resource_type=resource.resource_type,
        external_id=resource.external_id,
        title=resource.title,
        authors=resource.authors,
        keywords=resource.keywords,
        category_code=resource.category_code,
        publication_year=resource.publication_year,
        availability_status=resource.availability_status,
        available_from=resource.available_from,
        metadata_quality=resource.metadata_quality,
        is_classic=resource.is_classic,
        metadata_version=resource.metadata_version,
        language=resource.language,
        difficulty_level=resource.difficulty_level,
    )


def _namespace_name(prefix: str, index_version: str, target: str) -> str:
    safe_prefix = re.sub(r"[^a-z0-9_]+", "_", prefix.lower()).strip("_") or "recpro"
    safe_version = re.sub(r"[^a-z0-9_]+", "_", index_version.lower()).strip("_")
    return f"{safe_prefix}_{target.lower()}_{safe_version}"[:255]


def plan_index_builds(
    resources: tuple[ResourceSummary, ...],
    *,
    index_version: str = "g2-index-v1",
    namespace_prefix: str = "recpro",
) -> tuple[IndexBuildPlan, ...]:
    """Create stable VECTOR/GRAPH plans without contacting optional stores."""

    if _SAFE_VERSION.fullmatch(index_version) is None:
        raise ValueError("index_version must use safe version characters")
    plans: list[IndexBuildPlan] = []
    for resource in resources:
        content_hash = hashlib.sha256(
            "|".join(
                (
                    resource.external_id,
                    resource.title,
                    resource.abstract_text or "",
                    ",".join(resource.keywords),
                    str(resource.metadata_version),
                )
            ).encode("utf-8")
        ).hexdigest()
        for target in ("VECTOR", "GRAPH"):
            key = f"{resource.id}:{target}:{index_version}:{resource.metadata_version}:{content_hash}"
            plans.append(
                IndexBuildPlan(
                    build_id=str(uuid5(NAMESPACE_URL, key)),
                    resource_id=resource.id,
                    target=target,
                    index_version=index_version,
                    metadata_version=resource.metadata_version,
                    content_hash=content_hash,
                    namespace_name=_namespace_name(namespace_prefix, index_version, target),
                )
            )
    return tuple(plans)


class TaskScopedCatalogEvidenceReader(CatalogEvidenceReader):
    """Deduplicate catalog evidence reads within one orchestration task.

    The cache deliberately has one entry and no process-wide lifetime.  It is
    therefore safe for versioned catalog data: a new orchestrator receives a
    fresh reader, while concurrent Agents in the same task share one bounded
    read-only snapshot.  Resource-type filtering happens after the full
    snapshot is loaded so semantic probing and recall can reuse the same data.
    """

    def __init__(self, repository: CatalogRepository) -> None:
        self._repository = repository
        self._lock = asyncio.Lock()
        self._cached_key: str | None = None
        self._cached_snapshot: CatalogEvidenceSnapshot | None = None

    async def read_evidence_snapshot(
        self,
        *,
        available_at=None,
        resource_type: str | None = None,
    ) -> CatalogEvidenceSnapshot:
        key = available_at.isoformat() if available_at is not None else "LATEST"
        async with self._lock:
            if self._cached_key != key or self._cached_snapshot is None:
                loader = getattr(self._repository, "read_evidence_snapshot", None)
                if callable(loader):
                    snapshot = await loader(available_at=available_at)
                else:
                    candidate_loader = getattr(
                        self._repository, "list_resource_candidates", None
                    )
                    if callable(candidate_loader):
                        resources = await candidate_loader(available_at=available_at)
                    else:
                        resources = tuple(
                            _candidate_summary(resource)
                            for resource in await self._repository.list_resources(
                                available_at=available_at,
                            )
                        )
                    tags = await self._repository.list_resource_tags(
                        resource_ids=tuple(resource.id for resource in resources),
                    )
                    snapshot = CatalogEvidenceSnapshot(
                        resources=tuple(
                            _candidate_summary(resource) for resource in resources
                        ),
                        tags=tags,
                        available_at=available_at,
                    )
                if not isinstance(snapshot, CatalogEvidenceSnapshot):
                    raise TypeError("catalog evidence reader returned an invalid snapshot")
                snapshot = CatalogEvidenceSnapshot(
                    resources=tuple(
                        _candidate_summary(resource) for resource in snapshot.resources
                    ),
                    tags=snapshot.tags,
                    available_at=snapshot.available_at,
                )
                self._cached_key = key
                self._cached_snapshot = snapshot
            snapshot = self._cached_snapshot

        if resource_type is None:
            return snapshot
        resources = tuple(
            resource for resource in snapshot.resources
            if resource.resource_type == resource_type
        )
        resource_ids = {resource.id for resource in resources}
        return CatalogEvidenceSnapshot(
            resources=resources,
            tags=tuple(tag for tag in snapshot.tags if tag.resource_id in resource_ids),
            available_at=snapshot.available_at,
        )


__all__ = [
    "TaskScopedCatalogEvidenceReader",
    "plan_index_builds",
]
