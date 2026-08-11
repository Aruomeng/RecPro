"""Deterministic query embedding used by the optional Chroma read path.

The implementation intentionally mirrors the versioned offline vector build
contract.  It has no network, file, database, or model-SDK dependency, so the
composition root can opt into vector recall without changing the default
MySQL-only path.
"""

from __future__ import annotations

import hashlib
import math
import struct
import unicodedata


class HashCharNgramQueryEmbedder:
    """Reproduce ``hash-char-ngram-v1`` vectors for user query text."""

    embedding_version = "hash-char-ngram-v1"
    dimension = 384
    _ngram_min = 2
    _ngram_max = 4

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", text).split())

    def embed(self, text: str) -> tuple[float, ...]:
        normalized = self._normalize(text)
        values = [0.0] * self.dimension
        for size in range(self._ngram_min, self._ngram_max + 1):
            for index in range(0, max(0, len(normalized) - size + 1)):
                ngram = normalized[index : index + size]
                digest = hashlib.sha256(f"{size}:{ngram}".encode("utf-8")).digest()
                bucket = int.from_bytes(digest[:8], "big") % self.dimension
                values[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            raise ValueError("query text produced an empty embedding")
        normalized_vector = tuple(value / norm for value in values)
        packed = struct.pack("<" + "f" * self.dimension, *normalized_vector)
        vector = struct.unpack("<" + "f" * self.dimension, packed)
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("query embedding contains a non-finite value")
        return vector


__all__ = ["HashCharNgramQueryEmbedder"]
