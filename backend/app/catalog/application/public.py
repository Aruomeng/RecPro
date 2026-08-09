"""Catalog application-level index planning use case."""

from __future__ import annotations

import hashlib
import re
from uuid import NAMESPACE_URL, uuid5

from backend.app.catalog.domain.models import IndexBuildPlan, ResourceSummary


_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")


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
