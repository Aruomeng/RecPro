from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from scripts.verify_evaluation_freeze_inputs import (
    DEFAULT_PATHS,
    PROJECT_ROOT,
    _load_schema,
    build_evaluation_freeze_report,
    resolve_repository_path,
    validate_run_id,
)


class EvaluationFreezeInputTest(unittest.TestCase):
    def test_demo_fixture_is_explicitly_blocked_with_all_missing_inputs(self) -> None:
        missing = {
            name: PROJECT_ROOT / "data" / "evaluation" / f"missing-{name}.json"
            for name in ("license", "annotation", "split", "config")
        }
        report = build_evaluation_freeze_report(
            dataset_path=DEFAULT_PATHS["dataset"],
            license_path=missing["license"],
            annotation_path=missing["annotation"],
            split_path=missing["split"],
            config_path=missing["config"],
            git_status="",
            git_commit="0" * 40,
        )
        self.assertEqual("PASS_WITH_BLOCKERS", report["status"])
        self.assertFalse(report["paper_confirmation_ready"])
        codes = {item["code"] for item in report["blockers"]}
        self.assertTrue(
            {
                "DATASET_MANIFEST_INVALID",
                "SYNTHETIC_DATASET",
                "LICENSE_MANIFEST_MISSING",
                "ANNOTATION_MANIFEST_MISSING",
                "SPLIT_MANIFEST_MISSING",
                "CONFIG_MANIFEST_MISSING",
            }.issubset(codes)
        )
        self.assertEqual(0, report["safety"]["database_reads"])
        self.assertEqual(0, report["safety"]["database_writes"])
        self.assertEqual(0, report["safety"]["actual_delete_count"])

    def test_repository_path_rejects_traversal_and_external_absolute_path(self) -> None:
        with self.assertRaises(ValueError):
            resolve_repository_path("../outside.json", label="test")
        with self.assertRaises(ValueError):
            resolve_repository_path("/tmp/outside.json", label="test")
        self.assertTrue(
            resolve_repository_path(
                "contracts/data/g2/dataset_manifest.json",
                label="test",
            ).is_file()
        )

    def test_experiment_schemas_are_strict_about_unknown_fields(self) -> None:
        schema = _load_schema("dataset")
        instance = {
            "schema_version": "evaluation-dataset-manifest-v1",
            "manifest_version": "evaluation-dataset-v1",
            "dataset_version": "evaluation-v1",
            "track": "TRACK_J",
            "source": {
                "source_id": "source-001",
                "kind": "external",
                "name": "Example",
                "license_id": "CC-BY-4.0",
                "acquired_at": "2026-08-01T00:00:00Z",
            },
            "input_files": [
                {"path": "data/evaluation/resources.jsonl", "sha256": "a" * 64, "bytes": 1, "role": "resource"}
            ],
            "anonymization": {
                "status": "VERIFIED",
                "method": "one-way research identifier",
                "mapping_separated": True,
            },
            "counts": {"resources": 1, "anonymous_users": 0, "events": 0, "tasks": 1},
            "content_digest": "b" * 64,
            "confirmation_eligible": True,
        }
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.assertEqual([], list(validator.iter_errors(instance)))
        invalid = deepcopy(instance)
        invalid["unexpected"] = "must fail closed"
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_run_id_is_safe(self) -> None:
        self.assertEqual("evaluation-inputs-20260810-001", validate_run_id("evaluation-inputs-20260810-001"))
        with self.assertRaises(ValueError):
            validate_run_id("../overwrite")


if __name__ == "__main__":
    unittest.main()
