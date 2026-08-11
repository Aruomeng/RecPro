"""Read-only Chroma adapter for a versioned vector recall collection.

The adapter deliberately does not import the optional ``chromadb`` package.
The composition root injects a compatible collection object, which keeps the
catalog port testable in the locked base environment and makes an unavailable
vector store fail closed.  The only collection operation used here is the
read-only ``query`` method; collection lifecycle and all writes belong to a
separate, explicitly authorized build workflow.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from backend.app.catalog.domain.models import VectorRecallEvidence


_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,254}$")
_DEFAULT_DIMENSION = 384
_MAX_LIMIT = 50
_MAX_DIMENSION = 8192


class ChromaVectorReader:
    """Query one immutable Chroma collection without exposing write methods."""

    def __init__(
        self,
        *,
        collection: Any,
        namespace_name: str,
        embedding_version: str,
        index_version: str,
        dimension: int = _DEFAULT_DIMENSION,
        timeout: float = 5.0,
    ) -> None:
        if collection is None or not callable(getattr(collection, "query", None)):
            raise ValueError("Chroma collection must expose a query method")
        if _NAMESPACE_PATTERN.fullmatch(namespace_name) is None:
            raise ValueError("Chroma namespace has an unsafe format")
        if _VERSION_PATTERN.fullmatch(embedding_version) is None:
            raise ValueError("embedding version has an unsafe format")
        if _VERSION_PATTERN.fullmatch(index_version) is None:
            raise ValueError("index version has an unsafe format")
        if not isinstance(dimension, int) or not 1 <= dimension <= _MAX_DIMENSION:
            raise ValueError("vector dimension is outside the supported range")
        if timeout <= 0 or timeout > 30:
            raise ValueError("Chroma vector timeout must be between 0 and 30 seconds")
        self._collection = collection
        self._namespace_name = namespace_name
        self._embedding_version = embedding_version
        self._index_version = index_version
        self._dimension = dimension
        self._timeout = timeout

    async def recall(
        self,
        *,
        query_vector: tuple[float, ...],
        embedding_version: str,
        index_version: str,
        limit: int,
    ) -> tuple[VectorRecallEvidence, ...]:
        """Return bounded, version-checked hits from the injected collection."""

        if embedding_version != self._embedding_version:
            raise ValueError("query embedding version does not match the collection")
        if index_version != self._index_version:
            raise ValueError("query index version does not match the collection")
        if not 1 <= limit <= _MAX_LIMIT:
            raise ValueError("vector recall limit must be between 1 and 50")
        normalized_vector = self._validate_vector(query_vector)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(self._run_query, normalized_vector, limit),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Chroma vector query timed out") from exc
        return self._parse_payload(payload, limit=limit)

    def _run_query(self, query_vector: tuple[float, ...], limit: int) -> Any:
        """Invoke only Chroma's read query operation in the worker thread."""

        version_filter = {
            "$and": [
                {"embedding_version": self._embedding_version},
                {"index_version": self._index_version},
            ]
        }
        try:
            return self._collection.query(
                query_embeddings=[list(query_vector)],
                n_results=limit,
                where=version_filter,
                include=["distances", "metadatas"],
            )
        except Exception as exc:  # pragma: no cover - concrete clients vary
            raise ConnectionError(
                f"Chroma vector query failed: {type(exc).__name__}"
            ) from exc

    def _validate_vector(self, query_vector: Sequence[float]) -> tuple[float, ...]:
        if not isinstance(query_vector, (tuple, list)):
            raise ValueError("query vector must be a tuple or list")
        vector: list[float] = []
        for value in query_vector:
            if isinstance(value, bool):
                raise ValueError("query vector contains a boolean")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("query vector contains a non-numeric value") from exc
            if not math.isfinite(numeric):
                raise ValueError("query vector contains a non-finite value")
            vector.append(numeric)
        if len(vector) != self._dimension:
            raise ValueError(f"query vector must have {self._dimension} dimensions")
        if math.sqrt(sum(value * value for value in vector)) <= 0.0:
            raise ValueError("query vector must not be all zeros")
        return tuple(vector)

    def _parse_payload(self, payload: Any, *, limit: int) -> tuple[VectorRecallEvidence, ...]:
        if not isinstance(payload, Mapping):
            raise RuntimeError("Chroma vector query returned an invalid payload")
        ids = self._one_query_row(payload.get("ids"), label="ids")
        distances = self._one_query_row(payload.get("distances"), label="distances")
        metadatas = self._one_query_row(payload.get("metadatas"), label="metadatas")
        if len(ids) > limit:
            raise RuntimeError("Chroma vector query returned more rows than requested")
        if not (len(ids) == len(distances) == len(metadatas)):
            raise RuntimeError("Chroma vector query returned mismatched row lengths")

        evidence: list[VectorRecallEvidence] = []
        seen_vector_ids: set[str] = set()
        seen_external_ids: set[str] = set()
        for vector_id_raw, distance_raw, metadata_raw in zip(ids, distances, metadatas):
            if not isinstance(vector_id_raw, str) or not vector_id_raw.strip():
                raise RuntimeError("Chroma vector query returned an invalid vector ID")
            vector_id = vector_id_raw.strip()
            if vector_id in seen_vector_ids:
                raise RuntimeError("Chroma vector query returned duplicate vector IDs")
            if not isinstance(metadata_raw, Mapping):
                raise RuntimeError("Chroma vector query returned invalid metadata")
            external_id_raw = metadata_raw.get("external_id")
            external_id = external_id_raw.strip() if isinstance(external_id_raw, str) else ""
            if not external_id:
                raise RuntimeError("Chroma vector metadata has no external ID")
            if external_id in seen_external_ids:
                raise RuntimeError("Chroma vector query returned duplicate external IDs")
            if metadata_raw.get("embedding_version") != self._embedding_version:
                raise RuntimeError("Chroma vector metadata has a mismatched embedding version")
            if metadata_raw.get("index_version") != self._index_version:
                raise RuntimeError("Chroma vector metadata has a mismatched index version")
            metadata_namespace = metadata_raw.get("namespace_name")
            if metadata_namespace is not None and metadata_namespace != self._namespace_name:
                raise RuntimeError("Chroma vector metadata has a mismatched namespace")
            metadata_vector_id = metadata_raw.get("vector_id")
            if metadata_vector_id is not None and metadata_vector_id != vector_id:
                raise RuntimeError("Chroma vector metadata has a mismatched vector ID")
            try:
                distance = float(distance_raw)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Chroma vector query returned an invalid distance") from exc
            if not math.isfinite(distance):
                raise RuntimeError("Chroma vector query returned a non-finite distance")
            cosine_similarity = 1.0 - distance
            score = max(0.0, min(1.0, (cosine_similarity + 1.0) / 2.0))
            seen_vector_ids.add(vector_id)
            seen_external_ids.add(external_id)
            evidence.append(
                VectorRecallEvidence(
                    external_id=external_id,
                    vector_id=vector_id,
                    score=round(score, 6),
                    embedding_version=self._embedding_version,
                    index_version=self._index_version,
                    namespace_name=self._namespace_name,
                )
            )
        return tuple(evidence)

    @staticmethod
    def _one_query_row(value: Any, *, label: str) -> list[Any]:
        if not isinstance(value, (list, tuple)) or len(value) != 1:
            raise RuntimeError(f"Chroma vector query returned invalid {label}")
        row = value[0]
        if not isinstance(row, (list, tuple)):
            raise RuntimeError(f"Chroma vector query returned invalid {label} row")
        return list(row)


__all__ = ["ChromaVectorReader"]
