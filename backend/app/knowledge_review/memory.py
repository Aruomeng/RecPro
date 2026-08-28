"""Bounded in-memory review repository used before approved MySQL migration."""

from __future__ import annotations

import asyncio
from uuid import UUID

from backend.app.knowledge_review.domain import KnowledgeReviewActionFact, KnowledgeReviewProposal


class InMemoryKnowledgeReviewRepository:
    def __init__(self, proposals: tuple[KnowledgeReviewProposal, ...] = (), *, max_actions: int = 4096) -> None:
        if len(proposals) > 2048 or not 1 <= max_actions <= 8192:
            raise ValueError("knowledge review memory bounds are invalid")
        self._proposals = {item.proposal_uuid: item for item in proposals}
        self._actions: dict[UUID, list[KnowledgeReviewActionFact]] = {}
        self._idempotency: dict[str, KnowledgeReviewActionFact] = {}
        self._max_actions = max_actions
        self._lock = asyncio.Lock()

    async def list_proposals(self) -> tuple[KnowledgeReviewProposal, ...]:
        return tuple(sorted(self._proposals.values(), key=lambda item: (item.occurred_at, str(item.proposal_uuid))))

    async def get_proposal(self, proposal_uuid: UUID) -> KnowledgeReviewProposal | None:
        return self._proposals.get(proposal_uuid)

    async def list_actions(self, proposal_uuid: UUID) -> tuple[KnowledgeReviewActionFact, ...]:
        return tuple(self._actions.get(proposal_uuid, ()))

    async def list_actions_for_proposals(self, proposal_uuids: tuple[UUID, ...]) -> dict[UUID, tuple[KnowledgeReviewActionFact, ...]]:
        return {proposal_uuid: tuple(self._actions.get(proposal_uuid, ())) for proposal_uuid in proposal_uuids}

    async def append_action(self, fact: KnowledgeReviewActionFact) -> tuple[KnowledgeReviewActionFact, bool]:
        async with self._lock:
            replay = self._idempotency.get(fact.idempotency_key)
            if replay is not None:
                if replay.proposal_uuid != fact.proposal_uuid or replay.action != fact.action:
                    raise ValueError("knowledge review idempotency conflict")
                return replay, True
            if fact.proposal_uuid not in self._proposals:
                raise LookupError("knowledge review proposal not found")
            if len(self._idempotency) >= self._max_actions:
                raise OverflowError("knowledge review action capacity exceeded")
            current = self._actions.setdefault(fact.proposal_uuid, [])
            if fact.version != len(current) + 1:
                raise ValueError("knowledge review action version conflict")
            current.append(fact)
            self._idempotency[fact.idempotency_key] = fact
            return fact, False


__all__ = ["InMemoryKnowledgeReviewRepository"]
