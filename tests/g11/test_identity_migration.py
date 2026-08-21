from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from backend.app.identity.adapters.mysql import MySQLIdentityRepository
from scripts.execute_g11_identity_migration import (
    IAM_TABLES,
    IAM_VIEWS,
    MAXIMUM_ROWS,
    MIGRATION,
    SEED_ROWS,
    dry_run_report,
    validate_migration_statements,
)


class IdentityMigrationTests(unittest.TestCase):
    def test_dry_run_is_exact_and_connects_to_nothing(self) -> None:
        report = dry_run_report()
        self.assertEqual("NO_WRITE_DRY_RUN", report["mode"])
        self.assertEqual(19, report["migration_statement_count"])
        self.assertEqual(list(IAM_TABLES), report["new_tables"])
        self.assertEqual(list(IAM_VIEWS), report["new_views"])
        self.assertEqual(SEED_ROWS, report["seed_rows"])
        self.assertEqual(MAXIMUM_ROWS, report["maximum_rows"])
        self.assertEqual(0, report["bootstrap_account_rows"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_writes"])
        self.assertEqual(0, report["deepseek_requests"])

    def test_migration_has_twelve_tables_three_views_and_fixed_seeds(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        statements = validate_migration_statements(source)
        self.assertEqual(12, sum("CREATE TABLE IF NOT EXISTS" in item for item in statements))
        self.assertEqual(3, sum("CREATE VIEW" in item for item in statements))
        self.assertEqual(4, sum("INSERT IGNORE INTO" in item for item in statements))
        self.assertIn("AUTO_INCREMENT=10000", source)
        self.assertNotIn("ON DELETE CASCADE", source.upper())
        self.assertNotIn("ON UPDATE CASCADE", source.upper())
        self.assertNotIn("CREATE OR REPLACE", source.upper())

    def test_validator_rejects_mutating_or_unbounded_sql(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        malicious = source.replace(
            "INSERT IGNORE INTO recpro_schema_migration",
            "DELETE FROM recpro_schema_migration; INSERT IGNORE INTO recpro_schema_migration",
            1,
        )
        with self.assertRaises(ValueError):
            validate_migration_statements(malicious)
        unexpected = source.replace("INSERT IGNORE INTO iam_role (", "INSERT IGNORE INTO resource_catalog (", 1)
        with self.assertRaises(ValueError):
            validate_migration_statements(unexpected)

    def test_mysql_adapter_contains_no_physical_delete_or_replace_path(self) -> None:
        source = inspect.getsource(MySQLIdentityRepository).upper()
        self.assertNotIn("DELETE FROM", source)
        self.assertNotIn("REPLACE INTO", source)
        self.assertNotIn("DROP TABLE", source)
        self.assertNotIn("TRUNCATE TABLE", source)

    def test_required_artifacts_are_workspace_files(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.assertTrue(MIGRATION.is_relative_to(root))
        self.assertTrue((root / "backend/app/identity/adapters/mysql.py").is_file())


if __name__ == "__main__":
    unittest.main()
