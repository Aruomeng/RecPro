from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from scripts.build_g11_bootstrap_admin_plan import build_plan
from scripts.execute_g11_bootstrap_admin import (
    BOOTSTRAP_USER_ID, MAXIMUM_ROWS, ROLE_IDS, build_material, canonical,
    dry_run_report, expected_targets,
)


class BootstrapAdminPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.material = build_material(
            identifier="LIBRAMAS-ADMIN-2026-001",
            activation_code="test-activation-code-with-safe-length",
            identifier_pepper="i" * 48,
            token_pepper="t" * 48,
        )

    def test_dry_run_has_no_connection_or_write(self) -> None:
        report = dry_run_report()
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_writes"])
        self.assertEqual(0, report["deepseek_requests"])
        self.assertEqual(MAXIMUM_ROWS, report["maximum_rows"])
        self.assertEqual(BOOTSTRAP_USER_ID, report["user_id"])
        self.assertEqual(list(ROLE_IDS), report["roles"])

    def test_material_is_deterministic_and_contains_seven_targets(self) -> None:
        repeated = build_material(
            identifier=" libramas-admin-2026-001 ",
            activation_code="test-activation-code-with-safe-length",
            identifier_pepper="i" * 48,
            token_pepper="t" * 48,
        )
        self.assertEqual(self.material, repeated)
        self.assertEqual(MAXIMUM_ROWS, len(expected_targets(self.material)))
        serialized = "\n".join(expected_targets(self.material))
        self.assertNotIn("LIBRAMAS-ADMIN-2026-001", serialized)
        self.assertNotIn("test-activation", serialized)
        self.assertNotIn("service_worker", serialized)

    def test_plan_is_canonical_and_bounded(self) -> None:
        plan = build_plan(
            reviewed_commit="d" * 40,
            created_at="2026-08-27T08:00:00Z",
            material=self.material,
        )
        unsigned = dict(plan)
        expected_hash = unsigned.pop("plan_hash")
        self.assertEqual(expected_hash, hashlib.sha256(canonical(unsigned)).hexdigest())
        self.assertEqual(MAXIMUM_ROWS, plan["max_changes"])
        self.assertEqual(MAXIMUM_ROWS, len(plan["targets"]))
        self.assertTrue(all(target["operation"] == "APPEND" for target in plan["targets"]))

    def test_executor_source_has_no_destructive_sql(self) -> None:
        source = (
            Path(__file__).resolve().parents[2] / "scripts/execute_g11_bootstrap_admin.py"
        ).read_text(encoding="utf-8").upper()
        for statement in ("DELETE FROM", "DROP TABLE", "TRUNCATE TABLE", "REPLACE INTO"):
            self.assertNotIn(statement, source)


if __name__ == "__main__":
    unittest.main()
