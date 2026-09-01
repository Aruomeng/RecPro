"""Insert-only MySQL adapter for the G3 recommendation application port."""

from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime
import inspect
from typing import Any, Awaitable, Callable
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy

from backend.app.catalog.ports.public import CatalogRepository
from backend.app.recommendation.application.public import execute_recommendation
from backend.app.recommendation.domain.public import (
    ProfileSignal,
    RecommendationRequest,
    RecommendationTaskCommand,
    RecommendationTaskResult,
)
from backend.app.recommendation.ports.public import (
    IdempotencyConflictError,
    RecommendationTaskService,
    StaleContextVersionError,
    TaskStateConflictError,
)
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


ConnectionFactory = Callable[[], Awaitable[Any]]
CatalogRepositoryFactory = Callable[[Any], CatalogRepository]


def _json_value(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _json_object(value: object) -> dict[str, Any]:
    parsed = _json_value(value, {})
    return dict(parsed) if isinstance(parsed, dict) else {}


def _json_array(value: object) -> list[Any]:
    parsed = _json_value(value, [])
    return list(parsed) if isinstance(parsed, list) else []


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decimal(value: float | int) -> str:
    # A string is accepted by asyncmy and avoids binary float representation in
    # DECIMAL columns while keeping score values bounded by the core service.
    return f"{value:.6f}"


def _task_id(request_id: UUID, user_id: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"task:{user_id}:{request_id}")


def _trace_id(request_id: UUID, user_id: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"trace:{user_id}:{request_id}")


def _revision_trace_id(task_id: UUID, context_version: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"trace-revision:{task_id}:{context_version}")


CLARIFICATION_QUESTIONS: tuple[dict[str, object], ...] = (
    {
        "slot": "resource_types",
        "question": "你更需要图书、论文，还是两者都需要？",
        "options": ["BOOK", "PAPER", "BOOK_AND_PAPER"],
        "required": True,
    },
    {
        "slot": "topic",
        "question": "你主要关注哪个主题？",
        "options": ["多智能体", "推荐系统", "知识图谱"],
        "required": True,
    },
)


def _needs_clarification(command: RecommendationTaskCommand) -> bool:
    return (
        command.scene == "HOME"
        and not (command.input_text or "").strip()
        and not command.resource_types
        and command.output_type is None
    )


def _sanitized_digest(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _command_payload(command: RecommendationTaskCommand, evaluation_at: datetime) -> dict[str, object]:
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
        # ``None`` means the service freezes the current evaluation time on the
        # first write; it must not make a replay look like a different payload.
        "evaluation_at": command.evaluation_at.isoformat() if command.evaluation_at else None,
        "constraints": dict(command.constraints),
        "limit": command.limit,
    }


def _versions(*, config_bundle: str, dataset: str) -> dict[str, str]:
    return {
        "config_bundle": config_bundle,
        "policy": "policy-g3-v1",
        "ranking": "ranking-g3-v1",
        "behavior_formula": "profile-g2-v1",
        "embedding": "disabled-g3-mysql-only-v1",
        "graph": "disabled-g3-mysql-only-v1",
        "prompt": "template-g3-v1",
        "dataset": dataset,
    }


class MySQLRecommendationTaskService(RecommendationTaskService):
    """One-request connection adapter with insert-only result persistence."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        connect_timeout: float = 3.0,
        config_bundle_version: str = "rec-1.0.0",
        dataset_version: str = "synthetic-demo-2026-08",
        catalog_repository_factory: CatalogRepositoryFactory,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._connection_options = {
            "host": host,
            "port": port,
            "db": database,
            "user": user,
            "password": password,
            "connect_timeout": connect_timeout,
            "read_timeout": max(connect_timeout, 3.0),
            "charset": "utf8mb4",
            "autocommit": False,
        }
        self._connection_factory = connection_factory
        self._catalog_repository_factory = catalog_repository_factory
        self._config_bundle_version = config_bundle_version
        self._dataset_version = dataset_version

    async def _connect(self) -> Any:
        if self._connection_factory is not None:
            return await self._connection_factory()
        return await asyncmy.connect(**self._connection_options)

    async def close(self) -> None:
        """Close an explicitly injected pool, if this adapter owns one.

        Per-request direct ``asyncmy.connect`` connections are still closed by
        their request transaction.  A pooled factory exposes ``close`` and is
        closed by the application lifespan through this adapter.
        """

        if self._connection_factory is None:
            return
        close = getattr(self._connection_factory, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def runtime_metrics(self) -> dict[str, object] | None:
        """Expose pool metrics without exposing connection options."""

        snapshot = getattr(self._connection_factory, "snapshot", None)
        if not callable(snapshot):
            return None
        value = snapshot()
        as_dict = getattr(value, "as_dict", None)
        if callable(as_dict):
            value = as_dict()
        return dict(value) if isinstance(value, dict) else None

    async def create_task(
        self,
        command: RecommendationTaskCommand,
        *,
        idempotency_key: str,
    ) -> RecommendationTaskResult:
        if idempotency_key != str(command.request_id):
            raise ValueError("idempotency key must equal request id")
        if command.user_id <= 0:
            raise ValueError("user id must be positive")
        evaluation_at = command.evaluation_at or datetime.now(UTC).replace(tzinfo=None)
        connection = await self._connect()
        request_json = _command_payload(command, evaluation_at)
        try:
            existing = await self._find_task(
                connection,
                user_id=command.user_id,
                request_id=command.request_id,
            )
            if existing is not None:
                if _canonical(_json_object(existing["request_json"])) != _canonical(request_json):
                    raise IdempotencyConflictError(
                        "idempotency key was reused with a different request payload"
                    )
                payload = await self._load_execution(
                    connection, task_id=UUID(str(existing["task_id"]))
                )
                await connection.rollback()
                return RecommendationTaskResult(200, True, payload)

            if _needs_clarification(command):
                task_id = _task_id(command.request_id, command.user_id)
                trace_id = _trace_id(command.request_id, command.user_id)
                now = datetime.now(UTC).replace(tzinfo=None)
                versions = _versions(
                    config_bundle=self._config_bundle_version,
                    dataset=self._dataset_version,
                )
                await self._insert_task(
                    connection,
                    task_id=task_id,
                    trace_id=trace_id,
                    command=command,
                    evaluation_at=evaluation_at,
                    request_json=request_json,
                    execution=None,
                    intent_type="UNCLEAR",
                    intent_confidence=0.2,
                    versions=versions,
                    status="WAITING_CLARIFICATION",
                    now=now,
                    profile_version=None,
                )
                await self._insert_transitions(
                    connection,
                    task_id=task_id,
                    status="WAITING_CLARIFICATION",
                    occurred_at=now,
                    context_version=1,
                )
                payload = self._clarification_payload(
                    task_id=task_id,
                    trace_id=trace_id,
                    evaluation_at=evaluation_at,
                    versions=versions,
                )
                await self._insert_waiting_facts(
                    connection,
                    task_id=task_id,
                    trace_id=trace_id,
                    request_json=request_json,
                    payload=payload,
                    versions=versions,
                    now=now,
                )
                await connection.commit()
                return RecommendationTaskResult(201, False, payload)

            resources, tags, profile_signals, behavior_events, profile_version = await self._read_inputs(
                connection,
                user_id=command.user_id,
                evaluation_at=evaluation_at,
            )
            request = RecommendationRequest(
                user_id=command.user_id,
                input_text=command.input_text,
                resource_types=command.resource_types or ("BOOK", "PAPER"),
                limit=command.limit,
                evaluation_at=evaluation_at,
                output_type=command.output_type or "TOPIC_RESOURCES",
            )
            execution = execute_recommendation(
                request,
                resources=resources,
                tags=tags,
                profile_signals=profile_signals,
                behavior_events=behavior_events,
            )
            task_id = _task_id(command.request_id, command.user_id)
            trace_id = _trace_id(command.request_id, command.user_id)
            now = datetime.now(UTC).replace(tzinfo=None)
            versions = _versions(
                config_bundle=self._config_bundle_version,
                dataset=self._dataset_version,
            )
            status = "DEGRADED_COMPLETED" if execution.warnings else "COMPLETED"
            await self._insert_task(
                connection,
                task_id=task_id,
                trace_id=trace_id,
                command=command,
                evaluation_at=evaluation_at,
                request_json=request_json,
                execution=execution,
                versions=versions,
                status=status,
                now=now,
                profile_version=profile_version,
            )
            await self._insert_transitions(
                connection,
                task_id=task_id,
                status=status,
                occurred_at=now,
                context_version=1,
            )
            record_id = await self._insert_results(
                connection,
                task_id=task_id,
                trace_id=trace_id,
                user_id=command.user_id,
                execution=execution,
                output_type=command.output_type or "TOPIC_RESOURCES",
                versions=versions,
                now=now,
            )
            await connection.commit()
            payload = await self._load_execution(connection, task_id=task_id)
            if payload.get("record_id") != record_id:
                raise RuntimeError("persisted recommendation record identity mismatch")
            return RecommendationTaskResult(201, False, payload)
        except IdempotencyConflictError:
            await connection.rollback()
            raise
        except asyncmy.IntegrityError:
            # A concurrent request may win the unique request identity.  It is
            # safe to replay only after the transaction is rolled back and the
            # committed winner is read back.
            await connection.rollback()
            existing = await self._find_task(
                connection,
                user_id=command.user_id,
                request_id=command.request_id,
            )
            if existing is None:
                raise
            if _canonical(_json_object(existing["request_json"])) != _canonical(request_json):
                raise IdempotencyConflictError(
                    "idempotency key was reused with a different request payload"
                )
            payload = await self._load_execution(
                connection, task_id=UUID(str(existing["task_id"]))
            )
            await connection.rollback()
            return RecommendationTaskResult(200, True, payload)
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def get_task(self, task_id: UUID, *, user_id: int) -> dict[str, Any]:
        connection = await self._connect()
        try:
            task = await self._find_task_by_id(connection, task_id=task_id, user_id=user_id)
            if task is None:
                raise LookupError("recommendation task not found")
            latest = await self._latest_context(connection, task_id=task_id)
            record_id = await self._record_id(connection, task_id=task_id)
            warnings: list[str] = []
            versions = {
                "config_bundle": str(task["config_bundle_version"]),
                "policy": str(task["policy_version"]),
                "ranking": str(task["ranking_version"]),
                "behavior_formula": str(task["behavior_formula_version"]),
                "dataset": str(task["dataset_version"]),
            }
            if record_id is not None:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "SELECT warnings_json FROM recommendation_record WHERE id = %s",
                        (record_id,),
                    )
                    row = await cursor.fetchone()
                if row is not None:
                    warnings = [str(value) for value in _json_array(row[0])]
            response = _json_object(latest["response_json"]) if latest is not None else {}
            effective_status = str(latest["status"]) if latest is not None else str(task["status"])
            effective_context = (
                int(latest["context_version"]) if latest is not None else int(task["context_version"])
            )
            if response.get("record_id") is not None:
                record_id = int(response["record_id"])
            await connection.rollback()
            return {
                "task_id": str(task_id),
                "trace_id": str(task["trace_id"]),
                "status": effective_status,
                "context_version": effective_context,
                "record_id": record_id,
                "evaluation_at": _iso(task["evaluation_at"]),
                "started_at": _iso(task["started_at"]),
                "finished_at": _iso(task["finished_at"]) if task["finished_at"] else None,
                "error_code": task["error_code"],
                "warnings": warnings,
                "versions": versions,
            }
        finally:
            connection.close()

    async def get_trace(self, task_id: UUID, *, user_id: int) -> dict[str, Any]:
        connection = await self._connect()
        try:
            task = await self._find_task_by_id(connection, task_id=task_id, user_id=user_id)
            if task is None:
                raise LookupError("recommendation task not found")
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT schema_version, steps_json, complete FROM recommendation_trace_revision "
                    "WHERE task_id = %s ORDER BY context_version DESC LIMIT 1",
                    (str(task_id),),
                )
                trace = await cursor.fetchone()
                if trace is None:
                    await cursor.execute(
                        "SELECT schema_version, steps_json, complete FROM recommendation_trace "
                        "WHERE task_id = %s",
                        (str(task_id),),
                    )
                    trace = await cursor.fetchone()
            if trace is None:
                raise LookupError("recommendation trace not found")
            await connection.rollback()
            return {
                "task_id": str(task_id),
                "schema_version": str(trace[0]),
                "payload": {
                    "trace_id": str(task["trace_id"]),
                    "complete": bool(trace[2]),
                    "steps": _json_array(trace[1]),
                },
            }
        finally:
            connection.close()

    async def get_debug_trace(
        self,
        task_id: UUID,
        *,
        actor: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        self._require_research_admin(actor)
        connection = await self._connect()
        try:
            task = await self._find_task_any(connection, task_id=task_id)
            if task is None:
                raise LookupError("recommendation task not found")
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT schema_version, steps_json, complete FROM recommendation_trace_revision "
                    "WHERE task_id = %s ORDER BY context_version DESC LIMIT 1",
                    (str(task_id),),
                )
                trace = await cursor.fetchone()
                if trace is None:
                    await cursor.execute(
                        "SELECT schema_version, steps_json, complete FROM recommendation_trace "
                        "WHERE task_id = %s",
                        (str(task_id),),
                    )
                    trace = await cursor.fetchone()
            if trace is None:
                raise LookupError("recommendation trace not found")
            await connection.rollback()
            return {
                "task_id": str(task_id),
                "schema_version": "debug-trace-v1",
                "payload": {
                    "trace_id": str(task["trace_id"]),
                    "complete": bool(trace[2]),
                    "steps": _json_array(trace[1]),
                },
            }
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
    ) -> RecommendationTaskResult:
        """Append one clarification context and, when complete, its result.

        The original task row remains an immutable request fact.  Context,
        transition, policy, result and trace revisions are appended under a
        new context version in one transaction.
        """

        if context_version < 1 or not idempotency_key.strip():
            raise ValueError("context version and idempotency key are required")
        connection = await self._connect()
        try:
            task = await self._find_task_by_id(
                connection, task_id=task_id, user_id=user_id, include_request=True
            )
            if task is None:
                raise LookupError("recommendation task not found")
            replay = await self._find_context_by_idempotency(
                connection,
                task_id=task_id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                if _canonical(_json_object(replay["answers_json"])) != _canonical(answers):
                    raise IdempotencyConflictError(
                        "clarification idempotency key was reused with different answers"
                    )
                await connection.rollback()
                return RecommendationTaskResult(
                    200,
                    True,
                    _json_object(replay["response_json"]),
                )
            latest = await self._latest_context(connection, task_id=task_id)
            if latest is None:
                raise TaskStateConflictError("task has no clarification context")
            if int(latest["context_version"]) != context_version:
                raise StaleContextVersionError("clarification context version is stale")
            if str(latest["status"]) != "WAITING_CLARIFICATION":
                raise TaskStateConflictError("task is not waiting for clarification")
            self._validate_clarification_answers(
                questions=_json_array(latest["questions_json"]), answers=answers
            )
            command = self._command_from_clarification(
                task=task,
                request_json=_json_object(latest["request_json"]),
                answers=answers,
            )
            evaluation_at = task["evaluation_at"]
            if not isinstance(evaluation_at, datetime):
                raise RuntimeError("task evaluation_at is invalid")
            resources, tags, profile_signals, behavior_events, _profile_version = await self._read_inputs(
                connection,
                user_id=user_id,
                evaluation_at=evaluation_at,
            )
            request = RecommendationRequest(
                user_id=user_id,
                input_text=command.input_text,
                resource_types=command.resource_types or ("BOOK", "PAPER"),
                limit=command.limit,
                evaluation_at=evaluation_at,
                output_type=command.output_type or "TOPIC_RESOURCES",
            )
            execution = execute_recommendation(
                request,
                resources=resources,
                tags=tags,
                profile_signals=profile_signals,
                behavior_events=behavior_events,
            )
            versions = {
                "config_bundle": str(task["config_bundle_version"]),
                "policy": str(task["policy_version"]),
                "ranking": str(task["ranking_version"]),
                "behavior_formula": str(task["behavior_formula_version"]),
                "embedding": "disabled-g3-mysql-only-v1",
                "graph": "disabled-g3-mysql-only-v1",
                "prompt": "template-g3-v1",
                "dataset": str(task["dataset_version"]),
            }
            status = "DEGRADED_COMPLETED" if execution.warnings else "COMPLETED"
            now = datetime.now(UTC).replace(tzinfo=None)
            await self._insert_transitions(
                connection,
                task_id=task_id,
                status=status,
                occurred_at=now,
                context_version=context_version + 1,
            )
            await self._insert_results(
                connection,
                task_id=task_id,
                trace_id=UUID(str(task["trace_id"])),
                user_id=user_id,
                execution=execution,
                output_type=command.output_type or "TOPIC_RESOURCES",
                versions=versions,
                now=now,
                write_trace=False,
                context_version=context_version + 1,
            )
            await self._insert_trace_revision(
                connection,
                task_id=task_id,
                context_version=context_version + 1,
                trace_id=_revision_trace_id(task_id, context_version + 1),
                steps=list(execution.trace_steps),
                now=now,
            )
            payload = await self._load_execution(connection, task_id=task_id)
            payload["status"] = status
            payload["context_version"] = context_version + 1
            payload["evaluation_at"] = _iso(evaluation_at)
            await self._insert_context(
                connection,
                task_id=task_id,
                context_version=context_version + 1,
                status=status,
                request_json=_command_payload(command, evaluation_at),
                questions=[],
                answers=answers,
                response=payload,
                idempotency_key=idempotency_key,
                now=now,
            )
            await self._insert_clarification(
                connection,
                task_id=task_id,
                context_version=context_version + 1,
                questions=[],
                answers=answers,
                asked_at=now,
                answered_at=now,
            )
            await connection.commit()
            return RecommendationTaskResult(200, False, payload)
        except (IdempotencyConflictError, StaleContextVersionError, TaskStateConflictError):
            await connection.rollback()
            raise
        except asyncmy.IntegrityError:
            await connection.rollback()
            replay = await self._find_context_by_idempotency(
                connection,
                task_id=task_id,
                idempotency_key=idempotency_key,
            )
            if replay is None:
                raise
            if _canonical(_json_object(replay["answers_json"])) != _canonical(answers):
                raise IdempotencyConflictError(
                    "clarification idempotency key was reused with different answers"
                )
            return RecommendationTaskResult(200, True, _json_object(replay["response_json"]))
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def get_debug_context(
        self,
        task_id: UUID,
        *,
        actor: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        self._require_research_admin(actor)
        connection = await self._connect()
        try:
            task = await self._find_task_any(connection, task_id=task_id)
            if task is None:
                raise LookupError("recommendation task not found")
            contexts = await self._context_rows(connection, task_id=task_id)
            request_json = _json_object(task["request_json"])
            if "input_text" in request_json:
                request_json["input_text"] = _sanitized_digest(request_json["input_text"])
            await connection.rollback()
            return {
                "task_id": str(task_id),
                "schema_version": "debug-context-v1",
                "payload": {
                    "task": {
                        "status": str(task["status"]),
                        "context_version": int(task["context_version"]),
                        "evaluation_at": _iso(task["evaluation_at"]),
                        "request": request_json,
                    },
                    "contexts": contexts,
                },
            }
        finally:
            connection.close()

    async def get_debug_policy_decision(
        self,
        task_id: UUID,
        *,
        actor: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        self._require_research_admin(actor)
        connection = await self._connect()
        try:
            task = await self._find_task_any(connection, task_id=task_id)
            if task is None:
                raise LookupError("recommendation task not found")
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT decision_no, context_version, plan_version, output_type, "
                    "delivery_strategy, explanation_level, adaptation_state, "
                    "decision_reason_codes_json, decision_reason, policy_version, created_at "
                    "FROM recommendation_policy_decision WHERE task_id = %s "
                    "ORDER BY decision_no",
                    (str(task_id),),
                )
                rows = await cursor.fetchall()
                if not rows:
                    await cursor.execute(
                        "SELECT context_version, decision_json FROM recommendation_record "
                        "WHERE task_id = %s",
                        (str(task_id),),
                    )
                    fallback = await cursor.fetchone()
                    if fallback is not None:
                        decision = _json_object(fallback[1])
                        rows = [
                            (
                                1,
                                int(fallback[0]),
                                1,
                                decision.get("output_type", "TOPIC_RESOURCES"),
                                decision.get("delivery_strategy", "DIRECT"),
                                decision.get("explanation_level", "EVIDENCE"),
                                decision.get("adaptation_state", "NORMAL"),
                                _canonical(decision.get("decision_reason_codes", [])),
                                decision.get("decision_reason", "Persisted recommendation decision."),
                                decision.get("policy_version", str(task["policy_version"])),
                                task["started_at"],
                            )
                        ]
            await connection.rollback()
            return {
                "task_id": str(task_id),
                "schema_version": "debug-policy-v1",
                "payload": {
                    "decisions": [
                        {
                            "decision_no": int(row[0]),
                            "context_version": int(row[1]),
                            "plan_version": int(row[2]) if row[2] is not None else None,
                            "output_type": str(row[3]),
                            "delivery_strategy": str(row[4]),
                            "explanation_level": str(row[5]),
                            "adaptation_state": str(row[6]),
                            "decision_reason_codes": _json_array(row[7]),
                            "decision_reason": str(row[8]),
                            "policy_version": str(row[9]),
                            "created_at": _iso(row[10]),
                        }
                        for row in rows
                    ]
                },
            }
        finally:
            connection.close()

    async def _read_inputs(
        self,
        connection: Any,
        *,
        user_id: int,
        evaluation_at: datetime,
    ) -> tuple[Any, tuple[Any, ...], tuple[ProfileSignal, ...], tuple[tuple[int, str], ...], int | None]:
        repository = self._catalog_repository_factory(connection)
        resources = await repository.list_resources(available_at=evaluation_at)
        tags = await repository.list_resource_tags(
            resource_ids=tuple(resource.id for resource in resources)
        )
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT profile_version FROM user_profile WHERE user_id = %s",
                (user_id,),
            )
            profile_row = await cursor.fetchone()
            await cursor.execute(
                "SELECT tag_id, positive_weight FROM user_interest_tag "
                "WHERE user_id = %s ORDER BY tag_id",
                (user_id,),
            )
            positive = [ProfileSignal(int(row[0]), float(row[1]), False) for row in await cursor.fetchall()]
            await cursor.execute(
                "SELECT tag_id, negative_weight FROM user_negative_preference "
                "WHERE user_id = %s ORDER BY tag_id",
                (user_id,),
            )
            negative = [ProfileSignal(int(row[0]), float(row[1]), True) for row in await cursor.fetchall()]
            await cursor.execute(
                "SELECT resource_id, event_type FROM user_behavior_event "
                "WHERE user_id = %s AND occurred_at <= %s AND resource_id IS NOT NULL "
                "ORDER BY occurred_at, id",
                (user_id, evaluation_at),
            )
            events = tuple((int(row[0]), str(row[1])) for row in await cursor.fetchall())
        return (
            resources,
            tags,
            tuple(positive + negative),
            events,
            int(profile_row[0]) if profile_row is not None else None,
        )

    async def _find_task(self, connection: Any, *, user_id: int, request_id: UUID) -> dict[str, Any] | None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, trace_id, request_json, status, context_version, evaluation_at, "
                "started_at, finished_at, error_code, config_bundle_version, policy_version, "
                "ranking_version, behavior_formula_version, dataset_version "
                "FROM recommendation_task WHERE user_id = %s AND request_id = %s",
                (user_id, str(request_id)),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "trace_id": row[1],
            "request_json": row[2],
            "status": row[3],
            "context_version": row[4],
            "evaluation_at": row[5],
            "started_at": row[6],
            "finished_at": row[7],
            "error_code": row[8],
            "config_bundle_version": row[9],
            "policy_version": row[10],
            "ranking_version": row[11],
            "behavior_formula_version": row[12],
            "dataset_version": row[13],
        }

    async def _find_task_by_id(
        self,
        connection: Any,
        *,
        task_id: UUID,
        user_id: int,
        include_request: bool = False,
    ) -> dict[str, Any] | None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, request_id, trace_id, user_id, session_id, trigger_scene, input_text, request_json, "
                "status, context_version, evaluation_at, started_at, "
                "finished_at, error_code, config_bundle_version, policy_version, "
                "ranking_version, behavior_formula_version, dataset_version "
                "FROM recommendation_task WHERE id = %s AND user_id = %s",
                (str(task_id), user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "request_id": row[1],
            "trace_id": row[2],
            "user_id": row[3],
            "session_id": row[4],
            "trigger_scene": row[5],
            "input_text": row[6],
            "request_json": row[7],
            "status": row[8],
            "context_version": row[9],
            "evaluation_at": row[10],
            "started_at": row[11],
            "finished_at": row[12],
            "error_code": row[13],
            "config_bundle_version": row[14],
            "policy_version": row[15],
            "ranking_version": row[16],
            "behavior_formula_version": row[17],
            "dataset_version": row[18],
        }

    async def _find_task_any(
        self,
        connection: Any,
        *,
        task_id: UUID,
    ) -> dict[str, Any] | None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, request_id, trace_id, user_id, session_id, trigger_scene, input_text, request_json, "
                "status, context_version, evaluation_at, started_at, finished_at, error_code, "
                "config_bundle_version, policy_version, ranking_version, behavior_formula_version, dataset_version "
                "FROM recommendation_task WHERE id = %s",
                (str(task_id),),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "request_id": row[1],
            "trace_id": row[2],
            "user_id": row[3],
            "session_id": row[4],
            "trigger_scene": row[5],
            "input_text": row[6],
            "request_json": row[7],
            "status": row[8],
            "context_version": row[9],
            "evaluation_at": row[10],
            "started_at": row[11],
            "finished_at": row[12],
            "error_code": row[13],
            "config_bundle_version": row[14],
            "policy_version": row[15],
            "ranking_version": row[16],
            "behavior_formula_version": row[17],
            "dataset_version": row[18],
        }

    async def _latest_context(
        self,
        connection: Any,
        *,
        task_id: UUID,
    ) -> dict[str, Any] | None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT context_version, status, request_json, questions_json, answers_json, "
                "response_json, idempotency_key FROM recommendation_task_context "
                "WHERE task_id = %s ORDER BY context_version DESC LIMIT 1",
                (str(task_id),),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "context_version": row[0],
            "status": row[1],
            "request_json": row[2],
            "questions_json": row[3],
            "answers_json": row[4],
            "response_json": row[5],
            "idempotency_key": row[6],
        }

    async def _find_context_by_idempotency(
        self,
        connection: Any,
        *,
        task_id: UUID,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT context_version, status, request_json, questions_json, answers_json, "
                "response_json, idempotency_key FROM recommendation_task_context "
                "WHERE task_id = %s AND idempotency_key = %s",
                (str(task_id), idempotency_key),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "context_version": row[0],
            "status": row[1],
            "request_json": row[2],
            "questions_json": row[3],
            "answers_json": row[4],
            "response_json": row[5],
            "idempotency_key": row[6],
        }

    async def _context_rows(
        self,
        connection: Any,
        *,
        task_id: UUID,
    ) -> list[dict[str, Any]]:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT context_version, status, questions_json, answers_json, created_at "
                "FROM recommendation_task_context WHERE task_id = %s ORDER BY context_version",
                (str(task_id),),
            )
            rows = await cursor.fetchall()
        return [
            {
                "context_version": int(row[0]),
                "status": str(row[1]),
                "questions": _json_array(row[2]),
                "answers": _json_object(row[3]),
                "created_at": _iso(row[4]),
            }
            for row in rows
        ]

    @staticmethod
    def _require_research_admin(actor: AuthenticatedPrincipal) -> None:
        if not actor.has_role("research_admin"):
            raise PermissionError("research_admin role is required")

    @staticmethod
    def _validate_clarification_answers(
        *,
        questions: list[Any],
        answers: dict[str, str],
    ) -> None:
        if not answers or not all(
            isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()
            for key, value in answers.items()
        ):
            raise ValueError("clarification answers must be non-blank strings")
        question_map = {
            str(item.get("slot")): item
            for item in questions
            if isinstance(item, dict) and item.get("slot")
        }
        if any(key not in question_map for key in answers):
            raise ValueError("clarification answers contain an unknown slot")
        required = {
            key for key, item in question_map.items() if bool(item.get("required", False))
        }
        if not required.issubset(answers):
            raise ValueError("required clarification slots are missing")

    @staticmethod
    def _command_from_clarification(
        *,
        task: dict[str, Any],
        request_json: dict[str, Any],
        answers: dict[str, str],
    ) -> RecommendationTaskCommand:
        resource_types = tuple(str(value) for value in request_json.get("resource_types", ()))
        selected_types = answers.get("resource_types")
        if selected_types == "BOOK_AND_PAPER":
            resource_types = ("BOOK", "PAPER")
        elif selected_types in {"BOOK", "PAPER"}:
            resource_types = (selected_types,)
        input_text = request_json.get("input_text")
        if answers.get("topic"):
            input_text = answers["topic"]
        output_type = request_json.get("output_type") or None
        if answers.get("output_type"):
            output_type = answers["output_type"]
        return RecommendationTaskCommand(
            request_id=UUID(str(task["request_id"])),
            session_id=UUID(str(task["session_id"])),
            user_id=int(task["user_id"]),
            scene=str(task["trigger_scene"]),
            input_text=str(input_text) if input_text is not None else None,
            resource_types=resource_types,
            output_type=str(output_type) if output_type is not None else None,
            source_resource_id=request_json.get("source_resource_id"),
            source_item_id=request_json.get("source_item_id"),
            evaluation_at=task["evaluation_at"],
            constraints=dict(request_json.get("constraints", {})),
            limit=int(request_json.get("limit", 10)),
        )

    async def _record_id(self, connection: Any, *, task_id: UUID) -> int | None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id FROM recommendation_record WHERE task_id = %s",
                (str(task_id),),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row is not None else None

    async def _insert_task(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        command: RecommendationTaskCommand,
        evaluation_at: datetime,
        request_json: dict[str, object],
        execution: Any | None,
        versions: dict[str, str],
        status: str,
        now: datetime,
        intent_type: str | None = None,
        intent_confidence: float | None = None,
        profile_version: int | None = None,
    ) -> None:
        finished_at = now if status in {"COMPLETED", "DEGRADED_COMPLETED", "FAILED"} else None
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO recommendation_task "
                "(id, request_id, trace_id, user_id, session_id, trigger_scene, input_text, request_json, "
                "intent_type, intent_confidence, status, context_version, profile_version, "
                "config_bundle_version, policy_version, ranking_version, behavior_formula_version, "
                "dataset_version, replan_count, evaluation_at, started_at, finished_at, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s)",
                (
                    str(task_id),
                    str(command.request_id),
                    str(trace_id),
                    command.user_id,
                    str(command.session_id),
                    command.scene,
                    command.input_text,
                    _canonical(request_json),
                    intent_type or execution.intent.intent_type,
                    _decimal(
                        intent_confidence
                        if intent_confidence is not None
                        else execution.intent.confidence
                    ),
                    status,
                    profile_version,
                    versions["config_bundle"],
                    versions["policy"],
                    versions["ranking"],
                    versions["behavior_formula"],
                    versions["dataset"],
                    evaluation_at,
                    now,
                    finished_at,
                    now,
                ),
            )

    async def _insert_transitions(
        self,
        connection: Any,
        *,
        task_id: UUID,
        status: str,
        occurred_at: datetime,
        context_version: int,
    ) -> None:
        if context_version == 1 and status == "WAITING_CLARIFICATION":
            states = (
                ("CREATED", "UNDERSTANDING"),
                ("UNDERSTANDING", "PROBING"),
                ("PROBING", "DECIDING"),
                ("DECIDING", "WAITING_CLARIFICATION"),
            )
        elif context_version > 1:
            states = (
                ("WAITING_CLARIFICATION", "UNDERSTANDING"),
                ("UNDERSTANDING", "PROBING"),
                ("PROBING", "DECIDING"),
                ("DECIDING", "RECALLING"),
                ("RECALLING", "RANKING"),
                ("RANKING", "EXPLAINING"),
                ("EXPLAINING", "PERSISTING"),
                ("PERSISTING", status),
            )
        else:
            states = (
                ("CREATED", "UNDERSTANDING"),
                ("UNDERSTANDING", "PROBING"),
                ("PROBING", "DECIDING"),
                ("DECIDING", "RECALLING"),
                ("RECALLING", "RANKING"),
                ("RANKING", "EXPLAINING"),
                ("EXPLAINING", "PERSISTING"),
                ("PERSISTING", status),
            )
        async with connection.cursor() as cursor:
            for from_status, to_status in states:
                await cursor.execute(
                    "INSERT INTO recommendation_task_transition "
                    "(task_id, context_version, from_status, to_status, reason_code, occurred_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (str(task_id), context_version, from_status, to_status, "G3_RULE_PIPELINE", occurred_at),
                )

    async def _insert_results(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        user_id: int,
        execution: Any,
        output_type: str,
        versions: dict[str, str],
        now: datetime,
        write_trace: bool = True,
        context_version: int = 1,
    ) -> int:
        decision = {
            "output_type": output_type,
            "delivery_strategy": "DEGRADED" if execution.warnings else "DIRECT",
            "explanation_level": "EVIDENCE",
            "adaptation_state": "NORMAL",
            "decision_reason_codes": list(execution.decision_reason_codes),
            "decision_reason": "；".join(execution.decision_reason_codes),
            "policy_version": versions["policy"],
        }
        async with connection.cursor() as cursor:
            for item in execution.items:
                for channel, score in item.feature.channel_scores.items():
                    await cursor.execute(
                        "INSERT INTO recommendation_candidate "
                        "(task_id, plan_version, resource_id, channel, channel_rank, raw_score, "
                        "normalized_score, rrf_contribution, evidence_json, created_at) "
                        "VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            str(task_id),
                            item.feature.resource.id,
                            channel,
                            item.feature.channel_ranks[channel],
                            _decimal(score),
                            _decimal(score),
                            _decimal(score / (60 + item.feature.channel_ranks[channel])),
                            _canonical({"resource_id": item.feature.resource.id, "channel": channel}),
                            now,
                        ),
                    )
            await cursor.execute(
                "INSERT INTO recommendation_record "
                "(task_id, user_id, context_version, output_type, delivery_strategy, ranking_version, "
                "decision_json, warnings_json, versions_json, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(task_id),
                    user_id,
                    context_version,
                    output_type,
                    decision["delivery_strategy"],
                    versions["ranking"],
                    _canonical(decision),
                    _canonical(list(execution.warnings)),
                    _canonical(versions),
                    now,
                ),
            )
            await cursor.execute("SELECT LAST_INSERT_ID()")
            record_id = int((await cursor.fetchone())[0])
            for item in execution.items:
                await cursor.execute(
                    "INSERT INTO recommendation_item "
                    "(record_id, resource_id, rank_no, relevance_score, final_score, mmr_score, "
                    "evidence_confidence, primary_channel, score_detail_json, reason_evidence_json, "
                    "diversity_relaxed, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        record_id,
                        item.feature.resource.id,
                        item.rank_no,
                        _decimal(item.feature.final_score),
                        _decimal(item.feature.final_score),
                        _decimal(item.feature.final_score),
                        _decimal(item.feature.evidence_confidence),
                        item.feature.primary_channel,
                        _canonical(
                            {
                                "channel_scores": dict(item.feature.channel_scores),
                                "channel_ranks": dict(item.feature.channel_ranks),
                                "rrf_score": item.feature.rrf_score,
                                "negative_penalty": item.feature.negative_penalty,
                            }
                        ),
                        _canonical(list(item.evidence_refs)),
                        item.feature.diversity_relaxed,
                        now,
                    ),
                )
                await cursor.execute("SELECT LAST_INSERT_ID()")
                item_id = int((await cursor.fetchone())[0])
                await cursor.execute(
                    "INSERT INTO recommendation_item_explanation "
                    "(recommendation_item_id, explanation_version, explanation_text, "
                    "effective_explanation_level, provider, validator_status, evidence_refs_json, created_at) "
                    "VALUES (%s, 1, %s, 'EVIDENCE', 'TEMPLATE', 'PASSED', %s, %s)",
                    (item_id, item.explanation, _canonical(list(item.evidence_refs)), now),
                )
            await cursor.execute(
                "INSERT INTO recommendation_policy_decision "
                "(task_id, decision_no, context_version, plan_version, output_type, "
                "delivery_strategy, explanation_level, adaptation_state, decision_reason_codes_json, "
                "decision_reason, policy_version, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(task_id),
                    context_version,
                    context_version,
                    1,
                    output_type,
                    decision["delivery_strategy"],
                    decision["explanation_level"],
                    decision["adaptation_state"],
                    _canonical(decision["decision_reason_codes"]),
                    decision["decision_reason"],
                    decision["policy_version"],
                    now,
                ),
            )
            if write_trace:
                await cursor.execute(
                    "INSERT INTO recommendation_trace "
                    "(trace_id, task_id, schema_version, steps_json, complete, created_at) "
                    "VALUES (%s, %s, 'g3-trace-v1', %s, TRUE, %s)",
                    (str(trace_id), str(task_id), _canonical(list(execution.trace_steps)), now),
                )
        return record_id

    @staticmethod
    def _clarification_payload(
        *,
        task_id: UUID,
        trace_id: UUID,
        evaluation_at: datetime,
        versions: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "task_id": str(task_id),
            "record_id": None,
            "trace_id": str(trace_id),
            "status": "WAITING_CLARIFICATION",
            "context_version": 1,
            "evaluation_at": _iso(evaluation_at),
            "decision": {
                "output_type": "PERSONALIZED_FEED",
                "delivery_strategy": "GUIDED",
                "explanation_level": "LIMITED",
                "adaptation_state": "NORMAL",
                "decision_reason_codes": ["MISSING_REQUIRED_SLOTS"],
                "decision_reason": "当前主题和资源类型不足以形成可靠推荐。",
                "policy_version": versions["policy"],
            },
            "questions": list(CLARIFICATION_QUESTIONS),
            "warnings": [],
            "versions": versions,
        }

    async def _insert_waiting_facts(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        request_json: dict[str, object],
        payload: dict[str, Any],
        versions: dict[str, str],
        now: datetime,
    ) -> None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO recommendation_trace "
                "(trace_id, task_id, schema_version, steps_json, complete, created_at) "
                "VALUES (%s, %s, 'g3-trace-v1', %s, TRUE, %s)",
                (
                    str(trace_id),
                    str(task_id),
                    _canonical(
                        [
                            {
                                "step": 1,
                                "name": "RULE_INTENT",
                                "status": "SUCCESS",
                                "intent_type": "UNCLEAR",
                                "confidence": 0.2,
                            },
                            {
                                "step": 2,
                                "name": "POLICY_CLARIFICATION",
                                "status": "WAITING_CLARIFICATION",
                                "reason_code": "MISSING_REQUIRED_SLOTS",
                            },
                        ]
                    ),
                    now,
                ),
            )
            await cursor.execute(
                "INSERT INTO recommendation_policy_decision "
                "(task_id, decision_no, context_version, plan_version, output_type, "
                "delivery_strategy, explanation_level, adaptation_state, decision_reason_codes_json, "
                "decision_reason, policy_version, created_at) "
                "VALUES (%s, 1, 1, NULL, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(task_id),
                    "PERSONALIZED_FEED",
                    "GUIDED",
                    "LIMITED",
                    "NORMAL",
                    _canonical(["MISSING_REQUIRED_SLOTS"]),
                    "当前主题和资源类型不足以形成可靠推荐。",
                    versions["policy"],
                    now,
                ),
            )
        await self._insert_context(
            connection,
            task_id=task_id,
            context_version=1,
            status="WAITING_CLARIFICATION",
            request_json=request_json,
            questions=list(CLARIFICATION_QUESTIONS),
            answers={},
            response=payload,
            idempotency_key=None,
            now=now,
        )
        await self._insert_clarification(
            connection,
            task_id=task_id,
            context_version=1,
            questions=list(CLARIFICATION_QUESTIONS),
            answers={},
            asked_at=now,
            answered_at=None,
        )

    async def _insert_context(
        self,
        connection: Any,
        *,
        task_id: UUID,
        context_version: int,
        status: str,
        request_json: dict[str, Any],
        questions: list[Any],
        answers: dict[str, str],
        response: dict[str, Any],
        idempotency_key: str | None,
        now: datetime,
    ) -> None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO recommendation_task_context "
                "(task_id, context_version, status, request_json, questions_json, answers_json, "
                "response_json, idempotency_key, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(task_id),
                    context_version,
                    status,
                    _canonical(request_json),
                    _canonical(questions),
                    _canonical(answers),
                    _canonical(response),
                    idempotency_key,
                    now,
                ),
            )

    async def _insert_clarification(
        self,
        connection: Any,
        *,
        task_id: UUID,
        context_version: int,
        questions: list[Any],
        answers: dict[str, str],
        asked_at: datetime,
        answered_at: datetime | None,
    ) -> None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO recommendation_clarification "
                "(task_id, context_version, questions_json, answers_json, asked_at, answered_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    str(task_id),
                    context_version,
                    _canonical(questions),
                    _canonical(answers),
                    asked_at,
                    answered_at,
                ),
            )

    async def _insert_trace_revision(
        self,
        connection: Any,
        *,
        task_id: UUID,
        context_version: int,
        trace_id: UUID,
        steps: list[Any],
        now: datetime,
    ) -> None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO recommendation_trace_revision "
                "(trace_id, task_id, context_version, schema_version, steps_json, complete, created_at) "
                "VALUES (%s, %s, %s, 'g3-trace-v1', %s, TRUE, %s)",
                (str(trace_id), str(task_id), context_version, _canonical(steps), now),
            )

    async def _load_execution(self, connection: Any, *, task_id: UUID) -> dict[str, Any]:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT t.trace_id, t.status, t.context_version, t.evaluation_at, "
                "r.id, r.decision_json, r.warnings_json, r.versions_json "
                "FROM recommendation_task t LEFT JOIN recommendation_record r ON r.task_id = t.id "
                "WHERE t.id = %s",
                (str(task_id),),
            )
            task = await cursor.fetchone()
            if task is None:
                raise LookupError("recommendation task not found")
            if task[4] is None:
                await cursor.execute(
                    "SELECT response_json FROM recommendation_task_context "
                    "WHERE task_id = %s ORDER BY context_version DESC LIMIT 1",
                    (str(task_id),),
                )
                context = await cursor.fetchone()
                if context is not None:
                    return _json_object(context[0])
            await cursor.execute(
                "SELECT i.id, i.rank_no, i.evidence_confidence, r.id, r.resource_type, r.title, "
                "r.authors_json, r.publication_year, r.availability_status, e.explanation_text "
                "FROM recommendation_item i "
                "JOIN recommendation_record rr ON rr.id = i.record_id "
                "JOIN resource_catalog r ON r.id = i.resource_id "
                "LEFT JOIN recommendation_item_explanation e "
                "ON e.recommendation_item_id = i.id AND e.explanation_version = 1 "
                "WHERE rr.task_id = %s ORDER BY i.rank_no",
                (str(task_id),),
            )
            items = await cursor.fetchall()
        decision = _json_object(task[5])
        warnings = [str(value) for value in _json_array(task[6])]
        versions = _json_object(task[7])
        return {
            "task_id": str(task_id),
            "record_id": int(task[4]) if task[4] is not None else None,
            "trace_id": str(task[0]),
            "status": str(task[1]),
            "context_version": int(task[2]),
            "evaluation_at": _iso(task[3]),
            "decision": decision,
            "items": [
                {
                    "item_id": int(row[0]),
                    "resource": {
                        "resource_id": int(row[3]),
                        "resource_type": str(row[4]),
                        "title": str(row[5]),
                        "authors": [str(value) for value in _json_array(row[6])],
                        "publication_year": int(row[7]) if row[7] is not None else None,
                        "availability_status": str(row[8]),
                    },
                    "rank_no": int(row[1]),
                    "reason_summary": str(row[9]) if row[9] else "Evidence recorded in the recommendation trace.",
                    "evidence_confidence": float(row[2]),
                }
                for row in items
            ],
            "warnings": warnings,
            "versions": versions,
        }


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return str(value)
