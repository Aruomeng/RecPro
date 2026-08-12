from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from scripts.build_g8_final_revalidation_plan import build_plan, validate_plan
from scripts.verify_g8_final_revalidation_plan import (
    _case_results,
    _validate_runtime_evidence_payload,
    _validate_instance,
    AUDIT_SCHEMA_PATH,
    RUNTIME_EVIDENCE_SCHEMA_PATH,
    validate_run_id,
)


class FinalRevalidationAuditTest(unittest.TestCase):
    def test_missing_runtime_envelope_keeps_cases_pending_without_promoting_history(self) -> None:
        plan = build_plan(
            run_id="g8-final-revalidation-audit-test-001",
            git_commit="a" * 40,
        )
        self.assertEqual([], validate_plan(plan))
        cases = _case_results(plan, None)
        self.assertEqual(25, len(cases))
        self.assertEqual({"PENDING"}, {item["final_revalidation"] for item in cases})
        self.assertEqual(17, sum(item["execution_mode"] == "READ_ONLY_RUNTIME" for item in cases))
        self.assertEqual(8, sum(item["authorization"] == "SEPARATE_EXACT_CHANGE_PLAN" for item in cases))
        self.assertTrue(all(item["historical_artifact_count"] >= 0 for item in cases))
        self.assertTrue(all("final_runtime_evidence_not_supplied" in item["blockers"] for item in cases))

    def test_runtime_envelope_case_statuses_are_consumed_only_when_present(self) -> None:
        plan = build_plan(
            run_id="g8-final-revalidation-audit-test-002",
            git_commit="b" * 40,
        )
        evidence = {
            "cases": [
                {
                    "case_id": f"A{index:02d}",
                    "status": "PASS" if index == 1 else "PENDING",
                    "artifacts": [],
                }
                for index in range(1, 26)
            ]
        }
        cases = _case_results(plan, evidence)
        self.assertEqual("PASS", cases[0]["final_revalidation"])
        self.assertEqual("PENDING", cases[1]["final_revalidation"])
        self.assertNotIn("final_runtime_evidence_not_supplied", cases[0]["blockers"])
        self.assertIn("final_runtime_evidence_pending", cases[1]["blockers"])
        self.assertIn("separate_exact_change_plan_required", cases[1]["blockers"])

    def test_audit_and_runtime_schemas_are_valid_contracts(self) -> None:
        self.assertEqual([], _validate_instance(AUDIT_SCHEMA_PATH, {
            "schema_version": "g8-final-revalidation-audit-v1",
            "status": "READY_FOR_RUNTIME",
            "run_id": "audit-contract-test-001",
            "audited_at": "2026-08-12T00:00:00Z",
            "git": {"current_commit": "a" * 40, "status_before_report": ""},
            "plan": {
                "path": "plan.json",
                "sha256": "a" * 64,
                "plan_hash": "b" * 64,
                "plan_git_commit": "a" * 40,
                "plan_git_matches_current": True,
                "validation_status": "PASS",
            },
            "coverage_counts": {
                "total": 25,
                "plan_valid": 25,
                "read_only_ready": 17,
                "requires_change_plan": 8,
                "final_pass": 0,
                "final_fail": 0,
                "final_pending": 25,
                "historical_artifact_cases": 0,
            },
            "cases": [
                {
                    "case_id": f"A{index:02d}",
                    "execution_mode": "READ_ONLY_RUNTIME",
                    "authorization": "NONE",
                    "offline_refs_valid": True,
                    "runtime_refs_valid": True,
                    "historical_artifact_count": 0,
                    "final_revalidation": "PENDING",
                    "final_evidence_paths": [],
                    "blockers": ["final_runtime_evidence_not_supplied"],
                }
                for index in range(1, 26)
            ],
            "browser_scenarios": [
                {
                    "scenario_id": "cold_user_guided",
                    "fixture_user": "demo_cold",
                    "state": "BLOCKED_NO_CHANGE_PLAN",
                    "write_policy": "REQUIRES_SEPARATE_CHANGE_PLAN",
                }
                for _ in range(6)
            ],
            "blockers": ["pending"],
            "safety": {
                "database_reads": 0,
                "database_writes": 0,
                "neo4j_reads": 0,
                "neo4j_writes": 0,
                "chroma_reads": 0,
                "chroma_writes": 0,
                "outbox_claims": 0,
                "external_llm_requests": 0,
                "files_deleted": 0,
                "database_physical_deletions": 0,
                "artifact_overwrites": 0,
            },
        }))
        self.assertEqual([], _validate_instance(RUNTIME_EVIDENCE_SCHEMA_PATH, {
            "schema_version": "g8-final-runtime-evidence-v1",
            "plan_run_id": "plan-contract-test-001",
            "plan_hash": "a" * 64,
            "git_commit": "b" * 40,
            "status": "PENDING",
            "safety": {
                "database_reads": 0,
                "database_writes": 0,
                "neo4j_reads": 0,
                "neo4j_writes": 0,
                "chroma_reads": 0,
                "chroma_writes": 0,
                "outbox_claims": 0,
                "external_llm_requests": 0,
                "files_deleted": 0,
                "database_physical_deletions": 0,
                "artifact_overwrites": 0,
            },
            "cases": [
                {
                    "case_id": f"A{index:02d}",
                    "status": "PENDING",
                    "artifacts": [],
                    "observations": {},
                    "change_plan": None,
                }
                for index in range(1, 26)
            ],
        }))

    def test_run_id_rejects_path_traversal(self) -> None:
        self.assertEqual("g8-final-revalidation-audit-20260812-001", validate_run_id("g8-final-revalidation-audit-20260812-001"))
        with self.assertRaises(ValueError):
            validate_run_id("../overwrite")

    def test_runtime_loader_rejects_pass_without_verifiable_artifact(self) -> None:
        plan = build_plan(
            run_id="g8-final-revalidation-audit-test-003",
            git_commit="c" * 40,
        )
        payload = {
            "schema_version": "g8-final-runtime-evidence-v1",
            "plan_run_id": plan["run_id"],
            "plan_hash": plan["plan_hash"],
            "git_commit": plan["git_commit"],
            "status": "PENDING",
            "safety": {
                "database_reads": 0,
                "database_writes": 0,
                "neo4j_reads": 0,
                "neo4j_writes": 0,
                "chroma_reads": 0,
                "chroma_writes": 0,
                "outbox_claims": 0,
                "external_llm_requests": 0,
                "files_deleted": 0,
                "database_physical_deletions": 0,
                "artifact_overwrites": 0,
            },
            "cases": [
                {
                    "case_id": f"A{index:02d}",
                    "status": "PASS" if index == 1 else "PENDING",
                    "artifacts": [],
                    "observations": {},
                    "change_plan": None,
                }
                for index in range(1, 26)
            ],
        }
        issues = _validate_runtime_evidence_payload(payload, plan)
        self.assertIn("A01 PASS requires at least one artifact", issues)

    def test_runtime_loader_verifies_artifact_hash_and_schema(self) -> None:
        plan = build_plan(
            run_id="g8-final-revalidation-audit-test-004",
            git_commit="d" * 40,
        )
        artifact_path = Path("tests/fixtures/g8/runtime-artifact.json")
        artifact_bytes = artifact_path.read_bytes()
        payload = {
            "schema_version": "g8-final-runtime-evidence-v1",
            "plan_run_id": plan["run_id"],
            "plan_hash": plan["plan_hash"],
            "git_commit": plan["git_commit"],
            "status": "PENDING",
            "safety": {
                "database_reads": 0,
                "database_writes": 0,
                "neo4j_reads": 0,
                "neo4j_writes": 0,
                "chroma_reads": 0,
                "chroma_writes": 0,
                "outbox_claims": 0,
                "external_llm_requests": 0,
                "files_deleted": 0,
                "database_physical_deletions": 0,
                "artifact_overwrites": 0,
            },
            "cases": [
                {
                    "case_id": f"A{index:02d}",
                    "status": "PASS" if index == 1 else "PENDING",
                    "artifacts": ([{
                        "path": artifact_path.as_posix(),
                        "schema_version": "test-artifact-v1",
                        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                    }] if index == 1 else []),
                    "observations": {},
                    "change_plan": None,
                }
                for index in range(1, 26)
            ],
        }
        issues = _validate_runtime_evidence_payload(payload, plan)
        self.assertEqual([], issues)


if __name__ == "__main__":
    unittest.main()
