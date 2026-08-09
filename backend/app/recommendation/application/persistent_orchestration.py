"""Transactional application service for a port-backed G4 orchestration."""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any, Awaitable, Callable
from uuid import NAMESPACE_URL, uuid5

from backend.app.recommendation.agents.orchestrator import (
    OrchestrationRequest,
    OrchestrationResult,
    RecommendationOrchestrator,
)
from backend.app.recommendation.application.orchestration import persist_orchestration
from backend.app.recommendation.ports.agent_logging import AgentExecutionLogPort
from backend.app.shared_kernel.contracts.agent import ArtifactRef


ConnectionFactory = Callable[[], Awaitable[Any]]
OrchestratorFactory = Callable[[Any], RecommendationOrchestrator]


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_trace_artifact(result: OrchestrationResult) -> tuple[ArtifactRef, dict[str, object]]:
    """Create a deterministic, content-addressed trace artifact reference."""

    content = {
        "schema_version": "g4-orchestration-trace-v1",
        "task_id": str(result.task_id),
        "trace_id": str(result.trace_id),
        "context_version": result.context_version,
        "status": result.status.value,
        "replan_count": result.replan_count,
        "payload": result.payload,
        "transitions": [dict(item) for item in result.transitions],
        "trace": [dict(item) for item in result.trace],
    }
    content_hash = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
    artifact = ArtifactRef(
        artifact_id=uuid5(
            NAMESPACE_URL,
            f"g4-orchestration-trace:{result.task_id}:{result.context_version}:{content_hash}",
        ),
        artifact_type="ORCHESTRATION_TRACE",
        schema_version="g4-orchestration-trace-v1",
        content_hash=content_hash,
    )
    metadata = {
        "dispatch_count": len(result.dispatches),
        "trace_step_count": len(result.trace),
        "status": result.status.value,
        "replan_count": result.replan_count,
    }
    return artifact, metadata


async def _close(connection: Any) -> None:
    closed = connection.close()
    if inspect.isawaitable(closed):
        await closed


class PersistentOrchestrationService:
    """Run one Orchestrator and append every execution fact atomically.

    The service owns the connection lifecycle but deliberately does not own
    schema migrations, task creation, commit policy outside this batch, or
    transport concerns.  A caller must provide explicit ``evaluation_at`` and
    ``deadline_at`` values so a replay has stable Agent message identities.
    """

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        orchestrator_factory: OrchestratorFactory,
        log_port: AgentExecutionLogPort,
    ) -> None:
        self._connection_factory = connection_factory
        self._orchestrator_factory = orchestrator_factory
        self._log_port = log_port

    async def run(self, request: OrchestrationRequest) -> OrchestrationResult:
        if request.evaluation_at is None or request.deadline_at is None:
            raise ValueError(
                "persistent orchestration requires explicit evaluation_at and deadline_at"
            )
        connection = await self._connection_factory()
        try:
            orchestrator = self._orchestrator_factory(connection)
            result = await orchestrator.run(request)
            await persist_orchestration(connection, result, log_port=self._log_port)
            artifact, metadata = build_trace_artifact(result)
            await self._log_port.append_artifact(
                connection,
                task_id=result.task_id,
                trace_id=result.trace_id,
                context_version=result.context_version,
                artifact=artifact,
                metadata=metadata,
            )
            await connection.commit()
            return result
        except BaseException:
            await connection.rollback()
            raise
        finally:
            await _close(connection)


__all__ = [
    "ConnectionFactory",
    "OrchestratorFactory",
    "PersistentOrchestrationService",
    "build_trace_artifact",
]
