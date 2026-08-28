"""Immutable public-safe facts for librarian knowledge governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class KnowledgeReviewAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"


class KnowledgeReviewStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"


@dataclass(frozen=True, slots=True)
class KnowledgeReviewProposal:
    proposal_uuid: UUID
    proposal_type: str
    graph_version: str
    subject_id: str
    relation_type: str
    object_id: str
    source_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    confidence: float
    agent_name: str
    task_id: UUID | None
    workspace_id: UUID | None
    idempotency_sha256: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        bounded = (
            self.proposal_type, self.graph_version, self.subject_id,
            self.relation_type, self.object_id, self.agent_name,
        )
        if any(not value or len(value) > 256 for value in bounded):
            raise ValueError("knowledge proposal contains an invalid bounded field")
        if not 0 <= self.confidence <= 1:
            raise ValueError("knowledge proposal confidence must be bounded")
        if not 1 <= len(self.source_refs) <= 20 or not 1 <= len(self.reason_codes) <= 8:
            raise ValueError("knowledge proposal evidence is outside bounds")
        if len(self.idempotency_sha256) != 64:
            raise ValueError("knowledge proposal idempotency digest is invalid")


@dataclass(frozen=True, slots=True)
class KnowledgeReviewActionFact:
    fact_uuid: UUID
    proposal_uuid: UUID
    version: int
    action: KnowledgeReviewAction
    librarian_user_id: int
    reason_code: str
    idempotency_key: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.version < 1 or self.librarian_user_id < 1:
            raise ValueError("knowledge action version and actor must be positive")
        if not 1 <= len(self.reason_code) <= 64 or not 8 <= len(self.idempotency_key) <= 128:
            raise ValueError("knowledge action reason or idempotency key is invalid")


def status_from(actions: tuple[KnowledgeReviewActionFact, ...]) -> KnowledgeReviewStatus:
    if not actions:
        return KnowledgeReviewStatus.PENDING
    latest = max(actions, key=lambda fact: fact.version)
    return {
        KnowledgeReviewAction.APPROVE: KnowledgeReviewStatus.APPROVED,
        KnowledgeReviewAction.REJECT: KnowledgeReviewStatus.REJECTED,
        KnowledgeReviewAction.REQUEST_EVIDENCE: KnowledgeReviewStatus.EVIDENCE_REQUESTED,
    }[latest.action]


__all__ = [
    "KnowledgeReviewAction", "KnowledgeReviewActionFact",
    "KnowledgeReviewProposal", "KnowledgeReviewStatus", "status_from",
]
