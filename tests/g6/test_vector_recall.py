from __future__ import annotations

import asyncio
from pathlib import Path
import unittest

from backend.app.catalog.adapters.chroma import ChromaVectorReader


EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"
NAMESPACE = "library_resources__hash_char_ngram_v1"


class FakeCollection:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload or {
            "ids": [["vec-one", "vec-two"]],
            "distances": [[0.0, 0.5]],
            "metadatas": [[
                {
                    "external_id": "book:one",
                    "vector_id": "vec-one",
                    "embedding_version": EMBEDDING_VERSION,
                    "index_version": INDEX_VERSION,
                    "namespace_name": NAMESPACE,
                },
                {
                    "external_id": "book:two",
                    "vector_id": "vec-two",
                    "embedding_version": EMBEDDING_VERSION,
                    "index_version": INDEX_VERSION,
                    "namespace_name": NAMESPACE,
                },
            ]],
        }
        self.error = error
        self.calls: list[dict[str, object]] = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.payload


def reader(collection: FakeCollection, *, dimension: int = 384, timeout: float = 5.0) -> ChromaVectorReader:
    return ChromaVectorReader(
        collection=collection,
        namespace_name=NAMESPACE,
        embedding_version=EMBEDDING_VERSION,
        index_version=INDEX_VERSION,
        dimension=dimension,
        timeout=timeout,
    )


class VectorRecallTests(unittest.TestCase):
    def test_reader_queries_one_versioned_collection_and_maps_cosine_distance(self) -> None:
        collection = FakeCollection()
        result = asyncio.run(
            reader(collection).recall(
                query_vector=(1.0,) + (0.0,) * 383,
                embedding_version=EMBEDDING_VERSION,
                index_version=INDEX_VERSION,
                limit=5,
            )
        )
        self.assertEqual(("book:one", "book:two"), tuple(item.external_id for item in result))
        self.assertEqual((1.0, 0.75), tuple(item.score for item in result))
        self.assertEqual(5, collection.calls[0]["n_results"])
        self.assertEqual(
            {"$and": [
                {"embedding_version": EMBEDDING_VERSION},
                {"index_version": INDEX_VERSION},
            ]},
            collection.calls[0]["where"],
        )
        self.assertEqual(["distances", "metadatas"], collection.calls[0]["include"])

    def test_reader_rejects_wrong_version_limit_and_dimension(self) -> None:
        collection = FakeCollection()
        with self.assertRaises(ValueError):
            asyncio.run(
                reader(collection).recall(
                    query_vector=(1.0,) + (0.0,) * 383,
                    embedding_version="other-embedding-v1",
                    index_version=INDEX_VERSION,
                    limit=5,
                )
            )
        with self.assertRaises(ValueError):
            asyncio.run(
                reader(collection).recall(
                    query_vector=(1.0,) + (0.0,) * 383,
                    embedding_version=EMBEDDING_VERSION,
                    index_version=INDEX_VERSION,
                    limit=51,
                )
            )
        with self.assertRaises(ValueError):
            asyncio.run(
                reader(collection).recall(
                    query_vector=(1.0,),
                    embedding_version=EMBEDDING_VERSION,
                    index_version=INDEX_VERSION,
                    limit=5,
                )
            )

    def test_reader_fails_closed_on_store_error_and_malformed_metadata(self) -> None:
        failing = FakeCollection(error=RuntimeError("store unavailable"))
        with self.assertRaises(ConnectionError):
            asyncio.run(
                reader(failing).recall(
                    query_vector=(1.0,) + (0.0,) * 383,
                    embedding_version=EMBEDDING_VERSION,
                    index_version=INDEX_VERSION,
                    limit=5,
                )
            )
        malformed = FakeCollection()
        malformed.payload["metadatas"][0][0]["index_version"] = "wrong-index-v1"
        with self.assertRaises(RuntimeError):
            asyncio.run(
                reader(malformed).recall(
                    query_vector=(1.0,) + (0.0,) * 383,
                    embedding_version=EMBEDDING_VERSION,
                    index_version=INDEX_VERSION,
                    limit=5,
                )
            )

    def test_adapter_has_no_collection_write_calls(self) -> None:
        source = Path("backend/app/catalog/adapters/chroma.py").read_text(encoding="utf-8")
        for method in (
            "self._collection.add(",
            "self._collection.upsert(",
            "self._collection." + "del" + "ete(",
            "self._collection.reset(",
            "self._collection.modify(",
        ):
            with self.subTest(method=method):
                self.assertNotIn(method, source)


if __name__ == "__main__":
    unittest.main()
