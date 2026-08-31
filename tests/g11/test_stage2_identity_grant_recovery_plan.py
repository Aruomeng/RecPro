from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_stage2_identity_grant_recovery_plan import (
    APPEND_ROWS,
    CONTROLLED_UPDATE_OPERATIONS,
    GRANT_OPERATIONS,
    MAXIMUM_CHANGES,
    PARTIAL_BASELINE,
    TEST_READER_ID,
    TEST_READER_IDENTIFIER,
    build_plan,
    canonical,
    targets_for,
)
from scripts.execute_stage2_identity_grant_recovery import (
    dry_run_report,
    validate_plan,
)


class Stage2IdentityGrantRecoveryPlanTests(unittest.TestCase):
    def test_dry_run_has_no_database_or_container_side_effect(self) -> None:
        report = dry_run_report()
        self.assertEqual("PASS", report["status"])
        self.assertEqual("NO_WRITE_STAGE2_IDENTITY_GRANT_RECOVERY_DRY_RUN", report["mode"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_writes"])
        self.assertEqual(0, report["deepseek_requests"])
        self.assertEqual(0, report["container_deletions"])
        self.assertEqual(MAXIMUM_CHANGES, GRANT_OPERATIONS + APPEND_ROWS + CONTROLLED_UPDATE_OPERATIONS)

    def test_allowlist_contains_exact_grants_and_forward_only_operations(self) -> None:
        targets = targets_for("stage2-reader-grant-recovery-20260831")
        self.assertEqual(25, len(targets))
        self.assertEqual(GRANT_OPERATIONS, sum(item["operation"] == "UPDATE_STATUS" and "GRANT:" in item["identifier"] for item in targets))
        self.assertEqual(APPEND_ROWS, sum(item["operation"] == "APPEND" for item in targets))
        self.assertEqual(CONTROLLED_UPDATE_OPERATIONS, sum(item["operation"] == "UPDATE_STATUS" and "GRANT:" not in item["identifier"] for item in targets))
        self.assertEqual(3, sum(item["operation"] == "READ" for item in targets))
        grant_ids = {item["identifier"] for item in targets if "GRANT:" in item["identifier"]}
        self.assertEqual({
            "recpro_identity@%:GRANT:recpro.user_declared_profile:SELECT,INSERT,UPDATE",
            "recpro_identity@%:GRANT:recpro.user_declared_profile_history:SELECT,INSERT",
        }, grant_ids)
        self.assertTrue(any(TEST_READER_IDENTIFIER in item["identifier"] for item in targets))
        self.assertTrue(any(f"user_id={TEST_READER_ID}" in item["identifier"] for item in targets))
        self.assertEqual(4, PARTIAL_BASELINE["iam_auth_session"])

    def test_plan_hash_and_validator_are_exact(self) -> None:
        commit = "69755c7" + "0" * 33
        with patch(
            "scripts.build_stage2_identity_grant_recovery_plan.require_clean_worktree",
        ), patch(
            "scripts.build_stage2_identity_grant_recovery_plan.current_commit",
            return_value=commit,
        ):
            plan = build_plan(
                run_id="stage2-reader-grant-recovery-20260831",
                created_at="2026-08-31T00:00:00Z",
                database_identity="mysql://127.0.0.1:62306/recpro",
            )
        unsigned = dict(plan)
        plan_hash = unsigned.pop("plan_hash")
        self.assertEqual(plan_hash, hashlib.sha256(canonical(unsigned)).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            with patch(
                "scripts.execute_stage2_identity_grant_recovery.reviewed_commit_is_ancestor",
                return_value=True,
            ):
                validated = validate_plan(
                    path,
                    plan_id=str(plan["plan_id"]),
                    approved_hash=str(plan["plan_hash"]),
                )
        self.assertEqual(plan, validated)


if __name__ == "__main__":
    unittest.main()
