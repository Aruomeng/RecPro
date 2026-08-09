from __future__ import annotations

import asyncio
import re
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.recommendation.adapters.agent_logging_mysql import _naive_utc
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import (
    build_rule_orchestrator,
    persist_orchestration,
)
from backend.app.shared_kernel.contracts.agent import AgentDispatch, AgentMessage
from backend.app.shared_kernel.contracts.enums import MessageType
from scripts.migrate_g2 import split_statements


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/mysql/migrations/005_g4_agent_execution.sql"
ADAPTER = ROOT / "backend/app/recommendation/adapters/agent_logging_mysql.py"


def request(*, suffix: str = "a", constraints: dict[str, object] | None = None) -> OrchestrationRequest:
    return OrchestrationRequest(
        task_id=UUID(f"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa{suffix}"),
        trace_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        session_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        user_id=1001,
        input_text="多智能体推荐",
        constraints=constraints,
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )


class RecordingPort:
    def __init__(self) -> None:
        self.messages: list[object] = []
        self.results: list[object] = []
        self.final: list[object] = []

    async def append_message(self, connection, message) -> None:
        self.messages.append((connection, message))

    async def append_result(self, connection, **kwargs) -> None:
        self.results.append((connection, kwargs))

    async def append_artifact(self, connection, **kwargs) -> None:
        raise AssertionError("artifact path is not part of this rule slice")

    async def append_orchestration_result(self, connection, **kwargs) -> None:
        self.final.append((connection, kwargs))


class AgentLoggingContractTests(unittest.TestCase):
    def test_dispatch_pair_rejects_mismatched_result_message(self) -> None:
        message = AgentMessage(
            schema_version="test-v1",
            message_id=uuid4(),
            trace_id=uuid4(),
            task_id=uuid4(),
            sender="test",
            receiver="test-agent",
            message_type=MessageType.INTENT_RESOLVE,
            payload={},
            deadline_at=datetime.now(UTC) + timedelta(seconds=1),
            idempotency_key="test-key",
            context_version=1,
            created_at=datetime.now(UTC),
        )
        with self.assertRaises(ValueError):
            AgentDispatch(
                message=message,
                result=type("Result", (), {"input_message_id": uuid4()})(),
            )

    def test_persistence_port_receives_all_dispatches_without_owning_commit(self) -> None:
        result = asyncio.run(build_rule_orchestrator().run(request()))
        port = RecordingPort()
        connection = object()
        asyncio.run(persist_orchestration(connection, result, log_port=port))
        self.assertEqual(len(result.dispatches), len(port.messages))
        self.assertEqual(len(result.dispatches), len(port.results))
        self.assertEqual(1, len(port.final))
        self.assertTrue(all(item[0] is connection for item in port.messages))
        self.assertEqual(result.status.value, port.final[0][1]["status"])

    def test_replanning_keeps_both_attempts_in_append_batch(self) -> None:
        result = asyncio.run(
            build_rule_orchestrator().run(request(suffix="b", constraints={"force_replan": True}))
        )
        self.assertEqual(10, len(result.dispatches))
        message_ids = [dispatch.message.message_id for dispatch in result.dispatches]
        self.assertEqual(len(message_ids), len(set(message_ids)))
        self.assertEqual(3, sum(dispatch.message.attempt == 2 for dispatch in result.dispatches))

    def test_migration_is_forward_only_and_has_four_fact_tables(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertEqual(5, len(split_statements(source)))
        for table in (
            "recommendation_agent_message",
            "recommendation_agent_result",
            "recommendation_agent_artifact",
            "recommendation_orchestration_result",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", source)
        self.assertGreaterEqual(source.count("ON DELETE RESTRICT"), 4)
        forbidden = (
            r"(?i)\b(?:"
            + "DE" + r"LETE\s+FROM|"
            + "TRUN" + r"CATE(?:\s+TABLE)?|"
            + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA)|"
            + "AL" + r"TER\s+TABLE|"
            + "REPL" + r"ACE\s+INTO)\b"
        )
        self.assertIsNone(re.search(forbidden, source))

    def test_mysql_writer_contains_only_append_sql(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        forbidden = (
            r"(?i)\b(?:"
            + "DE" + r"LETE\s+FROM|"
            + "UP" + r"DATE\s+\w+\s+SET|"
            + "TRUN" + r"CATE|"
            + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA))\b"
        )
        self.assertIsNone(re.search(forbidden, source))
        self.assertGreaterEqual(source.count("INSERT IGNORE INTO"), 4)

    def test_aware_times_are_stored_as_utc_naive_values(self) -> None:
        value = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
        self.assertEqual(datetime(2026, 8, 9, 8, 0), _naive_utc(value))


if __name__ == "__main__":
    unittest.main()
