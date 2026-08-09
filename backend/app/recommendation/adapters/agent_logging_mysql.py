"""Append-only MySQL writer for G4 Agent and orchestration facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import UUID

from backend.app.recommendation.ports.agent_logging import AgentExecutionLogPort
from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult, ArtifactRef


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        normalized = value
    else:
        normalized = value.astimezone(UTC).replace(tzinfo=None)
    # MySQL DATETIME(3) retains milliseconds; normalize before identity checks.
    return normalized.replace(microsecond=(normalized.microsecond // 1000) * 1000)


def _status(value: object) -> str:
    return str(getattr(value, "value", value))


def _same_json(actual: object, expected: object) -> bool:
    try:
        return _canonical(_json_value(actual)) == _canonical(expected)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


class MySQLAgentExecutionLogWriter(AgentExecutionLogPort):
    """Write G4 facts on a caller-owned asyncmy transaction.

    The writer never commits or rolls back and never rewrites an existing row.
    ``INSERT IGNORE`` is followed by an identity/content comparison so a
    replay is safe while a conflicting id is surfaced to the owning service.
    """

    async def append_message(self, connection: Any, message: AgentMessage) -> None:
        payload_json = _canonical(message.payload)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_agent_message "
                "(message_id, task_id, trace_id, context_version, schema_version, sender, "
                "receiver, message_type, payload_json, deadline_at, attempt, idempotency_key, "
                "causation_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(message.message_id),
                    str(message.task_id),
                    str(message.trace_id),
                    message.context_version,
                    message.schema_version,
                    message.sender,
                    message.receiver,
                    message.message_type.value,
                    payload_json,
                    _naive_utc(message.deadline_at),
                    message.attempt,
                    message.idempotency_key,
                    str(message.causation_id) if message.causation_id else None,
                    _naive_utc(message.created_at),
                ),
            )
            await cursor.execute(
                "SELECT task_id, trace_id, context_version, schema_version, sender, receiver, "
                "message_type, payload_json, deadline_at, attempt, idempotency_key, causation_id "
                "FROM recommendation_agent_message WHERE message_id = %s",
                (str(message.message_id),),
            )
            row = await cursor.fetchone()
        expected = (
            str(message.task_id),
            str(message.trace_id),
            message.context_version,
            message.schema_version,
            message.sender,
            message.receiver,
            message.message_type.value,
            message.deadline_at,
            message.attempt,
            message.idempotency_key,
            str(message.causation_id) if message.causation_id else None,
        )
        if row is None or row[:7] != expected[:7] or not _same_json(row[7], message.payload):
            raise ValueError("Agent message identity or payload conflict")
        if not isinstance(row[8], datetime) or _naive_utc(row[8]) != _naive_utc(message.deadline_at):
            raise ValueError("Agent message deadline conflict")
        if row[9:] != expected[8:]:
            raise ValueError("Agent message delivery metadata conflict")

    async def append_result(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        context_version: int,
        message: AgentMessage,
        result: AgentResult[dict[str, object]],
        created_at: datetime | None = None,
    ) -> None:
        payload_json = _canonical(result.payload) if result.payload is not None else None
        created = _naive_utc(created_at or datetime.now(UTC))
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_agent_result "
                "(result_id, message_id, task_id, trace_id, context_version, agent_name, agent_version, "
                "status, confidence, payload_json, evidence_refs_json, warnings_json, fallback_used, "
                "tool_calls_json, error_code, duration_ms, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(result.result_id),
                    str(message.message_id),
                    str(task_id),
                    str(trace_id),
                    context_version,
                    result.agent_name,
                    result.agent_version,
                    result.status.value,
                    result.confidence,
                    payload_json,
                    _canonical(list(result.evidence_refs)),
                    _canonical(list(result.warnings)),
                    result.fallback_used,
                    _canonical(list(result.tool_calls)),
                    result.error_code,
                    result.duration_ms,
                    created,
                ),
            )
            await cursor.execute(
                "SELECT message_id, task_id, trace_id, context_version, agent_name, agent_version, "
                "status, confidence, payload_json, evidence_refs_json, warnings_json, fallback_used, "
                "tool_calls_json, error_code, duration_ms FROM recommendation_agent_result "
                "WHERE result_id = %s",
                (str(result.result_id),),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ValueError("Agent result identity conflict")
        expected_prefix = (
            str(message.message_id),
            str(task_id),
            str(trace_id),
            context_version,
            result.agent_name,
            result.agent_version,
            result.status.value,
        )
        if row[:7] != expected_prefix:
            raise ValueError("Agent result identity conflict")
        if abs(float(row[7]) - result.confidence) > 0.000001:
            raise ValueError("Agent result confidence conflict")
        if not _same_json(row[8], result.payload) or not _same_json(row[9], list(result.evidence_refs)):
            raise ValueError("Agent result payload conflict")
        if not _same_json(row[10], list(result.warnings)) or bool(row[11]) != result.fallback_used:
            raise ValueError("Agent result warning metadata conflict")
        if not _same_json(row[12], list(result.tool_calls)) or row[13] != result.error_code or int(row[14]) != result.duration_ms:
            raise ValueError("Agent result execution metadata conflict")

    async def append_artifact(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        context_version: int,
        artifact: ArtifactRef,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        metadata_json = _canonical(dict(metadata or {}))
        created = _naive_utc(created_at or datetime.now(UTC))
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_agent_artifact "
                "(artifact_id, task_id, trace_id, context_version, artifact_type, schema_version, "
                "content_hash, metadata_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(artifact.artifact_id),
                    str(task_id),
                    str(trace_id),
                    context_version,
                    artifact.artifact_type,
                    artifact.schema_version,
                    artifact.content_hash,
                    metadata_json,
                    created,
                ),
            )
            await cursor.execute(
                "SELECT task_id, trace_id, context_version, artifact_type, schema_version, "
                "content_hash, metadata_json FROM recommendation_agent_artifact WHERE artifact_id = %s",
                (str(artifact.artifact_id),),
            )
            row = await cursor.fetchone()
        expected = (
            str(task_id),
            str(trace_id),
            context_version,
            artifact.artifact_type,
            artifact.schema_version,
            artifact.content_hash,
        )
        if row is None or row[:6] != expected or not _same_json(row[6], dict(metadata or {})):
            raise ValueError("Agent artifact identity or metadata conflict")

    async def append_orchestration_result(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        context_version: int,
        schema_version: str,
        status: str,
        replan_count: int,
        payload: Mapping[str, object],
        transitions: tuple[Mapping[str, object], ...],
        trace: tuple[Mapping[str, object], ...],
        created_at: datetime | None = None,
    ) -> None:
        created = _naive_utc(created_at or datetime.now(UTC))
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_orchestration_result "
                "(task_id, trace_id, context_version, schema_version, status, replan_count, "
                "payload_json, transitions_json, trace_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(task_id),
                    str(trace_id),
                    context_version,
                    schema_version,
                    status,
                    replan_count,
                    _canonical(dict(payload)),
                    _canonical([dict(item) for item in transitions]),
                    _canonical([dict(item) for item in trace]),
                    created,
                ),
            )
            await cursor.execute(
                "SELECT trace_id, schema_version, status, replan_count, payload_json, transitions_json, "
                "trace_json FROM recommendation_orchestration_result "
                "WHERE task_id = %s AND context_version = %s",
                (str(task_id), context_version),
            )
            row = await cursor.fetchone()
        expected = (str(trace_id), schema_version, status, replan_count)
        if row is None or row[:4] != expected:
            raise ValueError("orchestration result identity conflict")
        if not _same_json(row[4], dict(payload)) or not _same_json(
            row[5], [dict(item) for item in transitions]
        ) or not _same_json(row[6], [dict(item) for item in trace]):
            raise ValueError("orchestration result payload conflict")


__all__ = ["MySQLAgentExecutionLogWriter"]
