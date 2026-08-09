from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.recommendation.adapters.mysql import (
    _command_payload,
    _task_id,
    _trace_id,
)
from backend.app.recommendation.domain.public import RecommendationTaskCommand


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "backend/app/recommendation/adapters/mysql.py"


class G3MySQLAdapterContractTests(unittest.TestCase):
    def test_auto_evaluation_time_is_not_part_of_replay_identity(self) -> None:
        command = RecommendationTaskCommand(
            request_id=uuid4(),
            session_id=uuid4(),
            user_id=1001,
            scene="SEARCH_AFTER",
            input_text="多智能体",
            resource_types=("BOOK", "PAPER"),
            output_type=None,
            source_resource_id=None,
            source_item_id=None,
            evaluation_at=None,
            constraints={},
            limit=5,
        )
        first = _command_payload(command, datetime(2026, 8, 9, 0, 0, 0))
        second = _command_payload(command, datetime(2026, 8, 9, 0, 1, 0))
        self.assertEqual(first, second)
        self.assertIsNone(first["evaluation_at"])

    def test_deterministic_ids_are_user_scoped(self) -> None:
        request_id = UUID("11111111-1111-1111-1111-111111111111")
        self.assertEqual(_task_id(request_id, 1001), _task_id(request_id, 1001))
        self.assertNotEqual(_task_id(request_id, 1001), _task_id(request_id, 1002))
        self.assertNotEqual(_trace_id(request_id, 1001), _trace_id(request_id, 1002))

    def test_adapter_contains_no_mutating_update_or_destructive_sql(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        forbidden = (
            r"(?i)\b(?:"
            + "DE" + r"LETE\s+FROM|"
            + "UP" + r"DATE\s+\w+\s+SET|"
            + "TRUN" + r"CATE|"
            + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA))\b"
        )
        import re

        self.assertIsNone(re.search(forbidden, source))


if __name__ == "__main__":
    unittest.main()
