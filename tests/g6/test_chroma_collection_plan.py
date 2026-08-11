from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_chroma_collection_plan import SCHEMA_VERSION
from scripts.verify_chroma_collection_plan import verify_collection_plan


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts/data/intake/chroma-collection-plan.schema.json"
PLAN_PATH = ROOT / (
    "artifacts/verification/chroma-collection-plan/"
    "chroma-collection-plan-20260811-001/chroma-collection-plan.json"
)


class ChromaCollectionPlanTests(unittest.TestCase):
    def test_schema_is_strict_and_has_write_authorization_gate(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(SCHEMA_VERSION, schema["properties"]["schema_version"]["const"])
        self.assertFalse(schema["additionalProperties"])
        client = schema["properties"]["client"]["properties"]
        self.assertTrue(client["write_authorization_required"]["const"])

    def test_local_plan_verifies_without_store_access(self) -> None:
        if not PLAN_PATH.is_file():
            self.skipTest("local Chroma collection plan evidence is not present")
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            [],
            list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan)),
        )
        report = verify_collection_plan(PLAN_PATH)
        self.assertEqual("PASS", report["status"])
        self.assertEqual("library_resources__hash_char_ngram_v1", report["collection_name"])
        self.assertEqual(14983, report["record_count"])
        self.assertEqual(0, report["external_store_writes"])
        self.assertEqual(0, report["actual_delete_count"])


if __name__ == "__main__":
    unittest.main()
