"""Append-only MySQL writer for the opt-in G4 recommendation projection.

This adapter consumes a validated :class:`G4ProjectionWritePlan` and a
caller-owned async MySQL connection.  It never commits or rolls back, never
updates an existing fact, and never performs destructive SQL.  The future
HTTP service can therefore place Agent execution facts and G3-compatible
recommendation facts in one transaction, while tests can exercise the writer
without enabling the default HTTP application.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy

from backend.app.recommendation.application.g4_persistence import (
    G4ProjectionWritePlan,
    build_g4_projection_write_plan,
)
from backend.app.recommendation.application.g4_projection import (
    G4TaskIdentity,
    G4ProjectionVersions,
    G4ResourceProjection,
    build_http_execution_payload,
    build_orchestration_request,
)
from backend.app.recommendation.application.g4_clarification import (
    build_g4_clarification_continuation,
)
from backend.app.recommendation.application.orchestration import persist_orchestration
from backend.app.recommendation.application.persistent_orchestration import (
    build_trace_artifact,
)
from backend.app.recommendation.agents.orchestrator import OrchestrationResult
from backend.app.recommendation.agents.orchestrator import RecommendationOrchestrator
from backend.app.recommendation.agents.orchestrator import AgentProgressSink
from backend.app.recommendation.adapters.agent_logging_mysql import (
    MySQLAgentExecutionLogWriter,
)
from backend.app.recommendation.adapters.mysql import (
    CatalogRepositoryFactory,
    ConnectionFactory,
    MySQLRecommendationTaskService,
    _canonical as _g3_canonical,
    _json_array as _g3_json_array,
    _json_object as _g3_json_object,
)
from backend.app.recommendation.domain.public import (
    RecommendationTaskCommand,
    RecommendationTaskResult,
)
from backend.app.recommendation.ports.public import (
    IdempotencyConflictError,
    StaleContextVersionError,
    TaskStateConflictError,
)
from backend.app.recommendation.ports.agent_logging import AgentExecutionLogPort
from backend.app.shared_kernel.contracts.enums import TaskStatus


def _canonical(value: object) -> str:
    """Serialize projection JSON with the same UTC representation as HTTP.

    The pure G4 HTTP projection intentionally keeps ``evaluation_at`` as a
    ``datetime`` for the transport layer.  Before persistence, however, the
    waiting-context response must be valid JSON.  Normalizing datetimes here
    keeps that boundary explicit and prevents a late transaction failure after
    earlier append statements have already run.
    """

    def _json_default(item: object) -> object:
        if isinstance(item, datetime):
            if item.tzinfo is not None and item.utcoffset() is not None:
                item = item.astimezone(UTC)
            return item.isoformat().replace("+00:00", "Z")
        raise TypeError(f"object of type {type(item).__name__} is not JSON serializable")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        normalized = value
    else:
        normalized = value.astimezone(UTC).replace(tzinfo=None)
    return normalized.replace(microsecond=(normalized.microsecond // 1000) * 1000)


def _decimal(value: float | int) -> str:
    return f"{float(value):.6f}"


def _same_json(actual: object, expected: object) -> bool:
    try:
        if isinstance(actual, (bytes, bytearray)):
            actual = actual.decode("utf-8")
        if isinstance(actual, str):
            actual = json.loads(actual)
        return _canonical(actual) == _canonical(expected)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _required_version(plan: G4ProjectionWritePlan, name: str) -> str:
    value = plan.versions.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"projection version {name} is required")
    return value


def _revision_trace_id(task_id: object, context_version: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"trace-revision:{task_id}:{context_version}"))


@dataclass(frozen=True, slots=True)
class G4PersistedIdentities:
    """Database identities created or replayed by one projection batch."""

    record_id: int | None
    item_ids: Mapping[int, int]


class MySQLG4ProjectionWriter:
    """Write one validated G4 plan using only append/replay SQL."""

    def __init__(self, *, log_port: AgentExecutionLogPort) -> None:
        self._log_port = log_port

    async def append(
        self,
        connection: Any,
        plan: G4ProjectionWritePlan,
        *,
        result: OrchestrationResult,
    ) -> G4PersistedIdentities:
        """Append all G4/G3 facts without owning transaction finalization."""

        await self._append_task(connection, plan)
        await self._append_transitions(connection, plan)
        await persist_orchestration(connection, result, log_port=self._log_port)
        artifact, metadata = build_trace_artifact(result)
        await self._log_port.append_artifact(
            connection,
            task_id=plan.task_id,
            trace_id=plan.trace_id,
            context_version=plan.context_version,
            artifact=artifact,
            metadata=metadata,
            created_at=plan.started_at,
        )
        if plan.status == "WAITING_CLARIFICATION":
            await self._append_waiting(connection, plan)
            return G4PersistedIdentities(record_id=None, item_ids={})
        return await self._append_completed(connection, plan)

    async def _append_task(self, connection: Any, plan: G4ProjectionWritePlan) -> None:
        finished_at = _naive_utc(plan.finished_at) if plan.finished_at else None
        async with connection.cursor() as cursor:
            if plan.context_version == 1:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_task "
                    "(id, request_id, trace_id, user_id, session_id, trigger_scene, input_text, request_json, "
                    "intent_type, intent_confidence, status, context_version, profile_version, "
                    "config_bundle_version, policy_version, ranking_version, behavior_formula_version, "
                    "dataset_version, replan_count, evaluation_at, started_at, finished_at, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(plan.task_id),
                        str(plan.request_id),
                        str(plan.trace_id),
                        plan.user_id,
                        str(plan.session_id),
                        plan.scene,
                        plan.input_text,
                        _canonical(plan.request_json),
                        plan.intent_type,
                        _decimal(plan.intent_confidence),
                        plan.status,
                        plan.context_version,
                        _required_version(plan, "config_bundle"),
                        _required_version(plan, "policy"),
                        _required_version(plan, "ranking"),
                        _required_version(plan, "behavior_formula"),
                        _required_version(plan, "dataset"),
                        plan.replan_count,
                        _naive_utc(plan.evaluation_at),
                        _naive_utc(plan.started_at),
                        finished_at,
                        _naive_utc(plan.started_at),
                    ),
                )
            await cursor.execute(
                "SELECT request_json, trace_id, status, context_version "
                "FROM recommendation_task WHERE id = %s",
                (str(plan.task_id),),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ValueError("G4 task projection was not persisted")
        if str(row[1]) != str(plan.trace_id):
            raise ValueError("G4 task trace identity conflict")
        if plan.context_version == 1:
            if not _same_json(row[0], dict(plan.request_json)):
                raise ValueError("G4 task request identity conflict")
            if str(row[2]) != plan.status or int(row[3]) != plan.context_version:
                raise ValueError("G4 task status or context conflict")
        else:
            # The root task row is an immutable request fact.  Its status and
            # context_version therefore remain at the creation snapshot; the
            # latest waiting context is the concurrency boundary for every
            # continuation, including a second or later clarification round.
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT status, context_version FROM recommendation_task_context "
                    "WHERE task_id = %s ORDER BY context_version DESC LIMIT 1",
                    (str(plan.task_id),),
                )
                latest_context = await cursor.fetchone()
            if (
                latest_context is None
                or str(latest_context[0]) != "WAITING_CLARIFICATION"
                or int(latest_context[1]) != plan.context_version - 1
            ):
                raise ValueError("G4 continuation requires the latest waiting context")

    async def _append_transitions(self, connection: Any, plan: G4ProjectionWritePlan) -> None:
        async with connection.cursor() as cursor:
            for transition in plan.transitions:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_task_transition "
                    "(task_id, context_version, from_status, to_status, reason_code, occurred_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        str(plan.task_id),
                        plan.context_version,
                        transition.from_status,
                        transition.to_status,
                        transition.reason_code,
                        _naive_utc(transition.occurred_at),
                    ),
                )
                await cursor.execute(
                    "SELECT from_status, to_status, reason_code "
                    "FROM recommendation_task_transition WHERE task_id = %s "
                    "AND context_version = %s AND to_status = %s",
                    (str(plan.task_id), plan.context_version, transition.to_status),
                )
                row = await cursor.fetchone()
                if row is None or tuple(str(value) for value in row) != (
                    transition.from_status,
                    transition.to_status,
                    transition.reason_code,
                ):
                    raise ValueError("G4 task transition identity conflict")

    async def _append_waiting(
        self,
        connection: Any,
        plan: G4ProjectionWritePlan,
    ) -> None:
        decision = plan.decision
        async with connection.cursor() as cursor:
            if plan.context_version == 1:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_trace "
                    "(trace_id, task_id, schema_version, steps_json, complete, created_at) "
                    "VALUES (%s, %s, 'g4-trace-v1', %s, TRUE, %s)",
                    (
                        str(plan.trace_id),
                        str(plan.task_id),
                        _canonical(list(plan.trace_steps)),
                        _naive_utc(plan.started_at),
                    ),
                )
            else:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_trace_revision "
                    "(trace_id, task_id, context_version, schema_version, steps_json, complete, created_at) "
                    "VALUES (%s, %s, %s, 'g4-trace-v1', %s, TRUE, %s)",
                    (
                        _revision_trace_id(plan.task_id, plan.context_version),
                        str(plan.task_id),
                        plan.context_version,
                        _canonical(list(plan.trace_steps)),
                        _naive_utc(plan.started_at),
                    ),
                )
            await self._append_policy_cursor(
                cursor,
                plan,
                decision_no=plan.context_version,
                plan_version=None,
            )
            if plan.context_version == 1:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_task_context "
                    "(task_id, context_version, status, request_json, questions_json, answers_json, "
                    "response_json, idempotency_key, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s)",
                    (
                        str(plan.task_id),
                        plan.context_version,
                        plan.status,
                        _canonical(plan.request_json),
                        _canonical(list(plan.questions)),
                        _canonical({}),
                        _canonical(dict(plan.context_response or {})),
                        _naive_utc(plan.started_at),
                    ),
                )
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_clarification "
                    "(task_id, context_version, questions_json, answers_json, asked_at, answered_at) "
                    "VALUES (%s, %s, %s, %s, %s, NULL)",
                    (
                        str(plan.task_id),
                        plan.context_version,
                        _canonical(list(plan.questions)),
                        _canonical({}),
                        _naive_utc(plan.started_at),
                    ),
                )

    async def _append_completed(
        self,
        connection: Any,
        plan: G4ProjectionWritePlan,
    ) -> G4PersistedIdentities:
        decision = plan.decision
        record_id: int | None = None
        item_ids: dict[int, int] = {}
        async with connection.cursor() as cursor:
            for candidate in plan.candidates:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_candidate "
                    "(task_id, plan_version, resource_id, channel, channel_rank, raw_score, "
                    "normalized_score, rrf_contribution, evidence_json, created_at) "
                    "VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(plan.task_id),
                        candidate.resource_id,
                        candidate.channel,
                        candidate.channel_rank,
                        _decimal(candidate.raw_score),
                        _decimal(candidate.normalized_score),
                        _decimal(candidate.rrf_contribution),
                        _canonical(dict(candidate.evidence)),
                        _naive_utc(plan.started_at),
                    ),
                )
                await cursor.execute(
                    "SELECT channel_rank, raw_score, normalized_score, rrf_contribution, evidence_json "
                    "FROM recommendation_candidate WHERE task_id = %s AND plan_version = 1 "
                    "AND resource_id = %s AND channel = %s",
                    (str(plan.task_id), candidate.resource_id, candidate.channel),
                )
                row = await cursor.fetchone()
                if (
                    row is None
                    or int(row[0]) != candidate.channel_rank
                    or abs(float(row[1]) - candidate.raw_score) > 0.000001
                    or abs(float(row[2]) - candidate.normalized_score) > 0.000001
                    or abs(float(row[3]) - candidate.rrf_contribution) > 0.000001
                    or not _same_json(row[4], dict(candidate.evidence))
                ):
                    raise ValueError("G4 candidate identity or score conflict")
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_record "
                "(task_id, user_id, context_version, output_type, delivery_strategy, ranking_version, "
                "decision_json, warnings_json, versions_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(plan.task_id),
                    plan.user_id,
                    plan.context_version,
                    decision["output_type"],
                    decision["delivery_strategy"],
                    _required_version(plan, "ranking"),
                    _canonical(dict(decision)),
                    _canonical(list(plan.warnings)),
                    _canonical(dict(plan.versions)),
                    _naive_utc(plan.started_at),
                ),
            )
            await cursor.execute(
                "SELECT id, decision_json, warnings_json, versions_json "
                "FROM recommendation_record WHERE task_id = %s",
                (str(plan.task_id),),
            )
            record = await cursor.fetchone()
            if record is None:
                raise ValueError("G4 recommendation record was not persisted")
            record_id = int(record[0])
            if not _same_json(record[1], dict(decision)):
                raise ValueError("G4 recommendation decision conflict")
            if not _same_json(record[2], list(plan.warnings)) or not _same_json(
                record[3], dict(plan.versions)
            ):
                raise ValueError("G4 recommendation metadata conflict")
            for item in plan.items:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_item "
                    "(record_id, resource_id, rank_no, relevance_score, final_score, mmr_score, "
                    "evidence_confidence, primary_channel, score_detail_json, reason_evidence_json, "
                    "diversity_relaxed, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)",
                    (
                        record_id,
                        item.resource_id,
                        item.rank_no,
                        _decimal(item.final_score),
                        _decimal(item.final_score),
                        _decimal(item.final_score),
                        _decimal(item.evidence_confidence),
                        item.primary_channel,
                        _canonical(dict(item.score_detail)),
                        _canonical(list(item.evidence_refs)),
                        _naive_utc(plan.started_at),
                    ),
                )
                await cursor.execute(
                    "SELECT id FROM recommendation_item WHERE record_id = %s AND resource_id = %s",
                    (record_id, item.resource_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError("G4 recommendation item was not persisted")
                item_id = int(row[0])
                item_ids[item.resource_id] = item_id
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_item_explanation "
                    "(recommendation_item_id, explanation_version, explanation_text, "
                    "effective_explanation_level, provider, validator_status, evidence_refs_json, created_at) "
                    "VALUES (%s, 1, %s, %s, 'TEMPLATE', 'PASSED', %s, %s)",
                    (
                        item_id,
                        item.reason_summary,
                        decision["explanation_level"],
                        _canonical(list(item.evidence_refs)),
                        _naive_utc(plan.started_at),
                    ),
                )
            await self._append_policy_cursor(
                cursor,
                plan,
                decision_no=plan.context_version,
                plan_version=1,
            )
            if plan.context_version == 1:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_trace "
                    "(trace_id, task_id, schema_version, steps_json, complete, created_at) "
                    "VALUES (%s, %s, 'g4-trace-v1', %s, TRUE, %s)",
                    (
                        str(plan.trace_id),
                        str(plan.task_id),
                        _canonical(list(plan.trace_steps)),
                        _naive_utc(plan.started_at),
                    ),
                )
            else:
                await cursor.execute(
                    "INSERT IGNORE INTO recommendation_trace_revision "
                    "(trace_id, task_id, context_version, schema_version, steps_json, complete, created_at) "
                    "VALUES (%s, %s, %s, 'g4-trace-v1', %s, TRUE, %s)",
                    (
                        _revision_trace_id(plan.task_id, plan.context_version),
                        str(plan.task_id),
                        plan.context_version,
                        _canonical(list(plan.trace_steps)),
                        _naive_utc(plan.started_at),
                    ),
                )
        return G4PersistedIdentities(record_id=record_id, item_ids=item_ids)

    async def append_continuation_context(
        self,
        connection: Any,
        plan: G4ProjectionWritePlan,
        *,
        answers: Mapping[str, str],
        idempotency_key: str,
        response: Mapping[str, object],
    ) -> None:
        """Append the answered context after the Agent/result facts.

        Context and clarification rows are immutable facts.  The task summary
        row is intentionally not updated; read APIs resolve the latest context
        version, so this method preserves the append-only state boundary.
        """

        if plan.context_version <= 1 or not idempotency_key.strip():
            raise ValueError("continuation context version and idempotency key are required")
        request_json = _canonical(dict(plan.request_json))
        questions_json = _canonical(list(plan.questions))
        answers_json = _canonical(dict(answers))
        response_json = _canonical(dict(response))
        created_at = _naive_utc(plan.started_at)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_task_context "
                "(task_id, context_version, status, request_json, questions_json, answers_json, "
                "response_json, idempotency_key, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(plan.task_id),
                    plan.context_version,
                    plan.status,
                    request_json,
                    questions_json,
                    answers_json,
                    response_json,
                    idempotency_key,
                    created_at,
                ),
            )
            await cursor.execute(
                "SELECT status, request_json, questions_json, answers_json, response_json, idempotency_key "
                "FROM recommendation_task_context WHERE task_id = %s AND context_version = %s",
                (str(plan.task_id), plan.context_version),
            )
            context = await cursor.fetchone()
            if (
                context is None
                or str(context[0]) != plan.status
                or not _same_json(context[1], dict(plan.request_json))
                or not _same_json(context[2], list(plan.questions))
                or not _same_json(context[3], dict(answers))
                or not _same_json(context[4], dict(response))
                or str(context[5]) != idempotency_key
            ):
                raise ValueError("G4 continuation context identity conflict")
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_clarification "
                "(task_id, context_version, questions_json, answers_json, asked_at, answered_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    str(plan.task_id),
                    plan.context_version,
                    questions_json,
                    answers_json,
                    created_at,
                    created_at,
                ),
            )
            await cursor.execute(
                "SELECT questions_json, answers_json, asked_at, answered_at "
                "FROM recommendation_clarification WHERE task_id = %s AND context_version = %s",
                (str(plan.task_id), plan.context_version),
            )
            clarification = await cursor.fetchone()
        if (
            clarification is None
            or not _same_json(clarification[0], list(plan.questions))
            or not _same_json(clarification[1], dict(answers))
        ):
            raise ValueError("G4 continuation clarification identity conflict")

    @staticmethod
    async def _append_policy_cursor(
        cursor: Any,
        plan: G4ProjectionWritePlan,
        *,
        decision_no: int,
        plan_version: int | None,
    ) -> None:
        decision = plan.decision
        await cursor.execute(
            "INSERT IGNORE INTO recommendation_policy_decision "
            "(task_id, decision_no, context_version, plan_version, output_type, "
            "delivery_strategy, explanation_level, adaptation_state, decision_reason_codes_json, "
            "decision_reason, policy_version, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(plan.task_id),
                decision_no,
                plan.context_version,
                plan_version,
                decision["output_type"],
                decision["delivery_strategy"],
                decision["explanation_level"],
                decision["adaptation_state"],
                _canonical(decision["decision_reason_codes"]),
                decision["decision_reason"],
                _required_version(plan, "policy"),
                _naive_utc(plan.started_at),
            ),
        )


OrchestratorFactory = Callable[[Any], RecommendationOrchestrator]


def _request_identity_payload(command: RecommendationTaskCommand) -> dict[str, object]:
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


def _resource_projection(resource: Any) -> G4ResourceProjection:
    return G4ResourceProjection(
        resource_id=int(resource.id),
        resource_type=str(resource.resource_type),
        title=str(resource.title),
        authors=tuple(str(author) for author in resource.authors),
        publication_year=(
            int(resource.publication_year)
            if resource.publication_year is not None
            else None
        ),
        availability_status=str(resource.availability_status),
        difficulty_level=(
            int(getattr(resource, "difficulty_level"))
            if getattr(resource, "difficulty_level", None) is not None
            else None
        ),
    )


def _result_resource_ids(result: OrchestrationResult) -> tuple[int, ...]:
    """Extract the bounded set of ranked IDs needed by the write projection."""

    raw_items = result.payload.get("items")
    if not isinstance(raw_items, (list, tuple)):
        return ()
    resource_ids: list[int] = []
    seen: set[int] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        raw_id = raw_item.get("resource_id")
        if isinstance(raw_id, bool):
            continue
        try:
            resource_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if resource_id < 1 or resource_id in seen:
            continue
        seen.add(resource_id)
        resource_ids.append(resource_id)
    if len(resource_ids) > 100:
        raise ValueError("result projection contains too many resource IDs")
    return tuple(resource_ids)


async def _read_projection_resources(
    catalog: Any,
    result: OrchestrationResult,
    *,
    evaluation_at: datetime,
) -> dict[int, G4ResourceProjection]:
    """Materialize only ranked resources, with a compatibility fallback."""

    resource_ids = _result_resource_ids(result)
    if not resource_ids:
        return {}
    reader = getattr(catalog, "list_resources_by_ids", None)
    if callable(reader):
        resource_values = await reader(
            resource_ids=resource_ids,
            available_at=evaluation_at,
        )
    else:
        # Older injected test adapters may not expose the optimized port.  The
        # fallback keeps them compatible while the production MySQL adapter
        # always takes the bounded-ID path above.
        resource_values = await catalog.list_resources(available_at=evaluation_at)
    return {
        int(resource.id): _resource_projection(resource)
        for resource in resource_values
        if int(resource.id) in resource_ids
    }


class MySQLG4RecommendationTaskService(MySQLRecommendationTaskService):
    """Opt-in RecommendationTaskService backed by the real G4 orchestrator.

    The service shares the G3 read APIs for replay/status/debug, but its create
    path runs the G4 orchestrator and then appends the task, Agent facts,
    candidate rows, record, items, explanations, policy, and trace through one
    caller-owned transaction.  It is intentionally not wired into the default
    FastAPI app; composition roots must opt in explicitly.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        catalog_repository_factory: CatalogRepositoryFactory,
        orchestrator_factory: OrchestratorFactory,
        config_bundle_version: str = "rec-1.0.0",
        dataset_version: str = "synthetic-demo-2026-08",
        graph_version: str | None = None,
        embedding_version: str | None = None,
        index_version: str | None = None,
        prompt_version: str | None = None,
        deadline_seconds: float = 30.0,
        connect_timeout: float = 3.0,
        connection_factory: ConnectionFactory | None = None,
        log_port: AgentExecutionLogPort | None = None,
    ) -> None:
        super().__init__(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=connect_timeout,
            config_bundle_version=config_bundle_version,
            dataset_version=dataset_version,
            catalog_repository_factory=catalog_repository_factory,
            connection_factory=connection_factory,
        )
        if deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        self._orchestrator_factory = orchestrator_factory
        self._g4_versions = G4ProjectionVersions(
            config_bundle=config_bundle_version,
            dataset=dataset_version,
            embedding=embedding_version,
            graph=graph_version,
            prompt=prompt_version,
        )
        self._deadline_seconds = deadline_seconds
        self._g4_writer = MySQLG4ProjectionWriter(
            log_port=log_port or MySQLAgentExecutionLogWriter()
        )

    async def create_task(
        self,
        command: RecommendationTaskCommand,
        *,
        idempotency_key: str,
        progress_sink: AgentProgressSink | None = None,
    ) -> RecommendationTaskResult:
        if idempotency_key != str(command.request_id):
            raise ValueError("idempotency key must equal request id")
        if command.user_id <= 0:
            raise ValueError("user id must be positive")
        evaluation_at = command.evaluation_at or datetime.now(UTC)
        deadline_at = datetime.now(UTC) + timedelta(seconds=self._deadline_seconds)
        connection = await self._connect()
        request_json = _request_identity_payload(command)
        try:
            existing = await self._find_task(
                connection,
                user_id=command.user_id,
                request_id=command.request_id,
            )
            if existing is not None:
                if _g3_canonical(_g3_json_object(existing["request_json"])) != _g3_canonical(
                    request_json
                ):
                    raise IdempotencyConflictError(
                        "idempotency key was reused with a different request payload"
                    )
                payload = await self._load_execution(
                    connection, task_id=existing["task_id"]
                )
                await connection.rollback()
                return RecommendationTaskResult(200, True, payload)

            orchestration_request = build_orchestration_request(
                command,
                evaluation_at=evaluation_at,
                deadline_at=deadline_at,
            )
            orchestrator = self._orchestrator_factory(connection)
            if progress_sink is None:
                result = await orchestrator.run(orchestration_request)
            else:
                result = await orchestrator.run(
                    orchestration_request, progress_sink=progress_sink
                )
            catalog = self._catalog_repository_factory(connection)
            resources = await _read_projection_resources(
                catalog,
                result,
                evaluation_at=evaluation_at,
            )
            started_at = datetime.now(UTC)
            plan = build_g4_projection_write_plan(
                command,
                result,
                resources=resources,
                versions=self._g4_versions,
                evaluation_at=evaluation_at,
                started_at=started_at,
            )
            persisted = await self._g4_writer.append(
                connection,
                plan,
                result=result,
            )
            if result.status.value == "WAITING_CLARIFICATION":
                payload = dict(plan.context_response or {})
            else:
                payload = build_http_execution_payload(
                    result,
                    resources=resources,
                    versions=self._g4_versions,
                    evaluation_at=evaluation_at,
                    record_id=persisted.record_id,
                    item_ids=persisted.item_ids,
                )
            await connection.commit()
            return RecommendationTaskResult(201, False, payload)
        except IdempotencyConflictError:
            await connection.rollback()
            raise
        except asyncmy.errors.IntegrityError:
            await connection.rollback()
            existing = await self._find_task(
                connection,
                user_id=command.user_id,
                request_id=command.request_id,
            )
            if existing is None:
                raise
            if _g3_canonical(_g3_json_object(existing["request_json"])) != _g3_canonical(
                request_json
            ):
                raise IdempotencyConflictError(
                    "idempotency key was reused with a different request payload"
                )
            payload = await self._load_execution(
                connection, task_id=existing["task_id"]
            )
            await connection.rollback()
            return RecommendationTaskResult(200, True, payload)
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def submit_clarification(
        self,
        task_id: UUID,
        *,
        context_version: int,
        answers: dict[str, str],
        idempotency_key: str,
        user_id: int,
        progress_sink: AgentProgressSink | None = None,
    ) -> RecommendationTaskResult:
        """Resume one waiting G4 context through the same append-only transaction."""

        if context_version < 1 or not idempotency_key.strip():
            raise ValueError("context version and idempotency key are required")
        connection = await self._connect()
        try:
            task = await self._find_task_by_id(
                connection,
                task_id=task_id,
                user_id=user_id,
                include_request=True,
            )
            if task is None:
                raise LookupError("recommendation task not found")
            replay = await self._find_context_by_idempotency(
                connection,
                task_id=task_id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                if _g3_canonical(_g3_json_object(replay["answers_json"])) != _g3_canonical(
                    answers
                ):
                    raise IdempotencyConflictError(
                        "clarification idempotency key was reused with different answers"
                    )
                await connection.rollback()
                return RecommendationTaskResult(
                    200,
                    True,
                    _g3_json_object(replay["response_json"]),
                )
            latest = await self._latest_context(connection, task_id=task_id)
            if latest is None:
                raise TaskStateConflictError("task has no clarification context")
            if int(latest["context_version"]) != context_version:
                raise StaleContextVersionError("clarification context version is stale")
            if str(latest["status"]) != "WAITING_CLARIFICATION":
                raise TaskStateConflictError("task is not waiting for clarification")

            request_json = _g3_json_object(latest["request_json"])
            base_command = self._command_from_clarification(
                task=task,
                request_json=request_json,
                answers={},
            )
            continuation = build_g4_clarification_continuation(
                base_command,
                questions=_g3_json_array(latest["questions_json"]),
                answers=answers,
                previous_context_version=context_version,
            )
            evaluation_at = task["evaluation_at"]
            if not isinstance(evaluation_at, datetime):
                raise RuntimeError("task evaluation_at is invalid")
            evaluation_at = evaluation_at.replace(tzinfo=UTC)
            deadline_at = datetime.now(UTC) + timedelta(seconds=self._deadline_seconds)
            orchestration_request = build_orchestration_request(
                continuation.command,
                evaluation_at=evaluation_at,
                deadline_at=deadline_at,
                context_version=continuation.context_version,
                identity=G4TaskIdentity(
                    task_id=UUID(str(task["task_id"])),
                    trace_id=UUID(str(task["trace_id"])),
                ),
                initial_status=TaskStatus.WAITING_CLARIFICATION,
            )
            orchestrator = self._orchestrator_factory(connection)
            if progress_sink is None:
                result = await orchestrator.run(orchestration_request)
            else:
                result = await orchestrator.run(
                    orchestration_request, progress_sink=progress_sink
                )
            catalog = self._catalog_repository_factory(connection)
            resources = await _read_projection_resources(
                catalog,
                result,
                evaluation_at=evaluation_at,
            )
            started_at = datetime.now(UTC)
            plan = build_g4_projection_write_plan(
                continuation.command,
                result,
                resources=resources,
                versions=self._g4_versions,
                evaluation_at=evaluation_at,
                started_at=started_at,
            )
            persisted = await self._g4_writer.append(
                connection,
                plan,
                result=result,
            )
            if result.status.value == "WAITING_CLARIFICATION":
                payload = dict(plan.context_response or {})
            else:
                payload = build_http_execution_payload(
                    result,
                    resources=resources,
                    versions=self._g4_versions,
                    evaluation_at=evaluation_at,
                    record_id=persisted.record_id,
                    item_ids=persisted.item_ids,
                )
            stored_payload = dict(payload)
            stored_evaluation = stored_payload.get("evaluation_at")
            if isinstance(stored_evaluation, datetime):
                stored_payload["evaluation_at"] = stored_evaluation.isoformat()
            await self._g4_writer.append_continuation_context(
                connection,
                plan,
                answers=continuation.answers,
                idempotency_key=idempotency_key,
                response=stored_payload,
            )
            await connection.commit()
            return RecommendationTaskResult(200, False, payload)
        except (
            IdempotencyConflictError,
            StaleContextVersionError,
            TaskStateConflictError,
        ):
            await connection.rollback()
            raise
        except asyncmy.errors.IntegrityError:
            await connection.rollback()
            replay = await self._find_context_by_idempotency(
                connection,
                task_id=task_id,
                idempotency_key=idempotency_key,
            )
            if replay is None:
                raise
            if _g3_canonical(_g3_json_object(replay["answers_json"])) != _g3_canonical(
                answers
            ):
                raise IdempotencyConflictError(
                    "clarification idempotency key was reused with different answers"
                )
            return RecommendationTaskResult(
                200,
                True,
                _g3_json_object(replay["response_json"]),
            )
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()


__all__ = [
    "G4PersistedIdentities",
    "MySQLG4ProjectionWriter",
    "MySQLG4RecommendationTaskService",
]
