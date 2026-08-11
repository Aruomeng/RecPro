from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from backend.app.recommendation.adapters.g4_mysql import (
    G4PersistedIdentities,
    MySQLG4ProjectionWriter,
    MySQLG4RecommendationTaskService,
)
from backend.app.recommendation.application.g4_projection import derive_task_identity
from backend.app.recommendation.ports.public import (
    IdempotencyConflictError,
    StaleContextVersionError,
)
from backend.app.shared_kernel.contracts.enums import TaskStatus
from tests.g4.test_g4_persistence import base_command, enriched_result, resources


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.row: tuple[object, ...] | None = None

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def execute(self, query: str, params: tuple[object, ...]) -> None:
        normalized = " ".join(query.split())
        self.connection.queries.append((normalized, params))
        if normalized.startswith("SELECT id, request_id"):
            self.row = self.connection.task_row
        elif normalized.startswith("SELECT context_version, status") and "AND idempotency_key =" in normalized:
            self.row = self.connection.replay_row
        elif normalized.startswith("SELECT context_version, status"):
            self.row = self.connection.latest_row
        else:
            self.row = None

    async def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class FakeConnection:
    def __init__(self, *, task_row, latest_row, replay_row=None) -> None:
        self.task_row = task_row
        self.latest_row = latest_row
        self.replay_row = replay_row
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        return None


class ContextCursor:
    def __init__(self, connection: "ContextConnection") -> None:
        self.connection = connection
        self.row: tuple[object, ...] | None = None

    async def __aenter__(self) -> "ContextCursor":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def execute(self, query: str, params: tuple[object, ...]) -> None:
        normalized = " ".join(query.split())
        self.connection.queries.append((normalized, params))
        if normalized.startswith("SELECT status, request_json"):
            self.row = self.connection.context_row
        elif normalized.startswith("SELECT questions_json, answers_json"):
            self.row = self.connection.clarification_row
        else:
            self.row = None

    async def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class ContextConnection:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.context_row = (
            "COMPLETED",
            "{}",
            "[]",
            '{"topic":"多智能体"}',
            '{"status":"COMPLETED","context_version":2}',
            "g4-context-key",
        )
        self.clarification_row = ("[]", '{"topic":"多智能体"}', datetime.now(), datetime.now())

    def cursor(self) -> ContextCursor:
        return ContextCursor(self)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeCatalog:
    async def list_resources(self, *, available_at: datetime):
        return [
            SimpleNamespace(
                id=resource.resource_id,
                resource_type=resource.resource_type,
                title=resource.title,
                authors=resource.authors,
                publication_year=resource.publication_year,
                availability_status=resource.availability_status,
            )
            for resource in resources().values()
        ]


class RecordingWriter:
    def __init__(self) -> None:
        self.appended = []
        self.contexts = []

    async def append(self, connection, plan, *, result):
        self.appended.append((connection, plan, result))
        return G4PersistedIdentities(record_id=901, item_ids={1: 1001, 2: 1002, 3: 1003})

    async def append_continuation_context(
        self, connection, plan, *, answers, idempotency_key, response
    ):
        self.contexts.append(
            (connection, plan, dict(answers), idempotency_key, dict(response))
        )


class RecordingOrchestrator:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    async def run(self, request):
        self.calls.append(request)
        return self.result


def _fixture():
    command = replace(base_command(resource_types=()), input_text=None)
    identity = derive_task_identity(command)
    request_json = {
        "request_id": str(command.request_id),
        "session_id": str(command.session_id),
        "user_id": command.user_id,
        "scene": command.scene,
        "input_text": None,
        "resource_types": [],
        "output_type": None,
        "source_resource_id": None,
        "source_item_id": None,
        "evaluation_at": None,
        "constraints": {},
        "limit": command.limit,
    }
    questions = [
        {
            "slot": "resource_types",
            "options": ["BOOK", "PAPER", "BOOK_AND_PAPER"],
            "required": True,
        },
        {"slot": "topic", "options": ["多智能体"], "required": True},
    ]
    task_row = (
        str(identity.task_id),
        str(command.request_id),
        str(identity.trace_id),
        command.user_id,
        str(command.session_id),
        command.scene,
        None,
        json.dumps(request_json, ensure_ascii=False),
        "WAITING_CLARIFICATION",
        1,
        datetime(2026, 8, 11, 1, 0),
        datetime(2026, 8, 11, 1, 0),
        None,
        None,
        "rec-1.0.0",
        "policy-g4-v1",
        "ranking-g4-v1",
        "profile-g4-v1",
        "lib-books-v1",
    )
    latest_row = (
        1,
        "WAITING_CLARIFICATION",
        json.dumps(request_json, ensure_ascii=False),
        json.dumps(questions, ensure_ascii=False),
        "{}",
        json.dumps({"status": "WAITING_CLARIFICATION"}),
        None,
    )
    return command, identity, task_row, latest_row, questions


