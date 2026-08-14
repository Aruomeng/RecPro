from __future__ import annotations

import hashlib
import unittest
from uuid import uuid4

from scripts.build_g8_final_revalidation_plan import canonical_json
from scripts.reconcile_g8_approved_write_evidence import WRITE_CASE_IDS, validate_source_pair
from scripts.verify_g8_final_revalidation_plan import RUNTIME_ARTIFACT_SCHEMAS


class ApprovedWriteReconciliationTests(unittest.TestCase):
    def source_plan(self, classification: str = "S1_APPEND") -> dict[str, object]:
        plan: dict[str, object] = {
            "plan_id": str(uuid4()),
            "classification": classification,
            "mode": "DRY_RUN",
        }
        plan["plan_hash"] = hashlib.sha256(canonical_json(plan)).hexdigest()
        return plan

    def test_exact_plan_apply_pair_is_accepted(self) -> None:
        plan = self.source_plan()
        apply = {
            "status": "PASS",
            "approved_plan_id": plan["plan_id"],
            "approved_plan_hash": plan["plan_hash"],
            "actual_delete_count": 0,
            "files_deleted": 0,
            "external_llm_requests": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
        }
        reference = validate_source_pair(plan, apply, classification="S1_APPEND")
        self.assertEqual(plan["plan_hash"], reference["plan_hash"])
        self.assertEqual("S1_APPEND", reference["classification"])

    def test_pair_rejects_unapproved_external_llm_request(self) -> None:
        plan = self.source_plan()
        apply = {
            "status": "PASS",
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "actual_delete_count": 0,
            "files_deleted": 0,
            "external_llm_requests": 1,
        }
        with self.assertRaisesRegex(ValueError, "external_llm_requests"):
            validate_source_pair(plan, apply, classification="S1_APPEND")

    def test_write_case_set_and_runtime_schema_are_frozen(self) -> None:
        self.assertEqual(
            ("A02", "A03", "A04", "A07", "A08", "A09", "A10", "A23"),
            WRITE_CASE_IDS,
        )
        self.assertIn("g8-approved-write-reconciliation-v1", RUNTIME_ARTIFACT_SCHEMAS)


if __name__ == "__main__":
    unittest.main()
