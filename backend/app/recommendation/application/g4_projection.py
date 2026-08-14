"""Pure contracts for the future G4-to-HTTP recommendation projection.

The G4 orchestrator deliberately returns Agent-shaped facts (resource IDs,
scores, channels, and evidence references).  The HTTP contract needs a
materialized resource summary and a database record identity as well.  This
module keeps that boundary explicit and side-effect free so the eventual
MySQL adapter can compose both projections in one transaction without making
the HTTP layer depend on Agent implementations.

No function in this module opens a connection, calls an external provider, or
mutates a database.  Incomplete Agent payloads fail closed instead of being
silently converted into a misleading recommendation response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.app.recommendation.agents.orchestrator import (
    OrchestrationRequest,
    OrchestrationResult,
)
from backend.app.recommendation.domain.public import RecommendationTaskCommand
from backend.app.shared_kernel.contracts.autonomy import (
    AgentAutonomyError,
    validate_decision_dict,
)
from backend.app.shared_kernel.contracts.enums import TaskStatus


class G4ProjectionError(ValueError):
    """The Agent result cannot be safely projected into the public contract."""


@dataclass(frozen=True, slots=True)
class G4TaskIdentity:
    """Stable task and trace IDs shared by G3 idempotency and G4 replay."""

    task_id: UUID
    trace_id: UUID


@dataclass(frozen=True, slots=True)
class G4ProjectionVersions:
    """Immutable version bundle required by the public execution response."""

    config_bundle: str
    dataset: str
    ranking: str = "ranking-g4-v1"
    behavior_formula: str = "profile-g4-v1"
    embedding: str | None = None
    graph: str | None = None
    prompt: str | None = None

    def __post_init__(self) -> None:
        for name in ("config_bundle", "dataset", "ranking", "behavior_formula"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-blank string")
        for name in ("embedding", "graph", "prompt"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be null or a non-blank string")


@dataclass(frozen=True, slots=True)
class G4ResourceProjection:
    """Minimum catalog projection needed by ``RecommendationExecutionResponse``."""

    resource_id: int
    resource_type: str
    title: str
    authors: tuple[str, ...]
    publication_year: int | None
    availability_status: str

    def __post_init__(self) -> None:
        if isinstance(self.resource_id, bool) or self.resource_id < 1:
            raise ValueError("resource_id must be positive")
        for name in ("resource_type", "title", "availability_status"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-blank string")
        if not isinstance(self.authors, tuple) or not all(
            isinstance(author, str) and author.strip() for author in self.authors
        ):
            raise ValueError("authors must be a tuple of non-blank strings")
        if self.publication_year is not None and (
            isinstance(self.publication_year, bool) or self.publication_year < 1
        ):
            raise ValueError("publication_year must be null or positive")


def derive_task_identity(command: RecommendationTaskCommand) -> G4TaskIdentity:
    """Derive replay-stable IDs without opening a persistence boundary.

    The names intentionally match the existing G3 adapter.  A future G4
    adapter can therefore claim the same request exactly once rather than
    creating a second task identity for the same HTTP idempotency key.
    """

    return G4TaskIdentity(
        task_id=uuid5(NAMESPACE_URL, f"task:{command.user_id}:{command.request_id}"),
        trace_id=uuid5(NAMESPACE_URL, f"trace:{command.user_id}:{command.request_id}"),
    )


def build_orchestration_request(
    command: RecommendationTaskCommand,
    *,
    evaluation_at: datetime,
    deadline_at: datetime,
    context_version: int = 1,
    identity: G4TaskIdentity | None = None,
    initial_status: TaskStatus = TaskStatus.CREATED,
) -> OrchestrationRequest:
    """Map a transport-neutral task command to one explicit G4 request.

    ``evaluation_at`` and ``deadline_at`` are required here rather than being
    generated implicitly.  This makes retries and Agent message IDs
    reproducible and prevents a future HTTP adapter from accidentally mixing
    the task's frozen evaluation time with a later wall-clock value.
    """

    if evaluation_at.tzinfo is None or evaluation_at.utcoffset() is None:
        raise G4ProjectionError("evaluation_at must be timezone-aware")
    if deadline_at.tzinfo is None or deadline_at.utcoffset() is None:
        raise G4ProjectionError("deadline_at must be timezone-aware")
    if deadline_at <= evaluation_at:
        raise G4ProjectionError("deadline_at must be later than evaluation_at")
    if isinstance(context_version, bool) or context_version < 1:
        raise G4ProjectionError("context_version must be positive")
    resolved_identity = identity or derive_task_identity(command)
    # Preserve the explicit HOME-empty shape so the policy Agent can ask for
    # the missing resource/topic slots.  For an otherwise meaningful request,
    # an omitted resource filter keeps the public default of BOOK+PAPER.
    clarification_shape = (
        command.scene == "HOME"
        and not (command.input_text or "").strip()
        and not command.resource_types
        and command.output_type is None
    )
    resource_types = (
        () if clarification_shape else tuple(command.resource_types or ("BOOK", "PAPER"))
    )
    return OrchestrationRequest(
        task_id=resolved_identity.task_id,
        trace_id=resolved_identity.trace_id,
        user_id=command.user_id,
        session_id=command.session_id,
        input_text=command.input_text,
        resource_types=resource_types,
        output_type=command.output_type,
        constraints=dict(command.constraints),
        context_version=context_version,
        evaluation_at=evaluation_at,
        deadline_at=deadline_at,
        scene=command.scene,
        limit=command.limit,
        initial_status=initial_status,
    )


def split_recall_channels(value: object) -> tuple[str, ...]:
    """Validate a compact Agent channel string for append-only persistence.

    G4 may expose ``MYSQL+GRAPH+VECTOR`` as one candidate attribute while the
    G3 candidate table stores one channel per row in ``VARCHAR(16)``.  The
    projection boundary preserves each component explicitly and rejects
    malformed or overlong channel names before SQL is attempted.
    """

    if not isinstance(value, str) or not value.strip():
        raise G4ProjectionError("candidate channel must be a non-blank string")
    channels = tuple(part.strip().upper() for part in value.split("+"))
    if not channels or any(not part or len(part) > 16 for part in channels):
        raise G4ProjectionError("candidate channel components must be 1..16 characters")
    if len(set(channels)) != len(channels):
        raise G4ProjectionError("candidate channel components must be unique")
    return channels


def _required_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise G4ProjectionError(f"{name} must be a JSON object")
    return value


def _project_agent_actions(result: OrchestrationResult) -> list[dict[str, Any]]:
    """Expose only validated Agent decisions at the explicit HTTP boundary."""

    actions: list[dict[str, Any]] = []
    for step in result.trace:
        if not isinstance(step, Mapping):
            raise G4ProjectionError("Agent trace step must be a mapping")
        agent_name = step.get("agent_name")
        autonomy = step.get("autonomy")
        if not isinstance(agent_name, str) or not agent_name.strip():
            raise G4ProjectionError("Agent trace step is missing agent_name")
        try:
            decision = validate_decision_dict(agent_name, autonomy)
        except AgentAutonomyError as exc:
            raise G4ProjectionError(
                f"Agent trace action is outside the role contract: {agent_name}"
            ) from exc
        step_no = step.get("step_no")
        message_type = step.get("message_type")
        if isinstance(step_no, bool) or not isinstance(step_no, int) or step_no < 1:
            raise G4ProjectionError("Agent trace step_no must be positive")
        if not isinstance(message_type, str) or not message_type.strip():
            raise G4ProjectionError("Agent trace message_type must be non-blank")
        agent_version = step.get("agent_version")
        if not isinstance(agent_version, str) or not agent_version.strip():
            raise G4ProjectionError("Agent trace agent_version must be non-blank")
        actions.append(
            {
                "step_no": step_no,
                "agent_name": agent_name,
                "agent_version": agent_version,
                "message_type": message_type,
                **decision.as_dict(),
            }
        )
    if not actions:
        raise G4ProjectionError("G4 HTTP projection requires Agent autonomy trace")
    return actions


def _bounded_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise G4ProjectionError(f"{name} must be numeric")
    number = float(value)
    if not isfinite(number) or not 0.0 <= number <= 1.0:
        raise G4ProjectionError(f"{name} must be finite and between 0 and 1")
    return number


def _candidate_items(
    result: OrchestrationResult,
    *,
    resources: Mapping[int, G4ResourceProjection],
) -> list[dict[str, Any]]:
    payload = _required_mapping(result.payload, "orchestration payload")
    raw_items = payload.get("items")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes, bytearray)):
        raise G4ProjectionError("orchestration payload.items must be a list")
    raw_explanations = payload.get("explanations")
    if not isinstance(raw_explanations, Sequence) or isinstance(
        raw_explanations, (str, bytes, bytearray)
    ):
        raise G4ProjectionError("orchestration payload.explanations must be a list")
    explanations: dict[int, Mapping[str, Any]] = {}
    for raw in raw_explanations:
        explanation = _required_mapping(raw, "explanation")
        try:
            resource_id = int(explanation["resource_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise G4ProjectionError("explanation.resource_id is required") from exc
        if resource_id in explanations:
            raise G4ProjectionError("explanations must contain one row per resource")
        explanations[resource_id] = explanation

    projected: list[dict[str, Any]] = []
    seen_resources: set[int] = set()
    for raw in raw_items:
        item = _required_mapping(raw, "ranked item")
        try:
            resource_id = int(item["resource_id"])
            rank_no = int(item["rank_no"])
        except (KeyError, TypeError, ValueError) as exc:
            raise G4ProjectionError("ranked item requires resource_id and rank_no") from exc
        if resource_id in seen_resources or rank_no != len(projected) + 1:
            raise G4ProjectionError("ranked items must have unique contiguous ranks")
        seen_resources.add(resource_id)
        resource = resources.get(resource_id)
        if resource is None:
            raise G4ProjectionError(f"catalog projection missing resource {resource_id}")
        channels = split_recall_channels(item.get("channel"))
        score = _bounded_number(item.get("score"), "ranked item.score")
        # This field must be produced by the ranking/recall pipeline.  It is
        # intentionally not inferred from score: score and evidence confidence
        # have different semantics in the public contract.
        evidence_confidence = _bounded_number(
            item.get("evidence_confidence"), "ranked item.evidence_confidence"
        )
        explanation = explanations.get(resource_id)
        if explanation is None:
            raise G4ProjectionError(f"explanation missing for resource {resource_id}")
        summary = explanation.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise G4ProjectionError("explanation.summary must be non-blank")
        refs = explanation.get("evidence_refs")
        if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes, bytearray)):
            raise G4ProjectionError("explanation.evidence_refs must be a list")
        evidence_refs = [str(ref).strip() for ref in refs]
        if not evidence_refs or any(not ref for ref in evidence_refs):
            raise G4ProjectionError("explanation.evidence_refs must be non-empty")
        raw_channel_scores = item.get("channel_scores")
        raw_channel_ranks = item.get("channel_ranks")
        channel_scores: dict[str, float] | None = None
        channel_ranks: dict[str, int] | None = None
        if raw_channel_scores is not None or raw_channel_ranks is not None:
            score_map = _required_mapping(raw_channel_scores, "ranked item.channel_scores")
            rank_map = _required_mapping(raw_channel_ranks, "ranked item.channel_ranks")
            if set(str(key).upper() for key in score_map) != set(channels) or set(
                str(key).upper() for key in rank_map
            ) != set(channels):
                raise G4ProjectionError(
                    "channel_scores and channel_ranks must match candidate channels"
                )
            channel_scores = {
                str(key).upper(): _bounded_number(value, "channel score")
                for key, value in score_map.items()
            }
            channel_ranks = {}
            for key, value in rank_map.items():
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise G4ProjectionError("channel ranks must be positive integers")
                channel_ranks[str(key).upper()] = value
        primary_channel = item.get("primary_channel")
        if primary_channel is not None:
            if not isinstance(primary_channel, str) or primary_channel.upper() not in channels:
                raise G4ProjectionError("primary_channel must be one candidate channel")
            primary_channel = primary_channel.upper()
        negative_penalty = _bounded_number(
            item.get("negative_penalty", 0.0), "ranked item.negative_penalty"
        )
        projected.append(
            {
                "rank_no": rank_no,
                "resource_id": resource_id,
                "resource": {
                    "resource_id": resource.resource_id,
                    "resource_type": resource.resource_type,
                    "title": resource.title,
                    "authors": list(resource.authors),
                    "publication_year": resource.publication_year,
                    "availability_status": resource.availability_status,
                },
                "channels": list(channels),
                "score": score,
                "evidence_confidence": evidence_confidence,
                "reason_summary": summary,
                "evidence_refs": evidence_refs,
                "channel_scores": channel_scores,
                "channel_ranks": channel_ranks,
                "primary_channel": primary_channel,
                "negative_penalty": negative_penalty,
            }
        )
    if set(explanations) != seen_resources:
        raise G4ProjectionError("explanations must match ranked item resources exactly")
    return projected


def extract_candidate_projections(
    result: OrchestrationResult,
    *,
    resources: Mapping[int, G4ResourceProjection],
) -> tuple[dict[str, Any], ...]:
    """Return validated candidate facts for a persistence adapter.

    The returned values still carry channels and evidence references.  They
    are intentionally separate from the public HTTP item DTO, which must not
    expose storage-only ranking details.
    """

    return tuple(_candidate_items(result, resources=resources))


def extract_candidate_rows_for_persistence(
    result: OrchestrationResult,
    *,
    resources: Mapping[int, G4ResourceProjection],
) -> tuple[dict[str, Any], ...]:
    """Expand enriched Agent candidates into append-only SQL row facts.

    HTTP can render a candidate with only its overall score, but the G3
    candidate table intentionally stores one row per recall channel.  This
    function requires channel-specific scores and ranks, so a result that has
    not been enriched by the real recall Agent cannot reach SQL.
    """

    rows: list[dict[str, Any]] = []
    for candidate in _candidate_items(result, resources=resources):
        scores = candidate.get("channel_scores")
        ranks = candidate.get("channel_ranks")
        if not isinstance(scores, dict) or not isinstance(ranks, dict):
            raise G4ProjectionError(
                "persistence projection requires channel_scores and channel_ranks"
            )
        for channel in candidate["channels"]:
            score = float(scores[channel])
            channel_rank = int(ranks[channel])
            rows.append(
                {
                    "resource_id": candidate["resource_id"],
                    "channel": channel,
                    "channel_rank": channel_rank,
                    "raw_score": score,
                    "normalized_score": score,
                    "rrf_contribution": score / (60.0 + channel_rank),
                    "evidence": {
                        "resource_id": candidate["resource_id"],
                        "channel": channel,
                        "evidence_refs": list(candidate["evidence_refs"]),
                    },
                }
            )
    return tuple(rows)


def build_http_execution_payload(
    result: OrchestrationResult,
    *,
    resources: Mapping[int, G4ResourceProjection],
    versions: G4ProjectionVersions,
    evaluation_at: datetime,
    record_id: int | None = None,
    item_ids: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """Project one complete G4 result into the HTTP response shape.

    This is a pure mapper.  It does not persist ``record_id`` and therefore
    can be called before or after the MySQL projection insert, depending on
    the adapter's transaction choreography.
    """

    if evaluation_at.tzinfo is None or evaluation_at.utcoffset() is None:
        raise G4ProjectionError("evaluation_at must be timezone-aware")
    if record_id is not None and (isinstance(record_id, bool) or record_id < 1):
        raise G4ProjectionError("record_id must be null or positive")
    payload = _required_mapping(result.payload, "orchestration payload")
    decision = _required_mapping(payload.get("decision"), "orchestration decision")
    required_decision = (
        "output_type",
        "delivery_strategy",
        "explanation_level",
        "adaptation_state",
        "decision_reason_codes",
        "decision_reason",
        "policy_version",
    )
    missing = [key for key in required_decision if key not in decision]
    if missing:
        raise G4ProjectionError(f"orchestration decision missing fields: {', '.join(missing)}")
    reason_codes = decision["decision_reason_codes"]
    if not isinstance(reason_codes, Sequence) or isinstance(reason_codes, (str, bytes, bytearray)):
        raise G4ProjectionError("decision_reason_codes must be a list")
    if not reason_codes or any(not isinstance(code, str) or not code.strip() for code in reason_codes):
        raise G4ProjectionError("decision_reason_codes must be non-empty strings")
    reason = decision["decision_reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise G4ProjectionError("decision_reason must be non-blank")
    policy_version = decision["policy_version"]
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise G4ProjectionError("policy_version must be non-blank")
    status = result.status.value
    projected_items: list[dict[str, Any]] = []
    questions = payload.get("questions")
    if status in {"COMPLETED", "DEGRADED_COMPLETED"}:
        candidate_projections = _candidate_items(result, resources=resources)
        if item_ids is None:
            raise G4ProjectionError(
                "completed HTTP projection requires persisted item_ids"
            )
        projected_items = []
        for candidate in candidate_projections:
            resource_id = int(candidate["resource_id"])
            item_id = item_ids.get(resource_id)
            if item_id is None or isinstance(item_id, bool) or item_id < 1:
                raise G4ProjectionError(
                    f"persisted item_id missing for resource {resource_id}"
                )
            projected_items.append(
                {
                    "item_id": item_id,
                    "resource": candidate["resource"],
                    "rank_no": candidate["rank_no"],
                    "group_id": None,
                    "reason_summary": candidate["reason_summary"],
                    "evidence_confidence": candidate["evidence_confidence"],
                    "unavailable_now": False,
                }
            )
        questions = None
    elif status == "WAITING_CLARIFICATION":
        if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes, bytearray)):
            raise G4ProjectionError("waiting clarification requires questions")
    else:
        raise G4ProjectionError(f"HTTP projection does not support status {status}")
    warnings = payload.get("warnings", [])
    if not isinstance(warnings, Sequence) or isinstance(warnings, (str, bytes, bytearray)):
        raise G4ProjectionError("warnings must be a list")
    if any(not isinstance(warning, str) or not warning.strip() for warning in warnings):
        raise G4ProjectionError("warnings must contain non-blank strings")
    agent_actions = _project_agent_actions(result)
    return {
        "task_id": str(result.task_id),
        "record_id": record_id,
        "trace_id": str(result.trace_id),
        "status": status,
        "context_version": result.context_version,
        "evaluation_at": evaluation_at,
        "decision": {
            "output_type": decision["output_type"],
            "delivery_strategy": decision["delivery_strategy"],
            "explanation_level": decision["explanation_level"],
            "adaptation_state": decision["adaptation_state"],
            "decision_reason_codes": list(reason_codes),
            "decision_reason": reason,
            "policy_version": policy_version,
        },
        "groups": None,
        "items": projected_items or None,
        "questions": list(questions) if questions is not None else None,
        "warnings": list(warnings),
        "agent_actions": agent_actions,
        "versions": {
            "config_bundle": versions.config_bundle,
            "policy": policy_version,
            "ranking": versions.ranking,
            "behavior_formula": versions.behavior_formula,
            "embedding": versions.embedding,
            "graph": versions.graph,
            "prompt": versions.prompt,
            "dataset": versions.dataset,
        },
    }


__all__ = [
    "G4ProjectionError",
    "G4ProjectionVersions",
    "G4ResourceProjection",
    "G4TaskIdentity",
    "build_http_execution_payload",
    "build_orchestration_request",
    "derive_task_identity",
    "extract_candidate_projections",
    "extract_candidate_rows_for_persistence",
    "split_recall_channels",
]
