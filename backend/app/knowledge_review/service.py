"""Application service for permissioned, append-only librarian decisions."""

from __future__ import annotations

from datetime import UTC, datetime
import inspect
from typing import Callable
from uuid import UUID, uuid4

from backend.app.knowledge_review.domain import (
    KnowledgeReviewAction,
    KnowledgeReviewActionFact,
    KnowledgeReviewProposal,
    KnowledgeReviewStatus,
    status_from,
)
from backend.app.knowledge_review.ports import KnowledgeReviewRepository
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


REVIEW_PERMISSION = "catalog.knowledge.review"


class KnowledgeReviewService:
    def __init__(
        self, repository: KnowledgeReviewRepository,
        *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def close(self) -> None:
        """Close an explicitly composed repository resource, if applicable."""

        close = getattr(self._repository, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def runtime_metrics(self) -> dict[str, object] | None:
        snapshot = getattr(self._repository, "runtime_metrics", None)
        if not callable(snapshot):
            return None
        value = snapshot()
        return dict(value) if isinstance(value, dict) else None

    @staticmethod
    def authorize(actor: AuthenticatedPrincipal) -> None:
        if not actor.has_permission(REVIEW_PERMISSION):
            raise PermissionError("catalog knowledge review permission is required")

    async def list_reviews(
        self, *, actor: AuthenticatedPrincipal,
        status: KnowledgeReviewStatus | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        self.authorize(actor)
        if not 1 <= limit <= 100:
            raise ValueError("knowledge review limit is outside bounds")
        proposals = await self._repository.list_proposals()
        action_map = await self._repository.list_actions_for_proposals(
            tuple(item.proposal_uuid for item in proposals),
        )
        views = []
        for proposal in proposals:
            actions = action_map.get(proposal.proposal_uuid, ())
            current = status_from(actions)
            if status is None or status is current:
                views.append(self._view(proposal, actions))
        return tuple(views[:limit])

    async def get_review(
        self, proposal_uuid: UUID, *, actor: AuthenticatedPrincipal,
    ) -> dict[str, object]:
        self.authorize(actor)
        proposal = await self._repository.get_proposal(proposal_uuid)
        if proposal is None:
            raise LookupError("knowledge review proposal not found")
        actions = await self._repository.list_actions(proposal_uuid)
        return self._view(proposal, actions)

    async def act(
        self, proposal_uuid: UUID, *, action: KnowledgeReviewAction,
        reason_code: str, idempotency_key: str,
        actor: AuthenticatedPrincipal,
    ) -> tuple[dict[str, object], bool]:
        self.authorize(actor)
        proposal = await self._repository.get_proposal(proposal_uuid)
        if proposal is None:
            raise LookupError("knowledge review proposal not found")
        current = await self._repository.list_actions(proposal_uuid)
        fact = KnowledgeReviewActionFact(
            fact_uuid=uuid4(), proposal_uuid=proposal_uuid,
            version=len(current) + 1, action=action,
            librarian_user_id=actor.user_id,
            reason_code=reason_code.strip(), idempotency_key=idempotency_key,
            occurred_at=self._clock(),
        )
        _, replayed = await self._repository.append_action(fact)
        return await self.get_review(proposal_uuid, actor=actor), replayed

    @staticmethod
    def _view(
        proposal: KnowledgeReviewProposal,
        actions: tuple[KnowledgeReviewActionFact, ...],
    ) -> dict[str, object]:
        return {
            "proposal_uuid": proposal.proposal_uuid,
            "proposal_type": proposal.proposal_type,
            "graph_version": proposal.graph_version,
            "subject_id": proposal.subject_id,
            "relation_type": proposal.relation_type,
            "object_id": proposal.object_id,
            "source_refs": list(proposal.source_refs),
            "reason_codes": list(proposal.reason_codes),
            "confidence": proposal.confidence,
            "agent_name": proposal.agent_name,
            "task_id": proposal.task_id,
            "workspace_id": proposal.workspace_id,
            "idempotency_sha256": proposal.idempotency_sha256,
            "occurred_at": proposal.occurred_at,
            "status": status_from(actions),
            "actions": [{
                "fact_uuid": fact.fact_uuid,
                "version": fact.version,
                "action": fact.action,
                "librarian_user_id": fact.librarian_user_id,
                "reason_code": fact.reason_code,
                "occurred_at": fact.occurred_at,
            } for fact in actions],
        }


__all__ = ["KnowledgeReviewService", "REVIEW_PERMISSION"]
