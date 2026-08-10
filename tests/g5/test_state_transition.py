from __future__ import annotations

import re
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.observability.domain.transition import StateTransition, transition_uuid
from scripts.migrate_g2 import split_statements


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/mysql/migrations/007_g5_state_transition_audit.sql"


class G5StateTransitionTests(unittest.TestCase):
    def test_transition_identity_is_deterministic(self) -> None:
        first = transition_uuid(
            aggregate_type="PROFILE_OUTBOX",
            aggregate_id="44",
            transition_type="CLAIMED",
            version_after=2,
            causation_ref="OUTBOX:44:ATTEMPT:1",
        )
        second = transition_uuid(
            aggregate_type="PROFILE_OUTBOX",
            aggregate_id="44",
            transition_type="CLAIMED",
            version_after=2,
            causation_ref="OUTBOX:44:ATTEMPT:1",
        )
        self.assertIsInstance(first, UUID)
        self.assertEqual(first, second)

    def test_transition_requires_a_forward_version(self) -> None:
        with self.assertRaises(ValueError):
            StateTransition(
                transition_uuid=uuid4(),
                module_name="profile",
                aggregate_type="USER_PROFILE",
                aggregate_id="1001",
                transition_type="REPLAY_APPLIED",
                from_state=None,
                to_state="1",
                version_before=0,
                version_after=1,
                causation_ref="OUTBOX:1:EVENT:1",
                actor_type="WORKER",
            )
        with self.assertRaises(ValueError):
            StateTransition(
                transition_uuid=uuid4(),
                module_name="profile",
                aggregate_type="USER_PROFILE",
                aggregate_id="1001",
                transition_type="REPLAY_APPLIED",
                from_state=None,
                to_state="2",
                version_before=None,
                version_after=2,
                causation_ref="OUTBOX:1:EVENT:1",
                actor_type="WORKER",
            )

    def test_transition_freezes_detail_and_normalizes_timestamp(self) -> None:
        transition = StateTransition(
            transition_uuid=uuid4(),
            module_name="feedback",
            aggregate_type="USER_RESOURCE_STATE",
            aggregate_id="1001:1:HIDDEN",
            transition_type="CREATED",
            from_state=None,
            to_state="HIDDEN",
            version_before=None,
            version_after=1,
            causation_ref="BEHAVIOR:10",
            actor_type="SYSTEM",
            detail={"source_event_id": 10},
            created_at=datetime(2026, 8, 10, 10, 0, 0, 123456, tzinfo=UTC),
        )
        self.assertEqual('{"source_event_id":10}', transition.detail_json())
        self.assertEqual(datetime(2026, 8, 10, 10, 0, 0, 123000), transition.created_at_utc())

    def test_migration_is_forward_only_and_restrictive(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertEqual(2, len(split_statements(source)))
        self.assertIn("CREATE TABLE IF NOT EXISTS domain_state_transition", source)
        self.assertIn("UNIQUE KEY uq_domain_transition_uuid", source)
        self.assertIn("UNIQUE KEY uq_domain_transition_aggregate_version", source)
        self.assertIn("INSERT IGNORE INTO recpro_schema_migration", source)
        forbidden = re.compile(
            r"(?i)\b(?:"
            + "DE" + r"LETE\s+FROM|"
            + "TRUN" + r"CATE(?:\s+TABLE)?|"
            + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA)|"
            + "AL" + r"TER\s+TABLE)\b"
        )
        self.assertIsNone(forbidden.search(source))


if __name__ == "__main__":
    unittest.main()
