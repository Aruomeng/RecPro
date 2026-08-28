"""Storage port for append-only knowledge review facts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.app.knowledge_review.domain import KnowledgeReviewActionFact, KnowledgeReviewProposal


class KnowledgeReviewRepository(Protocol):
    async def list_proposals(self) -> tuple[KnowledgeReviewProposal, ...]: ...
    async def get_proposal(self, proposal_uuid: UUID) -> KnowledgeReviewProposal | None: ...
    async def list_actions(self, proposal_uuid: UUID) -> tuple[KnowledgeReviewActionFact, ...]: ...
    async def list_actions_for_proposals(self, proposal_uuids: tuple[UUID, ...]) -> dict[UUID, tuple[KnowledgeReviewActionFact, ...]]: ...
    async def append_action(self, fact: KnowledgeReviewActionFact) -> tuple[KnowledgeReviewActionFact, bool]: ...


__all__ = ["KnowledgeReviewRepository"]
