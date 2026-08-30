from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_stage2_identity_closure_plan import (
    APPEND_ROWS,
    CONTROLLED_UPDATE_OPERATIONS,
    MAXIMUM_CHANGES,
    TEST_READER_ID,
    TEST_READER_IDENTIFIER,
    build_plan,
    canonical,
    targets_for,
)
from scripts.execute_stage2_identity_closure import (
    dry_run_report,
    validate_plan,
)


class Stage2IdentityClosurePlanTests(unittest.TestCase):
    def test_dry_run_is_zero_write_and_exactly_bounded(self) -> None:
        report = dry_run_report()
        self.assertEqual("PASS", report["status"])
        self.assertEqual("NO_WRITE_STAGE2_IDENTITY_CLOSURE_DRY_RUN", report["mode"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_writes"])
        self.assertEqual(0, report["deepseek_requests"])
        self.assertEqual(0, report["file_deletions"])
        self.assertEqual(0, report["database_physical_deletions"])
        self.assertEqual(MAXIMUM_CHANGES, APPEND_ROWS + CONTROLLED_UPDATE_OPERATIONS)

    def test_fixed_target_allowlist_has_grouped_append_and_update_budget(self) -> None:
        targets = targets_for("stage2-reader-closure-20260831")
        self.assertEqual(32, len(targets))
        self.assertEqual(
            20, sum(item["operation"] == "APPEND" for item in targets),
        )
        self.assertEqual(
            CONTROLLED_UPDATE_OPERATIONS,
            sum(item["operation"] == "UPDATE_STATUS" for item in targets),
        )
        account_target = next(
            item for item in targets
            if item["identifier"] == f"recpro.iam_user_account:user_id={TEST_READER_ID}"
        )
        self.assertEqual("APPEND", account_target["operation"])
        self.assertEqual(1, account_target["expected_after_min_count"])
        self.assertTrue(any(TEST_READER_IDENTIFIER in item["identifier"] for item in targets))

    def test_plan_is_canonical_and_validator_accepts_current_code_boundary(self) -> None:
        commit = "69755c7" + "0" * 33
        # The builder's clean-worktree check is deliberately bypassed only in
        # this in-memory unit test; production plan generation still requires
        # a clean tree.
        with patch(
            "scripts.build_stage2_identity_closure_plan.require_clean_worktree",
        ), patch(
            "scripts.build_stage2_identity_closure_plan.current_commit",
            return_value=commit,
        ):
            plan = build_plan(
                run_id="stage2-reader-closure-20260831",
                created_at="2026-08-31T00:00:00Z",
                database_identity="mysql://127.0.0.1:62306/recpro",
            )
        unsigned = dict(plan)
        plan_hash = unsigned.pop("plan_hash")
        import hashlib
        self.assertEqual(plan_hash, hashlib.sha256(canonical(unsigned)).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            # Validation checks ancestry, so patch only that external Git
            # predicate while retaining all exact input hashes and targets.
            with patch(
                "scripts.execute_stage2_identity_closure.reviewed_commit_is_ancestor",
                return_value=True,
            ):
                validated = validate_plan(
                    path,
                    plan_id=str(plan["plan_id"]),
                    approved_hash=str(plan["plan_hash"]),
                )
        self.assertEqual(plan, validated)

    def test_validator_rejects_changed_plan_hash(self) -> None:
        commit = "69755c7" + "0" * 33
        with patch(
            "scripts.build_stage2_identity_closure_plan.require_clean_worktree",
        ), patch(
            "scripts.build_stage2_identity_closure_plan.current_commit",
            return_value=commit,
        ):
            plan = build_plan(
                run_id="stage2-reader-closure-20260831",
                created_at="2026-08-31T00:00:00Z",
                database_identity="mysql://127.0.0.1:62306/recpro",
            )
        plan["intent"] = "tampered"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            with patch(
                "scripts.execute_stage2_identity_closure.reviewed_commit_is_ancestor",
                return_value=True,
            ), self.assertRaises(ValueError):
                validate_plan(
                    path,
                    plan_id=str(plan["plan_id"]),
                    approved_hash=str(plan["plan_hash"]),
                )


if __name__ == "__main__":
    unittest.main()
