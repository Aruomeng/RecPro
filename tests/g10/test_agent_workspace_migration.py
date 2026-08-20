from __future__ import annotations

import unittest
from pathlib import Path

from scripts.migrate_g2 import split_statements


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/mysql/migrations/008_g10_agent_workspace_audit.sql"


class AgentWorkspaceMigrationContractTests(unittest.TestCase):
    def test_migration_only_creates_two_append_fact_tables_and_marker(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        statements = split_statements(source)
        self.assertEqual(3, len(statements))
        self.assertIn("CREATE TABLE IF NOT EXISTS agent_workspace_event", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS interaction_directive_fact", source)
        self.assertIn("INSERT IGNORE INTO recpro_schema_migration", source)
        self.assertIn("uq_agent_workspace_event_sequence", source)
        self.assertIn("uq_interaction_directive_state", source)

    def test_migration_has_no_destructive_or_existing_table_mutation_statement(self) -> None:
        source = "\n".join(
            line for line in MIGRATION.read_text(encoding="utf-8").upper().splitlines()
            if not line.lstrip().startswith("--")
        )
        for token in (
            "DR" + "OP ",
            "DE" + "LETE ",
            "TRUN" + "CATE",
            "ALTER TABLE",
            "UP" + "DATE ",
            "REPL" + "ACE INTO",
        ):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
