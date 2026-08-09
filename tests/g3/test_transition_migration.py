from __future__ import annotations

import unittest
from pathlib import Path

from scripts.migrate_g2 import split_statements


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/mysql/migrations/003_g3_task_transition.sql"


class G3TransitionMigrationTests(unittest.TestCase):
    def test_transition_migration_is_forward_only_and_restrictive(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        statements = split_statements(source)
        self.assertEqual(2, len(statements))
        self.assertIn("recommendation_task_transition", source)
        self.assertIn("ON DELETE RESTRICT", source)
        self.assertIn("ON UPDATE RESTRICT", source)
        self.assertIn("INSERT IGNORE INTO recpro_schema_migration", source)
        forbidden = (
            r"(?i)\b(?:"
            + "DE" + r"LETE\s+FROM|"
            + "TRUN" + r"CATE(?:\s+TABLE)?|"
            + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA)|"
            + "AL" + r"TER\s+TABLE)\b"
        )
        self.assertNotRegex(source, forbidden)

    def test_transition_identity_is_idempotent(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("UNIQUE KEY uq_recommendation_transition", source)
        self.assertIn("g3-task-transition-v1", source)


if __name__ == "__main__":
    unittest.main()
