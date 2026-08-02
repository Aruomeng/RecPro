"""Typed Agent envelope and result contracts without framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Generic, TypeVar
from uuid import UUID

from .enums import AgentResultStatus, MessageType


PayloadT = TypeVar("PayloadT")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_uuid(value: object, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{field_name} must be a UUID")


def _require_non_blank(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in value.items()
        )
    return False


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: UUID
    artifact_type: str
    schema_version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_uuid(self.artifact_id, "artifact_id")
        _require_non_blank(self.artifact_type, "artifact_type")
        _require_non_blank(self.schema_version, "schema_version")
        if not isinstance(self.content_hash, str):
            raise ValueError("content_hash must be a string")
        if len(self.content_hash) != 64:
            raise ValueError("content_hash must be a SHA-256 hex digest")
        try:
            int(self.content_hash, 16)
        except ValueError as exc:
            raise ValueError("content_hash must be hexadecimal") from exc


@dataclass(frozen=True, slots=True)
class AgentMessage:
    schema_version: str
    message_id: UUID
    trace_id: UUID
    task_id: UUID
    sender: str
    receiver: str
    message_type: MessageType
    payload: dict[str, Any]
    deadline_at: datetime
    idempotency_key: str
    context_version: int
    created_at: datetime
    attempt: int = 1
    causation_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.schema_version, "schema_version")
        for field_name, value in (
            ("message_id", self.message_id),
            ("trace_id", self.trace_id),
            ("task_id", self.task_id),
        ):
            _require_uuid(value, field_name)
        _require_non_blank(self.sender, "sender")
        _require_non_blank(self.receiver, "receiver")
        if not isinstance(self.message_type, MessageType):
            raise ValueError("message_type must be a MessageType")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a JSON object (dict)")
        if not _is_json_value(self.payload):
            raise ValueError("payload must contain only JSON-compatible values")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt < 1:
            raise ValueError("attempt must be at least 1")
        if (
            not isinstance(self.context_version, int)
            or isinstance(self.context_version, bool)
            or self.context_version < 1
        ):
            raise ValueError("context_version must be at least 1")
        _require_non_blank(self.idempotency_key, "idempotency_key")
        if self.causation_id is not None:
            _require_uuid(self.causation_id, "causation_id")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.deadline_at, "deadline_at")
        if self.deadline_at <= self.created_at:
            raise ValueError("deadline_at must be later than created_at")


@dataclass(frozen=True, slots=True)
class AgentResult(Generic[PayloadT]):
    result_id: UUID
    input_message_id: UUID
    agent_name: str
    agent_version: str
    status: AgentResultStatus
    confidence: float
    payload: PayloadT | None
    evidence_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    fallback_used: bool = False
    tool_calls: tuple[dict[str, Any], ...] = ()
    error_code: str | None = None
    duration_ms: int = 0

    def __post_init__(self) -> None:
        _require_uuid(self.result_id, "result_id")
        _require_uuid(self.input_message_id, "input_message_id")
        _require_non_blank(self.agent_name, "agent_name")
        _require_non_blank(self.agent_version, "agent_version")
        if not isinstance(self.status, AgentResultStatus):
            raise ValueError("status must be an AgentResultStatus")
        if (
            not isinstance(self.confidence, (int, float))
            or isinstance(self.confidence, bool)
        ):
            raise ValueError("confidence must be numeric")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if (
            not isinstance(self.duration_ms, int)
            or isinstance(self.duration_ms, bool)
            or self.duration_ms < 0
        ):
            raise ValueError("duration_ms must not be negative")
        if not isinstance(self.evidence_refs, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.evidence_refs
        ):
            raise ValueError("evidence_refs must be a tuple of non-blank strings")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs must not contain duplicates")
        if not isinstance(self.warnings, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.warnings
        ):
            raise ValueError("warnings must be a tuple of non-blank strings")
        if not isinstance(self.fallback_used, bool):
            raise ValueError("fallback_used must be boolean")
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(item, dict) and _is_json_value(item)
            for item in self.tool_calls
        ):
            raise ValueError("tool_calls must be a tuple of JSON-compatible dicts")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or not self.error_code.strip()
        ):
            raise ValueError("error_code must be null or a non-blank string")
        if self.status is AgentResultStatus.SUCCESS and self.payload is None:
            raise ValueError("SUCCESS must include a payload")
        if self.payload is not None and not _is_json_value(self.payload):
            raise ValueError("payload must contain only JSON-compatible values")
        if self.status is not AgentResultStatus.FAILED and self.error_code is not None:
            raise ValueError("only FAILED may include error_code")
        if self.status is AgentResultStatus.PARTIAL and not self.warnings:
            raise ValueError("PARTIAL must include at least one warning")
        if self.status is AgentResultStatus.FAILED:
            if self.payload is not None:
                raise ValueError("FAILED must not include a business payload")
            if not self.error_code:
                raise ValueError("FAILED must include error_code")
