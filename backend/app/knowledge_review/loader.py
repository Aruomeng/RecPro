"""Read public-safe v2 review candidates from a locally generated JSONL artifact."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from backend.app.knowledge_review.domain import KnowledgeReviewProposal


def load_v2_review_proposals(
    path: Path,
    *, graph_version: str = "lib-books-v2-20260828",
) -> tuple[KnowledgeReviewProposal, ...]:
    if not path.is_file():
        return ()
    proposals: list[KnowledgeReviewProposal] = []
    occurred_at = datetime.fromisoformat("2026-08-28T00:00:00+08:00")
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"review proposal line {line_number} is not an object")
        key = str(raw.get("proposal_key", ""))
        reason = str(raw.get("reason_code", ""))
        digest = str(raw.get("idempotency_sha256", ""))
        books = raw.get("book_keys")
        if (
            not key or not reason or len(digest) != 64
            or not isinstance(books, list) or not books
            or any(not isinstance(item, str) or not item for item in books)
        ):
            raise ValueError(f"review proposal line {line_number} violates the public contract")
        proposals.append(KnowledgeReviewProposal(
            proposal_uuid=uuid5(NAMESPACE_URL, f"recpro:{graph_version}:{key}"),
            proposal_type=str(raw.get("proposal_type", "WORK_IDENTITY_REVIEW")),
            graph_version=graph_version,
            subject_id=books[0], relation_type="INSTANCE_OF",
            object_id="UNRESOLVED_WORK",
            source_refs=tuple(f"graph:{graph_version}:{item}" for item in books[:20]),
            reason_codes=(reason,), confidence=float(raw.get("confidence", 0.0)),
            agent_name="ResourceSemanticAgent", task_id=None, workspace_id=None,
            idempotency_sha256=digest, occurred_at=occurred_at,
        ))
    if len(proposals) > 2048:
        raise ValueError("review proposal artifact exceeds the in-memory bound")
    return tuple(proposals)


__all__ = ["load_v2_review_proposals"]
