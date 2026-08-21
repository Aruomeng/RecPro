"""Immutable, bounded audit facts for the demo Agent Workspace.

The broker only offers public, already-sanitised events to this module.  The
buffer never opens a database connection.  Guest workspaces and historical
replays are intentionally ignored.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Mapping
from uuid import UUID, uuid5


AUDIT_NAMESPACE = UUID("ad122dbf-4ce0-5d92-922b-46063e7613ae")
DIRECTIVE_FACT_STATES = frozenset(
    {"PROPOSED", "AUTO_APPLIED", "ACCEPTED", "DISMISSED", "UNDONE", "EXPIRED", "SUPERSEDED"}
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class WorkspaceEventFact:
    event_uuid: UUID
    workspace_id: UUID
    session_id: UUID
    user_id: int
    event_sequence: int
    event_type: str
    agent_name: str | None
    action_name: str | None
    target_name: str | None
    reason_code: str | None
    confidence: float | None
    public_payload_json: str
    payload_sha256: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DirectiveStateFact:
    fact_uuid: UUID
    directive_id: UUID
    workspace_id: UUID
    session_id: UUID
    user_id: int
    directive_version: int
    directive_type: str
    directive_scope: str
    behavior: str
    fact_state: str
    reason_codes_json: str
    evidence_refs_json: str
    payload_sha256: str
    confidence: float
    occurred_at: datetime


AuditFact = WorkspaceEventFact | DirectiveStateFact


class AuditCapacityError(RuntimeError):
    """Raised before an audit fact could exceed the reviewed memory bound."""


class AgentWorkspaceAuditBuffer:
    """Collect deterministic demo-only facts for a separately gated worker."""

    def __init__(self, *, enabled: bool = False, max_facts: int = 512, demo_user_id: int = 1001) -> None:
        if max_facts < 1:
            raise ValueError("audit max_facts must be positive")
        self.enabled = enabled
        self.max_facts = max_facts
        self.demo_user_id = demo_user_id
        self._facts: deque[AuditFact] = deque()
        self._keys: set[UUID] = set()
        self.rejected_count = 0

    @property
    def pending_count(self) -> int:
        return len(self._facts)

    def snapshot(self) -> tuple[AuditFact, ...]:
        return tuple(self._facts)

    def capture_event(
        self,
        *,
        mode: str,
        session_id: UUID,
        user_id: int,
        event: Mapping[str, object],
        replayed: bool = False,
    ) -> WorkspaceEventFact | None:
        if not self._eligible(mode=mode, user_id=user_id, replayed=replayed):
            return None
        workspace_id = UUID(str(event["workspace_id"]))
        sequence = int(event["sequence"])
        event_uuid = uuid5(AUDIT_NAMESPACE, f"workspace-event:{workspace_id}:{sequence}")
        public_payload = {
            key: value
            for key, value in event.items()
            if key not in {"schema_version", "sequence", "workspace_id", "occurred_at"}
        }
        encoded = _canonical(public_payload)
        fact = WorkspaceEventFact(
            event_uuid=event_uuid,
            workspace_id=workspace_id,
            session_id=session_id,
            user_id=user_id,
            event_sequence=sequence,
            event_type=str(event["event_type"])[:64],
            agent_name=_optional(event.get("agent_name"), 64),
            action_name=_optional(event.get("action"), 80),
            target_name=_optional(event.get("target"), 80),
            reason_code=_optional(event.get("reason_code"), 120),
            confidence=_confidence(event.get("confidence"), optional=True),
            public_payload_json=encoded,
            payload_sha256=sha256(encoded.encode()).hexdigest(),
            occurred_at=_parse_time(event["occurred_at"]),
        )
        self._append(event_uuid, fact)
        return fact

    def capture_directive(
        self,
        *,
        mode: str,
        workspace_id: UUID,
        session_id: UUID,
        user_id: int,
        directive: Mapping[str, object],
        state: str | None = None,
        occurred_at: object | None = None,
        replayed: bool = False,
    ) -> DirectiveStateFact | None:
        if not self._eligible(mode=mode, user_id=user_id, replayed=replayed):
            return None
        fact_state = str(state or directive.get("status", ""))
        if fact_state not in DIRECTIVE_FACT_STATES:
            raise ValueError("directive audit state is not allowed")
        directive_id = UUID(str(directive["directive_id"]))
        version = int(directive.get("directive_version", 1))
        fact_uuid = uuid5(AUDIT_NAMESPACE, f"directive-state:{directive_id}:{version}:{fact_state}")
        payload = directive.get("payload") if isinstance(directive.get("payload"), Mapping) else {}
        payload_json = _canonical(payload)
        fact = DirectiveStateFact(
            fact_uuid=fact_uuid,
            directive_id=directive_id,
            workspace_id=workspace_id,
            session_id=session_id,
            user_id=user_id,
            directive_version=version,
            directive_type=str(directive["type"])[:64],
            directive_scope=str(directive["scope"])[:80],
            behavior=str(directive["behavior"])[:24],
            fact_state=fact_state,
            reason_codes_json=_canonical(list(directive.get("reason_codes", []))[:20]),
            evidence_refs_json=_canonical(list(directive.get("evidence_refs", []))[:20]),
            payload_sha256=sha256(payload_json.encode()).hexdigest(),
            confidence=float(_confidence(directive.get("confidence"), optional=False)),
            occurred_at=_parse_time(occurred_at or directive.get("updated_at") or directive["created_at"]),
        )
        self._append(fact_uuid, fact)
        return fact

    def _eligible(self, *, mode: str, user_id: int, replayed: bool) -> bool:
        if not self.enabled or replayed or mode == "guest":
            return False
        if mode == "demo":
            return user_id == self.demo_user_id
        return mode == "authenticated" and user_id >= 10_000

    def acknowledge(self, fact_ids: set[UUID]) -> None:
        """Remove only successfully appended in-memory queue entries."""
        if not fact_ids:
            return
        self._facts = deque(fact for fact in self._facts if _fact_id(fact) not in fact_ids)
        self._keys.difference_update(fact_ids)

    def _append(self, key: UUID, fact: AuditFact) -> None:
        if key in self._keys:
            return
        if len(self._facts) >= self.max_facts:
            self.rejected_count += 1
            raise AuditCapacityError("agent workspace audit buffer capacity reached")
        self._facts.append(fact)
        self._keys.add(key)


def _fact_id(fact: AuditFact) -> UUID:
    return fact.event_uuid if isinstance(fact, WorkspaceEventFact) else fact.fact_uuid


def _optional(value: object, limit: int) -> str | None:
    return str(value)[:limit] if value is not None else None


def _confidence(value: object, *, optional: bool) -> float | None:
    if value is None and optional:
        return None
    numeric = float(value if value is not None else 0.0)
    if not 0 <= numeric <= 1:
        raise ValueError("audit confidence is outside 0..1")
    return numeric


__all__ = [
    "AgentWorkspaceAuditBuffer",
    "AuditCapacityError",
    "AuditFact",
    "DirectiveStateFact",
    "WorkspaceEventFact",
]
