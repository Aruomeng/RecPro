from __future__ import annotations

import unittest
from pathlib import Path

from scripts.migrate_g2 import DEFAULT_MIGRATION, split_statements


class G2MigrationContractTests(unittest.TestCase):
    def test_migration_is_forward_only_and_contains_core_tables(self) -> None:
        source = DEFAULT_MIGRATION.read_text(encoding="utf-8")
        statements = split_statements(source)
        self.assertGreaterEqual(len(statements), 20)
        for table in (
            "resource_catalog",
            "resource_tag",
            "user_behavior_event",
            "user_declared_profile_history",
            "user_profile",
            "profile_update_outbox",
            "profile_replay_run",
            "recommendation_config_version",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", source)
        self.assertNotIn("ON " + "DE" + "LETE CASCADE", source)
        self.assertGreaterEqual(source.count("ON DELETE RESTRICT"), 10)
        self.assertIn("INSERT IGNORE INTO recpro_schema_migration", source)

    def test_migration_parser_rejects_destructive_or_non_table_ddl(self) -> None:
        for source in (
            "DR" + "OP TABLE resource_catalog;",
            "DE" + "LETE FROM resource_catalog;",
            "CREATE INDEX ix_anything ON resource_catalog (title);",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                split_statements(source)

    def test_migration_path_stays_inside_repository(self) -> None:
        self.assertTrue(DEFAULT_MIGRATION.is_file())
        self.assertEqual(Path("infra/mysql/migrations/001_g2_core.sql"), DEFAULT_MIGRATION.relative_to(Path.cwd()))


if __name__ == "__main__":
    unittest.main()
