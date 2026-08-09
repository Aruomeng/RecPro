from __future__ import annotations

import unittest
from pathlib import Path

from scripts.migrate_g2 import split_statements


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/mysql/migrations/002_g3_recommendation.sql"


class G3MigrationContractTests(unittest.TestCase):
    def test_forward_migration_contains_idempotency_and_trace_tables(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        statements = split_statements(source)
        self.assertEqual(7, len(statements))
        for table in (
            "recommendation_task",
            "recommendation_candidate",
            "recommendation_record",
            "recommendation_item",
            "recommendation_item_explanation",
            "recommendation_trace",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", source)
        self.assertIn("UNIQUE KEY uq_recommendation_task_request", source)
        self.assertIn("INSERT IGNORE INTO recpro_schema_migration", source)
        self.assertGreaterEqual(source.count("ON DELETE RESTRICT"), 5)

    def test_migration_is_inside_repository_and_has_no_destructive_sql(self) -> None:
        self.assertEqual(Path("infra/mysql/migrations/002_g3_recommendation.sql"), MIGRATION.relative_to(ROOT))
        source = MIGRATION.read_text(encoding="utf-8").upper()
        for token in ("DR" + "OP TABLE", "DR" + "OP DATABASE", "DE" + "LETE FROM", "TRUN" + "CATE", "ALTER TABLE", "REPL" + "ACE INTO"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
