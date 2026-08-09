from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts.migrate_g2 import split_statements


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/mysql/migrations/004_g3_clarification_debug.sql"


class G3ClarificationMigrationTests(unittest.TestCase):
    def test_migration_contains_versioned_clarification_and_debug_facts(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertEqual(5, len(split_statements(source)))
        for table in (
            "recommendation_task_context",
            "recommendation_clarification",
            "recommendation_policy_decision",
            "recommendation_trace_revision",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", source)
        self.assertIn("UNIQUE KEY uq_recommendation_context_version", source)
        self.assertIn("UNIQUE KEY uq_recommendation_context_idempotency", source)
        self.assertIn("g3-clarification-debug-v1", source)
        self.assertGreaterEqual(source.count("ON DELETE RESTRICT"), 4)

    def test_migration_is_forward_only(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8").upper()
        forbidden = (
            r"(?i)\b(?:"
            + "DE" + r"LETE\s+FROM|"
            + "TRUN" + r"CATE(?:\s+TABLE)?|"
            + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA)|"
            + "AL" + r"TER\s+TABLE|"
            + "REPL" + r"ACE\s+INTO)\b"
        )
        self.assertIsNone(re.search(forbidden, source))


if __name__ == "__main__":
    unittest.main()
