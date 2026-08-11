from __future__ import annotations

import hashlib
import base64
import struct
from pathlib import Path
import unittest

from scripts.import_chroma_vectors import (
    DIMENSION,
    _compare_embedding,
    _decode_vector,
    _metadata_for_record,
    _payload,
)


EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"
NAMESPACE = "library_resources__hash_char_ngram_v1"
GRAPH_VERSION = "lib-books-v1-20260810"


def _plan() -> dict[str, object]:
    return {
        "embedding_version": EMBEDDING_VERSION,
        "index_version": INDEX_VERSION,
        "namespace_name": NAMESPACE,
        "metadata_contract": {
            "required_fields": [
                "external_id",
                "vector_id",
                "resource_type",
                "content_hash",
                "metadata_version",
                "embedding_version",
                "index_version",
                "namespace_name",
                "graph_version",
                "category_code",
                "publication_year",
                "difficulty_level",
                "available_from_epoch",
            ]
        },
    }


def _record() -> dict[str, object]:
    values = (1.0,) + (0.0,) * (DIMENSION - 1)
    packed = struct.pack("<" + "f" * DIMENSION, *values)
    document = "测试图书\n文学"
    content_hash = "a" * 64
    return {
        "content_hash": content_hash,
        "dimension": DIMENSION,
        "document": document,
        "document_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "embedding_version": EMBEDDING_VERSION,
        "external_id": "book:test",
        "metadata": {
            "available_from_epoch": 1786320000,
            "category_code": "I",
            "difficulty_level": 0,
            "embedding_version": EMBEDDING_VERSION,
            "graph_version": GRAPH_VERSION,
            "metadata_version": 1,
            "publication_year": 2024,
            "resource_type": "BOOK",
        },
        "metadata_version": 1,
        "resource_type": "BOOK",
        "vector_base64": base64.b64encode(packed).decode("ascii"),
        "vector_encoding": "float32-little-endian-base64",
        "vector_id": "vec-test",
        "vector_sha256": hashlib.sha256(packed).hexdigest(),
    }


class ChromaImportTests(unittest.TestCase):
    def test_payload_binds_identity_versions_and_hashes(self) -> None:
        record = _record()
        plan = _plan()
        vector_id, vector, metadata, document = _payload(
            record, collection_plan=plan, graph_version=GRAPH_VERSION
        )
        self.assertEqual("vec-test", vector_id)
        self.assertEqual(DIMENSION, len(vector))
        self.assertEqual("book:test", metadata["external_id"])
        self.assertEqual(EMBEDDING_VERSION, metadata["embedding_version"])
        self.assertEqual(INDEX_VERSION, metadata["index_version"])
        self.assertEqual(NAMESPACE, metadata["namespace_name"])
        self.assertEqual(record["document"], document)

    def test_decode_rejects_wrong_dimension_and_document_metadata_hash(self) -> None:
        record = _record()
        wrong_dimension = dict(record, dimension=DIMENSION - 1)
        with self.assertRaises(ValueError):
            _decode_vector(wrong_dimension)
        broken_document = dict(record, document_sha256="b" * 64)
        with self.assertRaises(ValueError):
            _metadata_for_record(
                broken_document, collection_plan=_plan(), graph_version=GRAPH_VERSION
            )

    def test_embedding_verification_allows_cosine_float_round_trip_but_rejects_drift(self) -> None:
        source = [1.0] + [0.0] * (DIMENSION - 1)
        absolute_error, l2_error = _compare_embedding(source, [1.0 - 1e-8] + [0.0] * (DIMENSION - 1), "test")
        self.assertLess(absolute_error, 2e-6)
        self.assertLess(l2_error, 2e-5)
        with self.assertRaises(RuntimeError):
            _compare_embedding(source, [0.0] * DIMENSION, "test")

    def test_operator_importer_has_no_collection_lifecycle_delete_or_reset(self) -> None:
        source = Path("scripts/import_chroma_vectors.py").read_text(encoding="utf-8")
        for method in (
            "." + "del" + "ete(",
            "." + "re" + "set(",
            "." + "mod" + "ify(",
            "." + "up" + "sert(",
        ):
            with self.subTest(method=method):
                self.assertNotIn(method, source)


if __name__ == "__main__":
    unittest.main()
