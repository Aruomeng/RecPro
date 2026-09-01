from __future__ import annotations

from pathlib import Path
import re
import unittest

from scripts.verify_g14_oidc_mapping_migration import dry_run_report


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/011_g14_oidc_identity_binding.sql"


class OIDCMappingSchemaTests(unittest.TestCase):
    def test_static_dry_run_has_no_connections_or_writes(self) -> None:
        report = dry_run_report()
        self.assertEqual("PASS", report["status"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_writes"])
        self.assertEqual(0, report["binding_rows"])

    def test_migration_is_forward_only_and_stores_only_digests(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        statements = tuple(item.strip() for item in source.split(";") if item.strip())
        self.assertEqual(2, len(statements))
        compact = [re.sub(r"--[^\n]*", " ", statement).upper() for statement in statements]
        self.assertTrue(compact[0].lstrip().startswith("CREATE TABLE IF NOT EXISTS IAM_OIDC_IDENTITY_BINDING"))
        self.assertTrue(compact[1].lstrip().startswith("INSERT IGNORE INTO RECPRO_SCHEMA_MIGRATION"))
        self.assertIn("ISSUER_SHA256 BINARY(32)", compact[0])
        self.assertIn("SUBJECT_HASH BINARY(32)", compact[0])
        self.assertNotIn("SUBJECT VARCHAR", compact[0])
        self.assertNotIn("TOKEN", compact[0])
        self.assertNotIn("ROLE_CODE", compact[0])
        self.assertIn("ON DELETE RESTRICT ON UPDATE RESTRICT", compact[0])
        for statement in compact:
            self.assertIsNone(
                re.search(r"\b(DROP|TRUNCATE|ALTER|RENAME|REPLACE)\b|\bDELETE\s+FROM\b|^\s*UPDATE\b", statement)
            )


if __name__ == "__main__":
    unittest.main()
