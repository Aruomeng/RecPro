from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts.migrate_g2 import split_statements


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/mysql/migrations/006_g5_feedback_state.sql"


class G5ContractTests(unittest.TestCase):
    def test_forward_migration_has_three_fact_or_projection_tables(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertEqual(4, len(split_statements(source)))
        for table in (
            "recommendation_impression",
            "recommendation_feedback",
            "user_resource_state",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", source)
        self.assertGreaterEqual(source.count("ON DELETE RESTRICT"), 3)

    def test_migration_and_adapters_have_no_physical_delete_or_replace(self) -> None:
        forbidden = re.compile(
            r"(?i)\b(?:"
            + "DE" + r"LETE\s+FROM|"
            + "TRUN" + r"CATE(?:\s+TABLE)?|"
            + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA)|"
            + "REPL" + r"ACE\s+INTO)\b"
        )
        for path in (
            MIGRATION,
            ROOT / "backend/app/feedback/adapters/mysql.py",
            ROOT / "backend/app/profile/adapters/behavior_mysql.py",
            ROOT / "backend/app/profile/adapters/refresh_mysql.py",
        ):
            self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")), path.name)

    def test_state_projection_uses_controlled_updates_only(self) -> None:
        source = (ROOT / "backend/app/feedback/adapters/mysql.py").read_text(encoding="utf-8")
        self.assertIn("UPDATE user_resource_state SET", source)
        self.assertNotIn("DELETE", source.upper())


if __name__ == "__main__":
    unittest.main()
