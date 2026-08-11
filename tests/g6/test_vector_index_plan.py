from __future__ import annotations

import base64
import json
from pathlib import Path
import struct
import unittest

from jsonschema import Draft202012Validator

from scripts.build_vector_index_plan import (
    DIMENSION,
    EMBEDDING_VERSION,
    build_vector_records,
    document_text,
    embedding_vector,
    vector_id,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts/data/intake/vector-index-plan.schema.json"


def catalog_row(*, external_id: str = "book:test-001") -> dict[str, object]:
    return {
        "resource_type": "BOOK",
        "external_id": external_id,
        "title": "多智能体系统与智慧图书馆",
        "authors": ["示例作者"],
        "abstract": "用于可重复测试的摘要",
        "keywords": ["多智能体", "智慧图书馆"],
        "category_code": "G25",
        "publication_year": 2025,
        "publication_date": "2025-01-01",
        "publisher_or_source": "测试出版社",
        "language": "zh-CN",
        "difficulty_level": 2,
        "availability_status": "REFERENCE_ONLY",
        "available_from": "2026-08-10 00:00:00",
        "access_url": None,
        "metadata_quality": 0.9,
        "is_classic": False,
        "metadata_version": 1,
    }


class VectorIndexPlanTests(unittest.TestCase):
    def test_document_and_embedding_are_deterministic(self) -> None:
        row = catalog_row()
        text = document_text(row)
        first = embedding_vector(text)
        second = embedding_vector(text)
        self.assertEqual("多智能体系统与智慧图书馆\n多智能体 智慧图书馆\n用于可重复测试的摘要", text)
        self.assertEqual(first, second)
        self.assertEqual(DIMENSION, len(first))
        self.assertAlmostEqual(1.0, sum(value * value for value in first), places=5)

    def test_records_are_versioned_and_decodable(self) -> None:
        row = catalog_row()
        rows, quality = build_vector_records(
            plan={"graph_version": "lib-books-v1-test"},
            rows_by_table={
                "resource_catalog": [row],
                "resource_index_state": [{
                    "external_id": row["external_id"],
                    "content_hash": "a" * 64,
                    "embedding_status": "PENDING",
                    "graph_status": "READY",
                    "graph_version": "lib-books-v1-test",
                }],
            },
            embedding_version=EMBEDDING_VERSION,
        )
        self.assertEqual([], quality["blockers"])
        self.assertEqual(1, len(rows))
        record = rows[0]
        self.assertEqual(
            vector_id(
                external_id="book:test-001",
                content_hash="a" * 64,
                metadata_version=1,
                embedding_version=EMBEDDING_VERSION,
            ),
            record["vector_id"],
        )
        decoded = base64.b64decode(record["vector_base64"])
        self.assertEqual(4 * DIMENSION, len(decoded))
        self.assertEqual(DIMENSION, len(struct.unpack("<" + "f" * DIMENSION, decoded)))
        self.assertEqual(EMBEDDING_VERSION, record["metadata"]["embedding_version"])

    def test_schema_is_valid_and_rejects_unknown_fields(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual("vector-index-plan-v1", schema["properties"]["schema_version"]["const"])
        self.assertTrue(schema["additionalProperties"] is False)


if __name__ == "__main__":
    unittest.main()
