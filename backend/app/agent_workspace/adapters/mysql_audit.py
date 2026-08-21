"""MySQL adapter that can only append and identity-check Workspace facts."""

from __future__ import annotations

import json
from typing import Any

from backend.app.agent_workspace.audit import AuditFact, DirectiveStateFact, WorkspaceEventFact


class MySQLAgentWorkspaceAuditAdapter:
    async def append(self, connection: Any, fact: AuditFact) -> None:
        if isinstance(fact, WorkspaceEventFact):
            await self._append_event(connection, fact)
            return
        if isinstance(fact, DirectiveStateFact):
            await self._append_directive(connection, fact)
            return
        raise TypeError("unsupported workspace audit fact")

    async def _append_event(self, connection: Any, fact: WorkspaceEventFact) -> None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO agent_workspace_event "
                "(event_uuid, workspace_id, session_id, user_id, event_sequence, event_type, "
                "agent_name, action_name, target_name, reason_code, confidence, public_payload_json, "
                "payload_sha256, occurred_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(fact.event_uuid), str(fact.workspace_id), str(fact.session_id), fact.user_id,
                    fact.event_sequence, fact.event_type, fact.agent_name, fact.action_name,
                    fact.target_name, fact.reason_code, fact.confidence, fact.public_payload_json,
                    fact.payload_sha256, fact.occurred_at.replace(tzinfo=None),
                ),
            )
            await cursor.execute(
                "SELECT workspace_id, session_id, user_id, event_sequence, event_type, payload_sha256 "
                "FROM agent_workspace_event WHERE event_uuid = %s",
                (str(fact.event_uuid),),
            )
            row = await cursor.fetchone()
        expected = (
            str(fact.workspace_id), str(fact.session_id), fact.user_id,
            fact.event_sequence, fact.event_type, fact.payload_sha256,
        )
        if row is None or tuple(_normalise(item) for item in row) != expected:
            raise ValueError("workspace event identity or payload conflict")

    async def _append_directive(self, connection: Any, fact: DirectiveStateFact) -> None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO interaction_directive_fact "
                "(fact_uuid, directive_id, workspace_id, session_id, user_id, directive_version, "
                "directive_type, directive_scope, behavior, fact_state, reason_codes_json, "
                "evidence_refs_json, payload_sha256, confidence, occurred_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(fact.fact_uuid), str(fact.directive_id), str(fact.workspace_id),
                    str(fact.session_id), fact.user_id, fact.directive_version, fact.directive_type,
                    fact.directive_scope, fact.behavior, fact.fact_state, fact.reason_codes_json,
                    fact.evidence_refs_json, fact.payload_sha256, fact.confidence,
                    fact.occurred_at.replace(tzinfo=None),
                ),
            )
            await cursor.execute(
                "SELECT directive_id, workspace_id, session_id, user_id, directive_version, "
                "directive_type, directive_scope, behavior, fact_state, reason_codes_json, "
                "evidence_refs_json, payload_sha256 FROM interaction_directive_fact WHERE fact_uuid = %s",
                (str(fact.fact_uuid),),
            )
            row = await cursor.fetchone()
        expected = (
            str(fact.directive_id), str(fact.workspace_id), str(fact.session_id), fact.user_id,
            fact.directive_version, fact.directive_type, fact.directive_scope, fact.behavior,
            fact.fact_state, json.loads(fact.reason_codes_json), json.loads(fact.evidence_refs_json),
            fact.payload_sha256,
        )
        if row is None:
            raise ValueError("directive fact could not be resolved after append")
        actual = tuple(_normalise(item) for item in row)
        if actual != expected:
            raise ValueError("directive fact identity or payload conflict")


def _normalise(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str) and value[:1] in {"[", "{"}:
        return json.loads(value)
    if isinstance(value, str):
        return value
    return int(value) if isinstance(value, int) else value


__all__ = ["MySQLAgentWorkspaceAuditAdapter"]
