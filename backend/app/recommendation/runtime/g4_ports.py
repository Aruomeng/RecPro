"""Compatibility facade for the catalog-owned G4 port factory.

The implementation lives in ``backend.app.catalog.runtime.g4_ports`` so the
modular-monolith dependency direction stays explicit. This path remains
available for older local scripts without adding a static cross-module
dependency; new code should import the catalog runtime directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import re
from typing import Any


_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
_GRAPH_VERSION_MAX_LENGTH = 64


@dataclass(frozen=True, slots=True)
class G4ReadOnlyRuntime:
    """Immutable retrieval ports and the versions they are allowed to read."""

    graph: Any
    vector: Any
    query_embedder: Any
    graph_version: str
    embedding_version: str
    index_version: str
    namespace_name: str
    dimension: int


def _validate_graph_version(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _GRAPH_VERSION_MAX_LENGTH:
        raise ValueError("graph version must be a non-blank string of at most 64 characters")
    return value.strip()


def _validate_version(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} has an unsafe format")
    return value


def build_g4_readonly_runtime(
    *,
    graph_endpoint: str,
    graph_username: str,
    graph_password: str,
    chroma_collection: object,
    graph_version: str,
    embedding_version: str,
    index_version: str,
    namespace_name: str,
    dimension: int = 384,
    timeout: float = 8.0,
    query_embedder: Any | None = None,
) -> G4ReadOnlyRuntime:
    """Build G4 read ports without opening a store connection.

    ``chroma_collection`` must be supplied by an explicit operator/runtime
    layer.  This keeps optional Chroma dependencies and collection lifecycle
    operations outside the application package.
    """

    chroma_adapter = import_module("backend.app.catalog.adapters.chroma")
    embedding_adapter = import_module("backend.app.catalog.adapters.embedding")
    neo4j_adapter = import_module("backend.app.catalog.adapters.neo4j")
    normalized_graph_version = _validate_graph_version(graph_version)
    normalized_embedding_version = _validate_version(
        embedding_version, label="embedding version"
    )
    normalized_index_version = _validate_version(index_version, label="index version")
    if query_embedder is None:
        query_embedder = embedding_adapter.HashCharNgramQueryEmbedder()
    if query_embedder.embedding_version != normalized_embedding_version:
        raise ValueError("query embedder version does not match embedding version")
    if query_embedder.dimension != dimension:
        raise ValueError("query embedder dimension does not match vector dimension")

    graph = neo4j_adapter.Neo4jGraphReader(
        endpoint=graph_endpoint,
        username=graph_username,
        password=graph_password,
        timeout=timeout,
    )
    vector = chroma_adapter.ChromaVectorReader(
        collection=chroma_collection,
        namespace_name=namespace_name,
        embedding_version=normalized_embedding_version,
        index_version=normalized_index_version,
        dimension=dimension,
        timeout=timeout,
    )
    return G4ReadOnlyRuntime(
        graph=graph,
        vector=vector,
        query_embedder=query_embedder,
        graph_version=normalized_graph_version,
        embedding_version=normalized_embedding_version,
        index_version=normalized_index_version,
        namespace_name=namespace_name,
        dimension=dimension,
    )


__all__ = ["G4ReadOnlyRuntime", "build_g4_readonly_runtime"]
