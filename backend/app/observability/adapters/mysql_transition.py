"""MySQL append-only state-transition audit adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.app.observability.domain.transition import StateTransition
from backend.app.observability.ports.audit import StateTransitionSink


def _json(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class MySQLStateTransitionWriter(StateTransitionSink):
    """Append and identity-check one transition in the caller's transaction."""

    async def append(self, connection: Any, transition: StateTransition) -> None:
        created_at = transition.created_at_utc()
        detail_json = transition.detail_json()
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO domain_state_transition "
                "(transition_uuid, module_name, aggregate_type, aggregate_id, transition_type, "
                "from_state, to_state, version_before, version_after, causation_ref, actor_type, "
                "actor_ref, detail_json, created_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(transition.transition_uuid),
                    transition.module_name,
                    transition.aggregate_type,
                    transition.aggregate_id,
                    transition.transition_type,
                    transition.from_state,
                    transition.to_state,
                    transition.version_before,
                    transition.version_after,
                    transition.causation_ref,
                    transition.actor_type,
                    transition.actor_ref,
                    detail_json,
                    created_at,
                ),
            )
            await cursor.execute(
                "SELECT transition_uuid, module_name, aggregate_type, aggregate_id, transition_type, "
                "from_state, to_state, version_before, version_after, causation_ref, actor_type, "
                "actor_ref, detail_json FROM domain_state_transition WHERE transition_uuid = %s",
                (str(transition.transition_uuid),),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ValueError("state transition could not be resolved after append")
        actual_detail = _json(row[12]) if row[12] is not None else None
        expected_detail = _json(detail_json) if detail_json is not None else None
        actual = (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]) if row[5] is not None else None,
            str(row[6]),
            int(row[7]) if row[7] is not None else None,
            int(row[8]),
            str(row[9]),
            str(row[10]),
            str(row[11]) if row[11] is not None else None,
            actual_detail,
        )
        expected = (
            str(transition.transition_uuid),
            transition.module_name,
            transition.aggregate_type,
            transition.aggregate_id,
            transition.transition_type,
            transition.from_state,
            transition.to_state,
            transition.version_before,
            transition.version_after,
            transition.causation_ref,
            transition.actor_type,
            transition.actor_ref,
            expected_detail,
        )
        if actual != expected:
            raise ValueError("state transition identity or payload conflict")


__all__ = ["MySQLStateTransitionWriter"]
