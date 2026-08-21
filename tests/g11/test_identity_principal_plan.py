from __future__ import annotations

import hashlib
import unittest

from scripts.build_g11_identity_principal_plan import build_plan
from scripts.execute_g11_identity_principal import MAXIMUM_CHANGES, TABLE_PRIVILEGES, canonical, dry_run_report


class IdentityPrincipalPlanTests(unittest.TestCase):
    def test_dry_run_has_no_connection_or_business_write(self) -> None:
        report = dry_run_report()
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["business_row_writes"])
        self.assertEqual({"INSERT", "SELECT", "UPDATE"}, set(report["allowed_privileges"]))
        self.assertIn("DELETE", report["forbidden_privileges"])

    def test_plan_is_canonical_and_exactly_bounded(self) -> None:
        plan = build_plan(reviewed_commit="c" * 40, created_at="2026-08-21T08:20:00Z")
        unsigned = dict(plan); expected = unsigned.pop("plan_hash")
        self.assertEqual(expected, hashlib.sha256(canonical(unsigned)).hexdigest())
        self.assertEqual(MAXIMUM_CHANGES, plan["max_changes"])
        self.assertEqual(1 + sum(len(value) for value in TABLE_PRIVILEGES.values()), len(plan["targets"]))
        serialized = "\n".join(target["identifier"] for target in plan["targets"])
        self.assertNotIn(":DELETE", serialized)
        self.assertNotIn(":DROP", serialized)


if __name__ == "__main__": unittest.main()
