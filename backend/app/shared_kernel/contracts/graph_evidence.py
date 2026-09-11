"""Stable, routeable references for bounded public graph paths.

The reference carries only the two public graph entity IDs needed to replay a
bounded read.  It never contains Cypher, database identifiers, source records,
or raw metadata.  The digest remains bound to the complete ordered node/edge
path so the exploration response can select the exact recommendation path.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Sequence


_PREFIX = "graphpath:v2:"
_LEGACY_PATTERN = re.compile(r"^graphpath:[0-9a-f]{32}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_MAX_ENTITY_ID_LENGTH = 256
_MAX_REFERENCE_LENGTH = 800


@dataclass(frozen=True, slots=True)
class GraphPathRoute:
    """Public endpoints recovered from a v2 graph-path reference."""

    source_id: str
    target_id: str


def _encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("graph path reference endpoint is invalid") from exc
    if not decoded or len(decoded) > _MAX_ENTITY_ID_LENGTH:
        raise ValueError("graph path reference endpoint is outside bounds")
    return decoded


def build_graph_path_reference(
    *,
    graph_version: str,
    node_ids: Sequence[str],
    edge_ids: Sequence[str],
) -> str:
    """Build a stable reference for one 1-3 hop public path."""

    if not graph_version.startswith("lib-books-v2-") or len(graph_version) > 64:
        raise ValueError("routeable graph path references require a bounded v2 version")
    if not 2 <= len(node_ids) <= 4 or len(edge_ids) != len(node_ids) - 1:
        raise ValueError("graph path reference requires one to three hops")
    normalized_nodes = tuple(str(value).strip() for value in node_ids)
    normalized_edges = tuple(str(value).strip() for value in edge_ids)
    if any(not value or len(value) > _MAX_ENTITY_ID_LENGTH for value in normalized_nodes):
        raise ValueError("graph path node ID is outside bounds")
    if any(not value or len(value) > _MAX_ENTITY_ID_LENGTH for value in normalized_edges):
        raise ValueError("graph path edge ID is outside bounds")
    canonical = json.dumps(
        [graph_version, list(normalized_nodes), list(normalized_edges)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = sha256(canonical).hexdigest()[:32]
    reference = (
        f"{_PREFIX}{_encode(normalized_nodes[0])}."
        f"{_encode(normalized_nodes[-1])}.{digest}"
    )
    if len(reference) > _MAX_REFERENCE_LENGTH:
        raise ValueError("graph path reference is too long")
    return reference


def parse_graph_path_route(reference: str) -> GraphPathRoute | None:
    """Return v2 route endpoints, or ``None`` for a valid legacy reference."""

    if not isinstance(reference, str) or not reference or len(reference) > _MAX_REFERENCE_LENGTH:
        raise ValueError("graph path reference is invalid")
    if _LEGACY_PATTERN.fullmatch(reference):
        return None
    if not reference.startswith(_PREFIX):
        raise ValueError("graph path reference is invalid")
    parts = reference.removeprefix(_PREFIX).split(".")
    if len(parts) != 3 or _DIGEST_PATTERN.fullmatch(parts[2]) is None:
        raise ValueError("graph path reference is invalid")
    source_id = _decode(parts[0])
    target_id = _decode(parts[1])
    if source_id == target_id:
        raise ValueError("graph path reference endpoints must differ")
    return GraphPathRoute(source_id=source_id, target_id=target_id)


def is_graph_path_reference(reference: object) -> bool:
    try:
        parse_graph_path_route(reference)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return True


def is_routeable_graph_path_reference(reference: object) -> bool:
    """Return whether a reference carries bounded public v2 route endpoints."""

    try:
        return parse_graph_path_route(reference) is not None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


__all__ = [
    "GraphPathRoute",
    "build_graph_path_reference",
    "is_graph_path_reference",
    "is_routeable_graph_path_reference",
    "parse_graph_path_route",
]
