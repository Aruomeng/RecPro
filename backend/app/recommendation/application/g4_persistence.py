"""Pure write-plan construction for the opt-in G4 MySQL adapter.

The plan is deliberately separate from SQL execution.  It lets tests verify
all identities, status transitions, candidate channel rows, and fail-closed
conditions without connecting to a database.  The adapter that consumes this
plan owns one caller-supplied transaction and performs only forward INSERTs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence
from uuid import UUID

from backend.app.recommendation.agents.orchestrator import OrchestrationResult
from backend.app.recommendation.application.g4_projection import (
    G4ProjectionError,
    G4ProjectionVersions,
    G4ResourceProjection,
    build_http_execution_payload,
    derive_task_identity,
    extract_candidate_projections,
    extract_candidate_rows_for_persistence,
)
from backend.app.recommendation.domain.public import RecommendationTaskCommand


@dataclass(frozen=True, slots=True)
class G4TransitionFact:
    from_status: str
    to_status: str
    reason_code: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class G4CandidateFact:
    resource_id: int
    channel: str
    channel_rank: int
    raw_score: float
    normalized_score: float
    rrf_contribution: float
    evidence: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class G4ItemFact:
    resource_id: int
    rank_no: int
    final_score: float
    evidence_confidence: float
    primary_channel: str
    score_detail: Mapping[str, object]
    reason_summary: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class G4ProjectionWritePlan:
    """All facts required to append one G4 task/result batch."""

    task_id: UUID
    trace_id: UUID
    request_id: UUID
    user_id: int
    session_id: UUID
    scene: str
    input_text: str | None
    request_json: Mapping[str, object]
    intent_type: str
    intent_confidence: float
    status: str
    context_version: int
    evaluation_at: datetime
    started_at: datetime
    finished_at: datetime | None
    versions: Mapping[str, str | None]
    replan_count: int
    transitions: tuple[G4TransitionFact, ...]
    candidates: tuple[G4CandidateFact, ...]
    items: tuple[G4ItemFact, ...]
    decision: Mapping[str, object]
    questions: tuple[Mapping[str, object], ...]
    warnings: tuple[str, ...]
    trace_steps: tuple[Mapping[str, object], ...]
    context_response: Mapping[str, object] | None


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise G4ProjectionError(f"{name} must be a JSON object")
    return value


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise G4ProjectionError(f"{name} must be timezone-aware")


def _bounded(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise G4ProjectionError(f"{name} must be numeric")
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise G4ProjectionError(f"{name} must be between 0 and 1")
    return numeric


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise G4ProjectionError(f"{name} must be non-blank")
    return value.strip()


def _request_json(command: RecommendationTaskCommand) -> dict[str, object]:
    return {
        "request_id": str(command.request_id),
        "session_id": str(command.session_id),
        "user_id": command.user_id,
        "scene": command.scene,
        "input_text": command.input_text,
        "resource_types": list(command.resource_types),
        "output_type": command.output_type,
        "source_resource_id": command.source_resource_id,
        "source_item_id": command.source_item_id,
        "evaluation_at": (
            command.evaluation_at.isoformat() if command.evaluation_at is not None else None
        ),
        "constraints": dict(command.constraints),
        "limit": command.limit,
    }


def build_g4_projection_write_plan(
    command: RecommendationTaskCommand,
    result: OrchestrationResult,
    *,
    resources: Mapping[int, G4ResourceProjection],
    versions: G4ProjectionVersions,
    evaluation_at: datetime,
    started_at: datetime,
) -> G4ProjectionWritePlan:
    """Validate and freeze a forward-only G4 projection batch."""

    _aware(evaluation_at, "evaluation_at")
    _aware(started_at, "started_at")
    identity = derive_task_identity(command)
    if result.task_id != identity.task_id or result.trace_id != identity.trace_id:
        raise G4ProjectionError("orchestration identity does not match command identity")
    if result.context_version < 1:
        raise G4ProjectionError("orchestration context_version must be positive")
    payload = _mapping(result.payload, "orchestration payload")
    intent = _mapping(payload.get("intent"), "orchestration intent")
    intent_type = _required_text(intent.get("intent_type"), "intent_type")
    intent_confidence = _bounded(intent.get("confidence"), "intent confidence")
    decision = _mapping(payload.get("decision"), "orchestration decision")
    for key in (
        "output_type",
        "delivery_strategy",
        "explanation_level",
        "adaptation_state",
        "decision_reason_codes",
        "decision_reason",
        "policy_version",
    ):
        if key not in decision:
            raise G4ProjectionError(f"orchestration decision missing field {key}")
    reason_codes = decision["decision_reason_codes"]
    if not isinstance(reason_codes, Sequence) or isinstance(reason_codes, (str, bytes, bytearray)):
        raise G4ProjectionError("decision_reason_codes must be a list")
    if not reason_codes or any(not isinstance(code, str) or not code.strip() for code in reason_codes):
        raise G4ProjectionError("decision_reason_codes must contain non-blank strings")
    decision_reason = _required_text(decision["decision_reason"], "decision_reason")
    policy_version = _required_text(decision["policy_version"], "policy_version")
    status = result.status.value
    if status not in {"WAITING_CLARIFICATION", "COMPLETED", "DEGRADED_COMPLETED"}:
        raise G4ProjectionError(f"unsupported projection status {status}")
    warnings_value = payload.get("warnings", [])
    if not isinstance(warnings_value, Sequence) or isinstance(
        warnings_value, (str, bytes, bytearray)
    ):
        raise G4ProjectionError("warnings must be a list")
    warnings = tuple(_required_text(value, "warning") for value in warnings_value)
    transitions: list[G4TransitionFact] = []
    for raw in result.transitions:
        transition = _mapping(raw, "transition")
        transitions.append(
            G4TransitionFact(
                from_status=_required_text(transition.get("from_status"), "from_status"),
                to_status=_required_text(transition.get("to_status"), "to_status"),
                reason_code=_required_text(transition.get("reason_code"), "reason_code"),
                occurred_at=started_at,
            )
        )
    questions_value = payload.get("questions", [])
    if not isinstance(questions_value, Sequence) or isinstance(
        questions_value, (str, bytes, bytearray)
    ):
        raise G4ProjectionError("questions must be a list")
    questions: tuple[Mapping[str, object], ...] = tuple(
        _mapping(value, "clarification question") for value in questions_value
    )
    candidates: list[G4CandidateFact] = []
    items: list[G4ItemFact] = []
    if status in {"COMPLETED", "DEGRADED_COMPLETED"}:
        candidate_rows = extract_candidate_rows_for_persistence(
            result, resources=resources
        )
        candidates = [
            G4CandidateFact(
                resource_id=int(row["resource_id"]),
                channel=str(row["channel"]),
                channel_rank=int(row["channel_rank"]),
                raw_score=float(row["raw_score"]),
                normalized_score=float(row["normalized_score"]),
                rrf_contribution=float(row["rrf_contribution"]),
                evidence=_mapping(row["evidence"], "candidate evidence"),
            )
            for row in candidate_rows
        ]
        for candidate in extract_candidate_projections(result, resources=resources):
            scores = _mapping(candidate.get("channel_scores"), "channel_scores")
            ranks = _mapping(candidate.get("channel_ranks"), "channel_ranks")
            primary = candidate.get("primary_channel")
            if primary is None:
                raise G4ProjectionError("persistence projection requires primary_channel")
            score_detail = {
                "channel_scores": dict(scores),
                "channel_ranks": dict(ranks),
                "rrf_score": candidate["score"],
                "negative_penalty": candidate["negative_penalty"],
            }
            items.append(
                G4ItemFact(
                    resource_id=int(candidate["resource_id"]),
                    rank_no=int(candidate["rank_no"]),
                    final_score=float(candidate["score"]),
                    evidence_confidence=float(candidate["evidence_confidence"]),
                    primary_channel=str(primary),
                    score_detail=score_detail,
                    reason_summary=str(candidate["reason_summary"]),
                    evidence_refs=tuple(str(ref) for ref in candidate["evidence_refs"]),
                )
            )
        if len(items) == 0:
            raise G4ProjectionError("completed projection requires at least one item")
    elif questions == ():
        raise G4ProjectionError("waiting clarification requires questions")
    versions_map: dict[str, str | None] = {
        "config_bundle": versions.config_bundle,
        "policy": policy_version,
        "ranking": versions.ranking,
        "behavior_formula": versions.behavior_formula,
        "embedding": versions.embedding,
        "graph": versions.graph,
        "prompt": versions.prompt,
        "dataset": versions.dataset,
    }
    context_response: Mapping[str, object] | None = None
    if status == "WAITING_CLARIFICATION":
        context_response = build_http_execution_payload(
            result,
            resources=resources,
            versions=versions,
            evaluation_at=evaluation_at,
        )
    return G4ProjectionWritePlan(
        task_id=result.task_id,
        trace_id=result.trace_id,
        request_id=command.request_id,
        user_id=command.user_id,
        session_id=command.session_id,
        scene=command.scene,
        input_text=command.input_text,
        request_json=_request_json(command),
        intent_type=intent_type,
        intent_confidence=intent_confidence,
        status=status,
        context_version=result.context_version,
        evaluation_at=evaluation_at,
        started_at=started_at,
        finished_at=started_at if status in {"COMPLETED", "DEGRADED_COMPLETED"} else None,
        versions=versions_map,
        replan_count=result.replan_count,
        transitions=tuple(transitions),
        candidates=tuple(candidates),
        items=tuple(items),
        decision={
            "output_type": decision["output_type"],
            "delivery_strategy": decision["delivery_strategy"],
            "explanation_level": decision["explanation_level"],
            "adaptation_state": decision["adaptation_state"],
            "decision_reason_codes": list(reason_codes),
            "decision_reason": decision_reason,
            "policy_version": policy_version,
        },
        questions=questions,
        warnings=warnings,
        trace_steps=tuple(_mapping(step, "trace step") for step in result.trace),
        context_response=context_response,
    )


__all__ = [
    "G4CandidateFact",
    "G4ItemFact",
    "G4ProjectionWritePlan",
    "G4TransitionFact",
    "build_g4_projection_write_plan",
]
