"""MySQL adapter limited to SELECT and append-only knowledge review facts."""

from __future__ import annotations

from datetime import UTC
import inspect
import json
from typing import Any
from uuid import UUID

from backend.app.knowledge_review.domain import (
    KnowledgeReviewAction,
    KnowledgeReviewActionFact,
    KnowledgeReviewProposal,
)


class MySQLKnowledgeReviewRepository:
    def __init__(self, connection_factory) -> None:
        self._connection_factory = connection_factory

    async def close(self) -> None:
        """Close the injected pool; review facts remain append-only."""

        close = getattr(self._connection_factory, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def runtime_metrics(self) -> dict[str, object] | None:
        snapshot = getattr(self._connection_factory, "snapshot", None)
        if not callable(snapshot):
            return None
        value = snapshot()
        as_dict = getattr(value, "as_dict", None)
        if callable(as_dict):
            value = as_dict()
        return dict(value) if isinstance(value, dict) else None

    async def list_proposals(self) -> tuple[KnowledgeReviewProposal, ...]:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT proposal_uuid, proposal_type, graph_version, subject_id, relation_type, "
                    "object_id, source_refs_json, reason_codes_json, confidence, agent_name, task_id, "
                    "workspace_id, idempotency_sha256, occurred_at FROM knowledge_review_proposal "
                    "ORDER BY occurred_at, proposal_uuid LIMIT 2048"
                )
                rows = await cursor.fetchall()
            await connection.rollback()
            return tuple(_proposal(row) for row in rows)
        finally:
            connection.close()

    async def get_proposal(self, proposal_uuid: UUID) -> KnowledgeReviewProposal | None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT proposal_uuid, proposal_type, graph_version, subject_id, relation_type, "
                    "object_id, source_refs_json, reason_codes_json, confidence, agent_name, task_id, "
                    "workspace_id, idempotency_sha256, occurred_at FROM knowledge_review_proposal "
                    "WHERE proposal_uuid = %s",
                    (str(proposal_uuid),),
                )
                row = await cursor.fetchone()
            await connection.rollback()
            return _proposal(row) if row is not None else None
        finally:
            connection.close()

    async def list_actions(self, proposal_uuid: UUID) -> tuple[KnowledgeReviewActionFact, ...]:
        return (await self.list_actions_for_proposals((proposal_uuid,))).get(proposal_uuid, ())

    async def list_actions_for_proposals(self, proposal_uuids: tuple[UUID, ...]) -> dict[UUID, tuple[KnowledgeReviewActionFact, ...]]:
        if not proposal_uuids:
            return {}
        if len(proposal_uuids) > 2048:
            raise ValueError("knowledge action batch exceeds bounds")
        connection = await self._connection_factory()
        try:
            placeholders = ",".join("%s" for _ in proposal_uuids)
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT fact_uuid, proposal_uuid, action_version, action, librarian_user_id, "
                    "reason_code, idempotency_key, occurred_at FROM knowledge_review_action_fact "
                    f"WHERE proposal_uuid IN ({placeholders}) ORDER BY proposal_uuid, action_version LIMIT 4096",
                    tuple(str(item) for item in proposal_uuids),
                )
                rows = await cursor.fetchall()
            await connection.rollback()
            grouped: dict[UUID, list[KnowledgeReviewActionFact]] = {item: [] for item in proposal_uuids}
            for row in rows:
                fact = _action(row)
                grouped.setdefault(fact.proposal_uuid, []).append(fact)
            return {key: tuple(value) for key, value in grouped.items()}
        finally:
            connection.close()

    async def append_action(self, fact: KnowledgeReviewActionFact) -> tuple[KnowledgeReviewActionFact, bool]:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT IGNORE INTO knowledge_review_action_fact "
                    "(fact_uuid, proposal_uuid, action_version, action, librarian_user_id, reason_code, "
                    "idempotency_key, occurred_at, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        str(fact.fact_uuid), str(fact.proposal_uuid), fact.version,
                        fact.action.value, fact.librarian_user_id, fact.reason_code,
                        fact.idempotency_key, fact.occurred_at.replace(tzinfo=None),
                        fact.occurred_at.replace(tzinfo=None),
                    ),
                )
                inserted = cursor.rowcount == 1
                await cursor.execute(
                    "SELECT fact_uuid, proposal_uuid, action_version, action, librarian_user_id, "
                    "reason_code, idempotency_key, occurred_at FROM knowledge_review_action_fact "
                    "WHERE idempotency_key = %s",
                    (fact.idempotency_key,),
                )
                row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("knowledge action append could not be resolved")
            persisted = _action(row)
            if persisted.proposal_uuid != fact.proposal_uuid or persisted.action is not fact.action:
                raise ValueError("knowledge action idempotency conflict")
            await connection.commit()
            return persisted, not inserted
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()


def _json_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ValueError("knowledge review JSON evidence is invalid")
    return tuple(decoded)


def _proposal(row: tuple[Any, ...]) -> KnowledgeReviewProposal:
    occurred = row[13].replace(tzinfo=UTC) if row[13].tzinfo is None else row[13]
    return KnowledgeReviewProposal(
        proposal_uuid=UUID(str(row[0])), proposal_type=str(row[1]), graph_version=str(row[2]),
        subject_id=str(row[3]), relation_type=str(row[4]), object_id=str(row[5]),
        source_refs=_json_tuple(row[6]), reason_codes=_json_tuple(row[7]),
        confidence=float(row[8]), agent_name=str(row[9]),
        task_id=UUID(str(row[10])) if row[10] else None,
        workspace_id=UUID(str(row[11])) if row[11] else None,
        idempotency_sha256=str(row[12]), occurred_at=occurred,
    )


def _action(row: tuple[Any, ...]) -> KnowledgeReviewActionFact:
    occurred = row[7].replace(tzinfo=UTC) if row[7].tzinfo is None else row[7]
    return KnowledgeReviewActionFact(
        fact_uuid=UUID(str(row[0])), proposal_uuid=UUID(str(row[1])), version=int(row[2]),
        action=KnowledgeReviewAction(str(row[3])), librarian_user_id=int(row[4]),
        reason_code=str(row[5]), idempotency_key=str(row[6]), occurred_at=occurred,
    )


__all__ = ["MySQLKnowledgeReviewRepository"]
