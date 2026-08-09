from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import build_rule_orchestrator
from backend.app.recommendation.application.persistent_orchestration import (
    PersistentOrchestrationService,
    build_trace_artifact,
)


def request(*, explicit: bool = True) -> OrchestrationRequest:
    now = datetime.now(UTC)
    return OrchestrationRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        user_id=1001,
        input_text="多智能体推荐系统",
        evaluation_at=now if explicit else None,
        deadline_at=now + timedelta(minutes=5) if explicit else None,
    )


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


class RecordingLogPort:
    def __init__(self, *, fail_on_result: bool = False) -> None:
        self.messages: list[object] = []
        self.results: list[object] = []
        self.finals: list[object] = []
        self.artifacts: list[object] = []
        self.fail_on_result = fail_on_result

    async def append_message(self, connection, message) -> None:
        self.messages.append((connection, message))

    async def append_result(self, connection, **kwargs) -> None:
        if self.fail_on_result:
            raise RuntimeError("simulated append failure")
        self.results.append((connection, kwargs))

    async def append_artifact(self, connection, **kwargs) -> None:
        self.artifacts.append((connection, kwargs))

    async def append_orchestration_result(self, connection, **kwargs) -> None:
        self.finals.append((connection, kwargs))


class StubOrchestrator:
    def __init__(self, result) -> None:
        self.result = result

    async def run(self, request):
        return self.result


class PersistentOrchestrationTests(unittest.TestCase):
    def test_success_persists_dispatches_artifact_and_commits_once(self) -> None:
        result = asyncio.run(build_rule_orchestrator().run(request()))
        connection = FakeConnection()
        log = RecordingLogPort()
        service = PersistentOrchestrationService(
            connection_factory=lambda: _resolved(connection),
            orchestrator_factory=lambda _: StubOrchestrator(result),
            log_port=log,
        )

        actual = asyncio.run(service.run(request()))

        self.assertEqual(result, actual)
        self.assertEqual(7, len(log.messages))
        self.assertEqual(7, len(log.results))
        self.assertEqual(1, len(log.finals))
        self.assertEqual(1, len(log.artifacts))
        self.assertEqual(1, connection.commits)
        self.assertEqual(0, connection.rollbacks)
        self.assertEqual(1, connection.closed)
        self.assertEqual(result.status.value, log.finals[0][1]["status"])

    def test_append_failure_rolls_back_and_never_commits(self) -> None:
        result = asyncio.run(build_rule_orchestrator().run(request()))
        connection = FakeConnection()
        service = PersistentOrchestrationService(
            connection_factory=lambda: _resolved(connection),
            orchestrator_factory=lambda _: StubOrchestrator(result),
            log_port=RecordingLogPort(fail_on_result=True),
        )

        with self.assertRaisesRegex(RuntimeError, "simulated append failure"):
            asyncio.run(service.run(request()))
        self.assertEqual(0, connection.commits)
        self.assertEqual(1, connection.rollbacks)
        self.assertEqual(1, connection.closed)

    def test_persistent_service_requires_frozen_time_boundary(self) -> None:
        connection_requested = False

        async def factory():
            nonlocal connection_requested
            connection_requested = True
            raise AssertionError("connection must not open")

        service = PersistentOrchestrationService(
            connection_factory=factory,
            orchestrator_factory=lambda _: StubOrchestrator(None),
            log_port=RecordingLogPort(),
        )
        with self.assertRaisesRegex(ValueError, "explicit evaluation_at"):
            asyncio.run(service.run(request(explicit=False)))
        self.assertFalse(connection_requested)

    def test_trace_artifact_is_content_addressed_and_replay_stable(self) -> None:
        result = asyncio.run(build_rule_orchestrator().run(request()))
        first, first_metadata = build_trace_artifact(result)
        second, second_metadata = build_trace_artifact(result)
        self.assertEqual(first, second)
        self.assertEqual(first_metadata, second_metadata)
        self.assertEqual("ORCHESTRATION_TRACE", first.artifact_type)
        self.assertEqual(64, len(first.content_hash))


async def _resolved(value):
    return value


if __name__ == "__main__":
    unittest.main()
