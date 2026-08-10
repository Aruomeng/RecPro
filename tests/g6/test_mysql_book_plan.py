from __future__ import annotations

import json
from datetime import UTC
import logging
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_mysql_book_plan import (
    build_plan,
    build_rows,
    parse_available_from,
    tag_key,
)
from scripts.import_mysql_book_catalog import _ExpectedDuplicateWarningFilter


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts/data/intake/mysql-book-plan.schema.json"


class MySQLBookPlanTests(unittest.TestCase):
    def test_available_time_is_normalized_to_utc_without_timezone_leak(self) -> None:
        date_value, datetime_value = parse_available_from("2026-08-10T08:00:00+08:00")
        self.assertEqual("2026-08-10", date_value)
        self.assertEqual("2026-08-10 00:00:00", datetime_value)

    def test_available_time_requires_timezone(self) -> None:
        with self.assertRaises(ValueError):
            parse_available_from("2026-08-10T00:00:00")

    def test_tag_keys_are_stable_and_kind_scoped(self) -> None:
        self.assertEqual(tag_key("kw", "知识图谱"), tag_key("kw", "知识图谱"))
        self.assertNotEqual(tag_key("kw", "知识图谱"), tag_key("topic", "知识图谱"))

    def test_rows_are_deterministic_and_keep_missing_optional_values_null(self) -> None:
        graph_plan = {
            "graph_version": "lib-books-v1-test",
            "status": "PASS_WITH_WARNINGS",
        }
        nodes = [
            {
                "graph_key": "book-key",
                "entity_id": "book:test-001",
                "label": "Book",
                "properties": {
                    "title": "多智能体系统导论",
                    "summary": "用于测试",
                    "publication_year": 2026,
                    "publication_month": 8,
                    "isbn": "9787300000000",
                    "source_url": "https://example.invalid/book",
                    "subject_raw": "TP391",
                },
            },
            {
                "graph_key": "author-key",
                "entity_id": "author:test-001",
                "label": "Author",
                "properties": {"name": "示例作者"},
            },
            {
                "graph_key": "topic-key",
                "entity_id": "topic:test-001",
                "label": "Topic",
                "properties": {"name": "多智能体"},
            },
            {
                "graph_key": "subject-key",
                "entity_id": "subject:test-001",
                "label": "SubjectCode",
                "properties": {"code": "TP391"},
            },
        ]
        triples = [
            {"subject_key": "book-key", "object_key": "author-key", "predicate": "AUTHORED_BY"},
            {"subject_key": "book-key", "object_key": "topic-key", "predicate": "IN_TOPIC"},
            {"subject_key": "book-key", "object_key": "subject-key", "predicate": "HAS_SUBJECT_CODE"},
        ]
        rows, blockers, warnings = build_rows(
            plan=graph_plan,
            nodes=nodes,
            triples=triples,
            available_from="2026-08-10 00:00:00",
        )
        self.assertEqual([], blockers)
        self.assertEqual("SOURCE_GRAPH_WARNING", warnings[0]["code"])
        self.assertEqual("BOOK", rows["resource_catalog"][0]["resource_type"])
        self.assertIsNone(rows["resource_catalog"][0]["language"])
        self.assertEqual("2026-08-01", rows["resource_catalog"][0]["publication_date"])
        self.assertEqual(2, len(rows["resource_tag"]))
        self.assertEqual(rows, build_rows(
            plan=graph_plan,
            nodes=list(reversed(nodes)),
            triples=list(reversed(triples)),
            available_from="2026-08-10 00:00:00",
        )[0])

    def test_schema_accepts_generated_plan_shape_and_rejects_unknown_fields(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        plan_dir = ROOT / "artifacts/verification/mysql-book-plan/mysql-book-plan-20260810-001"
        plan_path = plan_dir / "mysql-book-plan.json"
        if not plan_path.is_file():
            self.skipTest("local MySQL plan evidence is not present")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.assertEqual([], list(validator.iter_errors(plan)))
        invalid = dict(plan)
        invalid["unexpected"] = True
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_duplicate_warning_filter_keeps_unexpected_messages_visible(self) -> None:
        warning_filter = _ExpectedDuplicateWarningFilter()
        duplicate = logging.LogRecord("asyncmy", logging.WARNING, __file__, 1, "Duplicate entry 'x'", (), None)
        other = logging.LogRecord("asyncmy", logging.WARNING, __file__, 1, "Unexpected server warning", (), None)
        self.assertFalse(warning_filter.filter(duplicate))
        self.assertTrue(warning_filter.filter(other))


if __name__ == "__main__":
    unittest.main()
