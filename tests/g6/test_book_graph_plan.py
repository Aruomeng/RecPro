from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.build_book_graph_plan import (
    EXPECTED_FIELDS,
    PROJECT_ROOT,
    _assign_book_identities,
    build_plan,
    graph_key,
    sanitize_source_url,
)


class BookGraphPlanTest(unittest.TestCase):
    def test_source_url_drops_query_but_keeps_provenance_hash(self) -> None:
        safe, digest = sanitize_source_url("https://example.invalid/book?id=secret-token#fragment")
        self.assertEqual("https://example.invalid/book", safe)
        self.assertIsNotNone(digest)
        self.assertNotIn("secret-token", safe or "")

    def test_conflicting_isbn_uses_content_variant_identity(self) -> None:
        records = [
            {"isbn": "9780000000001", "core_digest": "a" * 64},
            {"isbn": "9780000000001", "core_digest": "b" * 64},
        ]
        summary = _assign_book_identities(records)
        self.assertEqual(1, summary["isbn_conflict_group_count"])
        self.assertEqual(2, summary["isbn_conflicting_record_count"])
        self.assertNotEqual(records[0]["book_entity_id"], records[1]["book_entity_id"])
        self.assertTrue(all(item["identity_strategy"] == "ISBN_VARIANT_CONTENT_FINGERPRINT" for item in records))

    def test_graph_plan_has_unique_occurrence_records_and_no_null_properties(self) -> None:
        values = {field: "" for field in EXPECTED_FIELDS}
        values.update(
            {
                "题名": "多智能体系统导论",
                "作者": "示例作者 著",
                "出版社": "示例出版社",
                "发行时间": "2024-03",
                "ISBN号": "9780000000001",
                "页数": "200",
                "原书定价": "58.00",
                "主题词": "多智能体, 推荐",
                "中图法分类号": "TP18",
                "详情页Url": "https://example.invalid/book?id=token",
            }
        )
        record_base = {
            "source_id": "lib-duixiu-scrape",
            "source_file": "Lib/T-工业技术/人工智能.csv",
            "source_file_sha256": "f" * 64,
            "values": values,
            "isbn": "9780000000001",
            "isbn_raw": "9780000000001",
            "authors": [{"name": "示例作者", "role": "著", "raw": "示例作者 著"}],
            "keywords": ["多智能体", "推荐"],
            "subject_code": "TP18",
            "category_code": "T",
            "category_name": "工业技术",
            "topic_name": "人工智能",
            "publication_year": 2024,
            "publication_month": 3,
            "pages": 200,
            "list_price": 58.0,
            "safe_url": "https://example.invalid/book",
            "url_sha256": "e" * 64,
            "core_digest": "a" * 64,
        }
        first = {
            **record_base,
            "source_line": 2,
            "raw_record_sha256": "1" * 64,
            "source_record_id": "record:first",
        }
        second = {
            **record_base,
            "source_line": 3,
            "raw_record_sha256": "1" * 64,
            "source_record_id": "record:second",
        }
        file_summaries = [{"path": record_base["source_file"], "sha256": "f" * 64, "bytes": 10, "record_count": 2}]
        with patch(
            "scripts.build_book_graph_plan._parse_rows",
            return_value=([first, second], file_summaries, []),
        ):
            plan = build_plan(
                input_root=PROJECT_ROOT / "Lib",
                graph_version="lib-books-test-v1",
                source_license_status="PENDING_USER_CONFIRMATION",
            )
        nodes = plan.pop("_nodes")
        triples = plan.pop("_triples")
        source_records = [node for node in nodes if node["label"] == "SourceRecord"]
        self.assertEqual(2, len(source_records))
        self.assertEqual(2, len({node["entity_id"] for node in source_records}))
        self.assertTrue(all(value is not None for node in nodes for value in node["properties"].values()))
        self.assertEqual(2, plan["input"]["record_count"])
        self.assertGreater(len(triples), 0)

    def test_graph_key_is_stable_and_version_scoped(self) -> None:
        first = graph_key("graph-v1", "Book", "book:isbn:9780000000001")
        second = graph_key("graph-v1", "Book", "book:isbn:9780000000001")
        other = graph_key("graph-v2", "Book", "book:isbn:9780000000001")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)


if __name__ == "__main__":
    unittest.main()
