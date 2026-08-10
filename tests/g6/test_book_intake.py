from __future__ import annotations

from copy import deepcopy
import json
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from scripts.inspect_book_intake import (
    DEFAULT_MANIFEST,
    MANIFEST_SCHEMA,
    PROJECT_ROOT,
    RECORD_SCHEMA,
    build_intake_report,
    resolve_repository_path,
    validate_record,
    validate_run_id,
)


class BookIntakeTest(unittest.TestCase):
    def test_missing_user_input_is_blocked_without_database_access(self) -> None:
        report = build_intake_report(
            manifest_path=DEFAULT_MANIFEST,
            git_commit="0" * 40,
            git_worktree_dirty=False,
        )
        self.assertEqual("PASS_WITH_BLOCKERS", report["status"])
        self.assertFalse(report["can_import"])
        self.assertIn("INTAKE_MANIFEST_MISSING", {item["code"] for item in report["blockers"]})
        self.assertEqual(0, report["safety"]["database_reads"])
        self.assertEqual(0, report["safety"]["database_writes"])
        self.assertEqual(0, report["safety"]["actual_delete_count"])

    def test_normalized_record_schema_rejects_unknown_scraper_fields(self) -> None:
        record = {
            "schema_version": "library-book-record-v1",
            "source_id": "books-source-001",
            "source_record_id": "book-001",
            "title": "多智能体系统导论",
            "authors": ["示例作者"],
            "retrieved_at": "2026-08-10T00:00:00Z",
            "availability_status": "AVAILABLE_BORROW",
        }
        schema = json.loads(RECORD_SCHEMA.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.assertEqual([], list(validator.iter_errors(record)))
        invalid = deepcopy(record)
        invalid["raw_html"] = "must be normalized before import"
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_record_source_and_duplicate_tag_checks_are_explicit(self) -> None:
        record = {
            "schema_version": "library-book-record-v1",
            "source_id": "wrong-source",
            "source_record_id": "book-001",
            "title": "多智能体系统导论",
            "authors": ["示例作者"],
            "retrieved_at": "2026-08-10T00:00:00Z",
            "availability_status": "AVAILABLE_BORROW",
            "license_id": "CC-BY-4.0",
            "tags": [
                {"name": "多智能体", "normalized_name": "multi-agent", "weight": 1, "confidence": 1},
                {"name": "多智能体", "normalized_name": "multi-agent", "weight": 0.9, "confidence": 0.8},
            ],
        }
        codes = {
            issue["code"]
            for issue in validate_record(
                record,
                expected_source_id="books-source-001",
                expected_license_id="CC0-1.0",
            )
        }
        self.assertIn("RECORD_SOURCE_MISMATCH", codes)
        self.assertIn("RECORD_LICENSE_MISMATCH", codes)
        self.assertIn("RECORD_DUPLICATE_TAG", codes)

    def test_intake_manifest_schema_is_strict(self) -> None:
        schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
        instance = {
            "schema_version": "library-book-intake-manifest-v1",
            "manifest_version": "library-book-intake-v1",
            "intake_id": "books-intake-001",
            "source": {
                "source_id": "books-source-001",
                "kind": "user_provided_scrape",
                "name": "User supplied book metadata",
                "license_id": "CC-BY-4.0",
                "license_evidence_ref": "https://example.invalid/license",
            },
            "input_file": {
                "path": "data/incoming/books/books.jsonl",
                "sha256": "a" * 64,
                "bytes": 1,
                "format": "JSONL",
                "encoding": "UTF-8",
            },
            "record_schema_version": "library-book-record-v1",
            "normalization": {
                "status": "NORMALIZED",
                "parser_version": "books-parser-v1",
                "mapping_version": "books-map-v1",
            },
            "privacy": {
                "status": "NOT_REQUIRED",
                "contains_user_data": False,
                "identity_mapping_separated": True,
            },
            "destinations": {"mysql_resource_catalog": True, "neo4j_graph_plan": True},
            "confirmation_eligible": False,
            "created_at": "2026-08-10T00:00:00Z",
        }
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.assertEqual([], list(validator.iter_errors(instance)))
        invalid = deepcopy(instance)
        invalid["unknown"] = "reject"
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_repository_paths_and_run_ids_are_safe(self) -> None:
        self.assertTrue(resolve_repository_path("contracts/data/intake/book-record.schema.json", label="test").is_file())
        with self.assertRaises(ValueError):
            resolve_repository_path("../outside.json", label="test")
        with self.assertRaises(ValueError):
            validate_run_id("../overwrite")


if __name__ == "__main__":
    unittest.main()
