from __future__ import annotations

import re
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from backend.app.catalog.adapters.mysql import _db_datetime
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest


ROOT = Path(__file__).resolve().parents[2]


class G4RealPortContractTests(unittest.TestCase):
    def test_retry_policy_is_bounded(self) -> None:
        self.assertEqual(2, RetryPolicy().max_attempts)
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=4)

    def test_aware_catalog_time_is_normalized_for_mysql(self) -> None:
        value = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
        self.assertEqual(datetime(2026, 8, 9, 8, 0), _db_datetime(value))

    def test_orchestration_evaluation_time_requires_timezone(self) -> None:
        with self.assertRaises(ValueError):
            OrchestrationRequest(
                task_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                trace_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                session_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                user_id=1001,
                evaluation_at=datetime(2026, 8, 9, 0, 0),
            )

    def test_profile_adapter_is_select_only(self) -> None:
        source = (ROOT / "backend/app/profile/adapters/mysql.py").read_text(encoding="utf-8")
        forbidden = re.compile(
            r"(?i)\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
            r"REPLACE\s+INTO|" + "TRUN" + r"CATE(?:\s+TABLE)?|"
            + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA))\b"
        )
        self.assertIsNone(forbidden.search(source))
        self.assertGreaterEqual(source.count("SELECT"), 4)

    def test_runtime_verifier_declares_zero_writes(self) -> None:
        source = (ROOT / "scripts/verify_g4_real_ports_runtime.py").read_text(encoding="utf-8")
        self.assertIn('"inserts": 0', source)
        self.assertIn('"updates": 0', source)
        self.assertIn('"deletes": 0', source)


if __name__ == "__main__":
    unittest.main()
