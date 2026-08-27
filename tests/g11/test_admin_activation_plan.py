from __future__ import annotations

import hashlib
from pathlib import Path
import unittest
from uuid import UUID

from scripts.build_g11_admin_activation_plan import build_plan
from scripts.execute_g11_admin_activation import (
    MAXIMUM_CHANGES, ActivationMaterial, canonical, dry_run_report,
    expected_targets,
)
from scripts.execute_g11_bootstrap_admin import build_material


class AdminActivationPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        bootstrap = build_material(
            identifier="LIBRAMAS-ADMIN-2026-001",
            activation_code="test-activation-code-with-safe-length",
            identifier_pepper="i" * 48,
            token_pepper="t" * 48,
        )
        self.material = ActivationMaterial(
            bootstrap=bootstrap,
            password_hash="$argon2id$v=19$m=65536,t=3,p=2$fixture$fixturehash",
            password_material_digest=b"p" * 32,
            event_uuid=UUID("8f1e7e61-564c-5f5f-bbae-b5395dc05d65"),
        )

    def test_dry_run_has_no_connection_or_write(self) -> None:
        report = dry_run_report()
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_writes"])
        self.assertEqual(0, report["login_sessions"])
        self.assertEqual(MAXIMUM_CHANGES, report["maximum_changes"])

    def test_targets_are_exactly_two_appends_and_two_status_updates(self) -> None:
        operations = list(expected_targets(self.material).values())
        self.assertEqual(2, operations.count("APPEND"))
        self.assertEqual(2, operations.count("UPDATE_STATUS"))
        self.assertEqual(MAXIMUM_CHANGES, len(operations))
        serialized = "\n".join(expected_targets(self.material))
        self.assertNotIn("test-activation", serialized)

    def test_plan_is_canonical_and_bounded(self) -> None:
        plan = build_plan(
            reviewed_commit="e" * 40,
            created_at="2026-08-27T12:00:00Z", material=self.material,
        )
        unsigned = dict(plan)
        expected_hash = unsigned.pop("plan_hash")
        self.assertEqual(expected_hash, hashlib.sha256(canonical(unsigned)).hexdigest())
        self.assertEqual("S2_CONTROLLED_UPDATE", plan["classification"])
        self.assertEqual(MAXIMUM_CHANGES, plan["max_changes"])

    def test_executor_has_no_destructive_sql(self) -> None:
        source = (
            Path(__file__).resolve().parents[2] / "scripts/execute_g11_admin_activation.py"
        ).read_text(encoding="utf-8").upper()
        for statement in ("DELETE FROM", "DROP TABLE", "TRUNCATE TABLE", "REPLACE INTO"):
            self.assertNotIn(statement, source)


if __name__ == "__main__":
    unittest.main()
