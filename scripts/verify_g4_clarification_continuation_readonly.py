#!/usr/bin/env python3
"""Run one G4 clarification continuation as a read-only projection rehearsal.

The rehearsal reads the existing waiting task/context, validates the submitted
answers through the pure continuation contract, runs the port-backed Agents,
and builds the exact G4 write plan in memory.  It never invokes the G4 writer,
never commits, and never touches Neo4j, Chroma, or an external LLM.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from uuid import UUID

import asyncmy

from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.application.g4_clarification import (
    build_g4_clarification_continuation,
)
from backend.app.recommendation.application.g4_persistence import (
    build_g4_projection_write_plan,
)
from backend.app.recommendation.application.g4_projection import (
    G4ProjectionVersions,
    G4ResourceProjection,
    G4TaskIdentity,
    build_orchestration_request,
)
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from backend.app.recommendation.domain.public import RecommendationTaskCommand
from backend.app.shared_kernel.contracts.enums import TaskStatus
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g4_clarification_readonly import COUNT_TABLES, read_counts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
ANSWER_SLOTS = ("resource_types", "topic")


def _parse_answers(raw: str) -> dict[str, str]:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != set(ANSWER_SLOTS):
        raise ValueError("answers must contain exactly resource_types and topic")
    if any(
        not isinstance(item, str) or not item.strip() or len(item.strip()) > 500
        for item in value.values()
    ):
        raise ValueError("answers must be non-blank strings of at most 500 characters")
    return {str(key): str(item).strip() for key, item in value.items()}


def _command_from_request(value: Mapping[str, object]) -> RecommendationTaskCommand:
    return RecommendationTaskCommand(
        request_id=UUID(str(value["request_id"])),
        session_id=UUID(str(value["session_id"])),
        user_id=int(value["user_id"]),
        scene=str(value["scene"]),
        input_text=value.get("input_text"),
        resource_types=tuple(str(item) for item in value.get("resource_types", ())),
        output_type=value.get("output_type"),
        source_resource_id=value.get("source_resource_id"),
        source_item_id=value.get("source_item_id"),
        evaluation_at=None,
        constraints=dict(value.get("constraints") or {}),
        limit=int(value["limit"]),
    )


def _aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _resource_projection(resource: Any) -> G4ResourceProjection:
    return G4ResourceProjection(
        resource_id=int(resource.id),
        resource_type=str(resource.resource_type),
        title=str(resource.title),
        authors=tuple(str(author) for author in resource.authors),
        publication_year=resource.publication_year,
        availability_status=str(resource.availability_status),
    )


async def _connect(values: Mapping[str, str]) -> Any:
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=120,
        charset="utf8mb4",
        autocommit=False,
    )


def _delta_projection(plan: Any, dispatch_count: int) -> dict[str, int]:
    if plan.status not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise ValueError(f"continuation rehearsal returned unexpected status {plan.status}")
    return {
        "recommendation_task_transition": len(plan.transitions),
        "recommendation_candidate": len(plan.candidates),
        "recommendation_record": 1,
        "recommendation_item": len(plan.items),
        "recommendation_item_explanation": len(plan.items),
        "recommendation_policy_decision": 1,
        "recommendation_trace_revision": 1,
        "recommendation_task_context": 1,
        "recommendation_clarification": 1,
        "recommendation_agent_message": dispatch_count,
        "recommendation_agent_result": dispatch_count,
        "recommendation_agent_artifact": 1,
        "recommendation_orchestration_result": 1,
    }


async def execute(args: argparse.Namespace) -> dict[str, object]:
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    task_id = UUID(args.task_id)
    if args.answers_json is not None:
        answers = _parse_answers(args.answers_json)
    elif args.resource_types and args.topic:
        answers = _parse_answers(
            json.dumps(
                {"resource_types": args.resource_types, "topic": args.topic},
                ensure_ascii=False,
            )
        )
    else:
        raise ValueError("provide answers-json or both resource-types and topic")
    values = {
        **read_env(args.env_file.resolve()),
        **read_env(args.secrets_file.resolve()),
    }
    compose_values = read_env(args.env_file.resolve())
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    connection = await _connect(values)
    try:
        before_counts = await read_counts(connection)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, request_id, trace_id, user_id, session_id, trigger_scene, "
                "evaluation_at, config_bundle_version, dataset_version "
                "FROM recommendation_task WHERE id = %s AND user_id = %s",
                (str(task_id), args.user_id),
            )
            task = await cursor.fetchone()
            await cursor.execute(
                "SELECT context_version, status, request_json, questions_json, "
                "answers_json, idempotency_key FROM recommendation_task_context "
                "WHERE task_id = %s ORDER BY context_version DESC LIMIT 1",
                (str(task_id),),
            )
            context = await cursor.fetchone()
        if task is None:
            raise ValueError("waiting task does not belong to the requested user")
        if context is None or int(context[0]) != args.context_version:
            raise ValueError("latest context version does not match the rehearsal")
        if str(context[1]) != "WAITING_CLARIFICATION":
            raise ValueError("latest context is not WAITING_CLARIFICATION")
        if json.loads(context[4]) != {} or context[5] is not None:
            raise ValueError("the rehearsal requires an unanswered context")

        base_command = _command_from_request(json.loads(context[2]))
        continuation = build_g4_clarification_continuation(
            base_command,
            questions=json.loads(context[3]),
            answers=answers,
            previous_context_version=args.context_version,
        )
        evaluation_at = _aware_utc(task[6])
        orchestration_request = build_orchestration_request(
            continuation.command,
            evaluation_at=evaluation_at,
            deadline_at=datetime.now(UTC) + timedelta(seconds=90),
            context_version=continuation.context_version,
            identity=G4TaskIdentity(task_id=task_id, trace_id=UUID(str(task[2]))),
            initial_status=TaskStatus.WAITING_CLARIFICATION,
        )
        orchestrator = build_port_orchestrator(
            MySQLCatalogRepository(connection),
            MySQLProfileSnapshotReader(connection),
            retry_policy=RetryPolicy(max_attempts=2),
        )
        result = await orchestrator.run(orchestration_request)
        catalog = MySQLCatalogRepository(connection)
        resources = {
            int(resource.id): _resource_projection(resource)
            for resource in await catalog.list_resources(available_at=evaluation_at)
        }
        projection = build_g4_projection_write_plan(
            continuation.command,
            result,
            resources=resources,
            versions=G4ProjectionVersions(
                config_bundle=str(task[7]), dataset=str(task[8])
            ),
            evaluation_at=evaluation_at,
            started_at=datetime.now(UTC),
        )
        after_counts = await read_counts(connection)
        await connection.rollback()
    finally:
        connection.close()

    if before_counts != after_counts:
        raise ValueError("continuation read-only rehearsal changed MySQL counts")
    deltas = _delta_projection(projection, len(result.dispatches))
    if result.context_version != args.context_version + 1:
        raise ValueError("continuation did not advance exactly one context version")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / args.run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    evidence = {
        "schema_version": "g4-clarification-continuation-readonly-evidence-v1",
        "status": "PASS",
        "run_id": args.run_id,
        "task_id": str(task_id),
        "trace_id": str(task[2]),
        "user_id": args.user_id,
        "previous_context_version": args.context_version,
        "next_context_version": result.context_version,
        "answers": answers,
        "orchestration_status": result.status.value,
        "dispatch_count": len(result.dispatches),
        "transition_count": len(result.transitions),
        "candidate_count": len(projection.candidates),
        "item_count": len(projection.items),
        "trace_step_count": len(projection.trace_steps),
        "warnings": list(projection.warnings),
        "decision": dict(projection.decision),
        "proposed_idempotency_key": args.idempotency_key,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "expected_deltas": deltas,
        "safety": {
            "mysql_mode": "SELECT_ONLY_ROLLBACK",
            "mysql_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "external_requests": 0,
            "actual_delete_count": 0,
            "files_deleted": 0,
            "overwritten_inputs": 0,
        },
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "clarification-continuation-readonly.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--context-version", type=int, default=1)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--answers-json")
    parser.add_argument("--resource-types")
    parser.add_argument("--topic")
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(execute(args))
    except (
        OSError,
        RuntimeError,
        ValueError,
        asyncmy.errors.Error,
        json.JSONDecodeError,
    ) as exc:
        print(
            "[FAIL] G4 clarification continuation read-only rehearsal did not complete: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