class G4ContinuationTests(unittest.TestCase):
    def _service(self, connection, result, writer, orchestrator):
        async def connection_factory():
            return connection

        return MySQLG4RecommendationTaskService(
            host="127.0.0.1",
            port=3306,
            database="recpro",
            user="test",
            password="test",
            catalog_repository_factory=lambda _connection: FakeCatalog(),
            orchestrator_factory=lambda _connection: orchestrator,
            connection_factory=connection_factory,
            log_port=object(),
        ), result

    def test_continuation_commits_once_after_writer_and_context(self) -> None:
        command, identity, task_row, latest_row, _questions = _fixture()
        result = replace(enriched_result(), context_version=2)
        connection = FakeConnection(task_row=task_row, latest_row=latest_row)
        writer = RecordingWriter()
        orchestrator = RecordingOrchestrator(result)
        service, _ = self._service(connection, result, writer, orchestrator)
        service._g4_writer = writer

        response = asyncio.run(
            service.submit_clarification(
                identity.task_id,
                context_version=1,
                answers={"resource_types": "BOOK_AND_PAPER", "topic": "多智能体"},
                idempotency_key="g4-continuation-test-key",
                user_id=1001,
            )
        )

        self.assertEqual(200, response.status_code)
        self.assertFalse(response.replayed)
        self.assertEqual(2, response.payload["context_version"])
        self.assertEqual(1, connection.commits)
        self.assertEqual(0, connection.rollbacks)
        self.assertEqual(1, len(writer.appended))
        self.assertEqual(2, writer.appended[0][1].context_version)
        self.assertEqual(1, len(writer.contexts))
        self.assertEqual(1, len(orchestrator.calls))
        self.assertEqual(TaskStatus.WAITING_CLARIFICATION, orchestrator.calls[0].initial_status)

    def test_context_writer_is_append_only_and_does_not_own_transaction(self) -> None:
        connection = ContextConnection()
        plan = SimpleNamespace(
            task_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            context_version=2,
            status="COMPLETED",
            request_json={},
            questions=(),
            started_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
        )
        asyncio.run(
            MySQLG4ProjectionWriter(log_port=object()).append_continuation_context(
                connection,
                plan,
                answers={"topic": "多智能体"},
                idempotency_key="g4-context-key",
                response={"status": "COMPLETED", "context_version": 2},
            )
        )
        sql = " ".join(query for query, _ in connection.queries).upper()
        self.assertIn("INSERT IGNORE INTO RECOMMENDATION_TASK_CONTEXT", sql)
        self.assertIn("INSERT IGNORE INTO RECOMMENDATION_CLARIFICATION", sql)
        self.assertNotIn("UPDATE ", sql)
        self.assertNotIn("DELETE ", sql)
        self.assertEqual(0, connection.commits)
        self.assertEqual(0, connection.rollbacks)

    def test_stale_context_rolls_back_before_orchestration(self) -> None:
        _command, identity, task_row, latest_row, _questions = _fixture()
        stale_latest = (2, *latest_row[1:])
        connection = FakeConnection(task_row=task_row, latest_row=stale_latest)
        writer = RecordingWriter()
        orchestrator = RecordingOrchestrator(replace(enriched_result(), context_version=2))
        service, _ = self._service(connection, None, writer, orchestrator)
        service._g4_writer = writer

        with self.assertRaises(StaleContextVersionError):
            asyncio.run(
                service.submit_clarification(
                    identity.task_id,
                    context_version=1,
                    answers={"resource_types": "BOOK", "topic": "多智能体"},
                    idempotency_key="g4-stale-key",
                    user_id=1001,
                )
            )
        self.assertEqual(0, connection.commits)
        self.assertEqual(1, connection.rollbacks)
        self.assertEqual([], writer.appended)
        self.assertEqual([], orchestrator.calls)

    def test_replay_returns_stored_response_without_orchestration(self) -> None:
        _command, identity, task_row, latest_row, _questions = _fixture()
        response = {"status": "COMPLETED", "context_version": 2}
        replay_row = (
            2,
            "COMPLETED",
            latest_row[2],
            "[]",
            json.dumps({"resource_types": "BOOK", "topic": "多智能体"}, ensure_ascii=False),
            json.dumps(response),
            "g4-replay-key",
        )
        connection = FakeConnection(
            task_row=task_row,
            latest_row=latest_row,
            replay_row=replay_row,
        )
        writer = RecordingWriter()
        orchestrator = RecordingOrchestrator(replace(enriched_result(), context_version=2))
        service, _ = self._service(connection, None, writer, orchestrator)
        service._g4_writer = writer

        result = asyncio.run(
            service.submit_clarification(
                identity.task_id,
                context_version=1,
                answers={"resource_types": "BOOK", "topic": "多智能体"},
                idempotency_key="g4-replay-key",
                user_id=1001,
            )
        )
        self.assertTrue(result.replayed)
        self.assertEqual(response, result.payload)
        self.assertEqual(0, connection.commits)
        self.assertEqual(1, connection.rollbacks)
        self.assertEqual([], orchestrator.calls)

    def test_replay_conflict_is_rejected_without_write(self) -> None:
        _command, identity, task_row, latest_row, _questions = _fixture()
        replay_row = (
            2,
            "COMPLETED",
            latest_row[2],
            "[]",
            json.dumps({"resource_types": "BOOK", "topic": "多智能体"}, ensure_ascii=False),
            json.dumps({"status": "COMPLETED", "context_version": 2}),
            "g4-replay-conflict-key",
        )
        connection = FakeConnection(task_row=task_row, latest_row=latest_row, replay_row=replay_row)
        writer = RecordingWriter()
        orchestrator = RecordingOrchestrator(replace(enriched_result(), context_version=2))
        service, _ = self._service(connection, None, writer, orchestrator)
        service._g4_writer = writer

        with self.assertRaises(IdempotencyConflictError):
            asyncio.run(
                service.submit_clarification(
                    identity.task_id,
                    context_version=1,
                    answers={"resource_types": "PAPER", "topic": "多智能体"},
                    idempotency_key="g4-replay-conflict-key",
                    user_id=1001,
                )
            )
        self.assertEqual(0, connection.commits)
        self.assertEqual(1, connection.rollbacks)
        self.assertEqual([], writer.appended)


if __name__ == "__main__":
    unittest.main()
