from __future__ import annotations

import hashlib
import json
import unittest

from scripts.build_g11_identity_change_plan import build_plan
from scripts.execute_g11_identity_migration import (
    IAM_TABLES,
    IAM_VIEWS,
    MAXIMUM_ROWS,
    REQUIRED_INPUT_PATHS,
    canonical,
    dry_run_report,
)


class IdentityChangePlanTests(unittest.TestCase):
    def test_dry_run_is_zero_connection_and_zero_write(self) -> None:
        report = dry_run_report()
        self.assertEqual("NO_WRITE_DRY_RUN", report["mode"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_writes"])
        self.assertEqual(0, report["deepseek_requests"])
        self.assertEqual(MAXIMUM_ROWS, report["maximum_rows"])

    def test_builder_freezes_exact_schema_seed_and_hash_boundary(self) -> None:
        plan = build_plan(
            reviewed_commit="a" * 40,
            created_at="2026-08-21T08:30:00Z",
        )
        unsigned = dict(plan)
        expected_hash = str(unsigned.pop("plan_hash"))
        self.assertEqual(expected_hash, hashlib.sha256(canonical(unsigned)).hexdigest())
        self.assertEqual(MAXIMUM_ROWS, plan["max_changes"])
        self.assertEqual(len(IAM_TABLES) + len(IAM_VIEWS) + 4, len(plan["targets"]))
        self.assertEqual(set(REQUIRED_INPUT_PATHS), set(plan["input_hashes"]))
        self.assertTrue(all(target["operation"] in {"CREATE", "APPEND"} for target in plan["targets"]))
        self.assertEqual(0, plan["safety_assertions"]["database_physical_deletions"])

    def test_plan_contains_no_account_or_model_budget(self) -> None:
        plan = build_plan(
            reviewed_commit="b" * 40,
            created_at="2026-08-21T08:30:00+00:00",
        )
        conditions = "\n".join(plan["preconditions"])
        self.assertIn("real reader rows", conditions)
        self.assertIn("exactly 0", conditions)
        self.assertIn("DeepSeek", conditions)
        appended = [target["identifier"] for target in plan["targets"] if target["operation"] == "APPEND"]
        self.assertTrue(all("iam_user_account" not in target for target in appended))


if __name__ == "__main__":
    unittest.main()
