from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from backend.app.recommendation.adapters.g4_mysql import MySQLG4ProjectionWriter
from backend.app.recommendation.application.g4_persistence import (
    G4ProjectionWritePlan,
)
from backend.app.recommendation.application.g4_projection import (
    G4ProjectionVersions,
)
from backend.app.recommendation.application.g4_persistence import build_g4_projection_write_plan
from tests.g4.test_g4_persistence import base_command, enriched_result, resources


class RecordingLogPort:
    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[object] = []
        self.results: list[object] = []
        self.artifacts: list[object] = []
        self.finals: list[object] = []
        self.fail = fail

    async def append_message(self, connection, message) -> None:
        if self.fail:
            raise RuntimeError("simulated agent log failure")
        self.messages.append((connection, message))

    async def append_result(self, connection, **kwargs) -> None:
        self.results.append((connection, kwargs))

    async def append_artifact(self, connection, **kwargs) -> None:
        self.artifacts.append((connection, kwargs))

    async def append_orchestration_result(self, connection, **kwargs) -> None:
        self.finals.append((connection, kwargs))


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.row: tuple[Any, ...] | None = None

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.connection.queries.append((query, params))
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT request_json"):
            plan = self.connection.plan
            self.row = (
                json.dumps(dict(plan.request_json), ensure_ascii=False),
                str(plan.trace_id),
                plan.status,
                plan.context_version,
            )
        elif normalized.startswith(
            "SELECT status, context_version FROM recommendation_task_context"
        ):
            self.row = self.connection.latest_context
        elif normalized.startswith("SELECT id, decision_json"):
            plan = self.connection.plan
            self.row = (
                901,
                json.dumps(dict(plan.decision), ensure_ascii=False),
                json.dumps(list(plan.warnings), ensure_ascii=False),
                json.dumps(dict(plan.versions), ensure_ascii=False),
            )
        elif normalized.startswith("SELECT id FROM recommendation_item"):
            resource_id = int(params[1])
            self.row = (1000 + resource_id,)
        elif normalized.startswith("SELECT from_status, to_status, reason_code"):
            plan = self.connection.plan
            to_status = str(params[2])
            transition = next(
                item for item in plan.transitions if item.to_status == to_status
            )
            self.row = (
                transition.from_status,
                transition.to_status,
                transition.reason_code,
            )
        elif normalized.startswith("SELECT channel_rank, raw_score"):
            plan = self.connection.plan
            resource_id = int(params[1])
            channel = str(params[2])
            candidate = next(
                item
                for item in plan.candidates
                if item.resource_id == resource_id and item.channel == channel
            )
            self.row = (
                candidate.channel_rank,
                candidate.raw_score,
                candidate.normalized_score,
                candidate.rrf_contribution,
                json.dumps(dict(candidate.evidence), ensure_ascii=False),
            )
        else:
            self.row = None

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class FakeConnection:
    def __init__(
        self,
        plan: G4ProjectionWritePlan,
        *,
        latest_context: tuple[str, int] | None = None,
    ) -> None:
        self.plan = plan
        self.latest_context = latest_context
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def make_plan() -> tuple[G4ProjectionWritePlan, object]:
    result = enriched_result()
    plan = build_g4_projection_write_plan(
        base_command(),
        result,
        resources=resources(),
        versions=G4ProjectionVersions(
            config_bundle="rec-1.0.0", dataset="lib-books-v1"
        ),
        evaluation_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
        started_at=datetime(2026, 8, 11, 1, 0, 1, tzinfo=UTC),
    )
    return plan, result


class G4MySQLWriterTests(unittest.TestCase):
    def test_writer_appends_all_facts_without_owning_commit(self) -> None:
        plan, result = make_plan()
        connection = FakeConnection(plan)
        log = RecordingLogPort()
        identities = asyncio.run(
            MySQLG4ProjectionWriter(log_port=log).append(
                connection, plan, result=result
            )
        )
        self.assertEqual(901, identities.record_id)
        self.assertEqual({1: 1001, 2: 1002, 3: 1003}, dict(identities.item_ids))
        self.assertEqual(7, len(log.messages))
        self.assertEqual(7, len(log.results))
        self.assertEqual(1, len(log.finals))
        self.assertEqual(1, len(log.artifacts))
        self.assertEqual(0, connection.commits)
        self.assertEqual(0, connection.rollbacks)
        sql = " ".join(query for query, _ in connection.queries).upper()
        self.assertNotIn("UPDATE ", sql)
        self.assertNotIn("DELETE ", sql)
        self.assertNotIn("DROP ", sql)
        self.assertGreaterEqual(sql.count("INSERT IGNORE INTO"), 1)

    def test_agent_log_failure_stops_before_writer_can_commit(self) -> None:
        plan, result = make_plan()
        connection = FakeConnection(plan)
        with self.assertRaisesRegex(RuntimeError, "simulated agent log failure"):
            asyncio.run(
                MySQLG4ProjectionWriter(log_port=RecordingLogPort(fail=True)).append(
                    connection, plan, result=result
                )
            )
        self.assertEqual(0, connection.commits)
        self.assertEqual(0, connection.rollbacks)

    def test_continuation_uses_latest_context_not_immutable_task_snapshot(self) -> None:
        plan, _result = make_plan()
        continuation_plan = replace(plan, context_version=3)
        connection = FakeConnection(
            continuation_plan,
            latest_context=("WAITING_CLARIFICATION", 2),
        )
        asyncio.run(
            MySQLG4ProjectionWriter(log_port=RecordingLogPort())._append_task(
                connection, continuation_plan
            )
        )
        sql = " ".join(query for query, _ in connection.queries).upper()
        self.assertIn(
            "SELECT STATUS, CONTEXT_VERSION FROM RECOMMENDATION_TASK_CONTEXT",
            sql,
        )
        self.assertEqual(0, connection.commits)
        self.assertEqual(0, connection.rollbacks)


if __name__ == "__main__":
    unittest.main()
