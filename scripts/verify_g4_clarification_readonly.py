#!/usr/bin/env python3
"""Verify the real G4 HOME-empty clarification branch with reads only.

The verifier exercises the port-backed Agents that the opt-in G4 service will
use for an initial clarification task.  It never calls the projection writer,
never commits a transaction, and never touches Neo4j, Chroma, or an external
LLM.  Its evidence is the only input accepted by the clarification ChangePlan
builder.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

import asyncmy

from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
COUNT_TABLES = (
    "resource_catalog",
    "resource_book_detail",
    "tag_dictionary",
    "resource_tag",
    "resource_index_state",
    "recommendation_task",
    "recommendation_task_transition",
    "recommendation_candidate",
    "recommendation_record",
    "recommendation_item",
    "recommendation_item_explanation",
    "recommendation_policy_decision",
    "recommendation_trace",
    "recommendation_trace_revision",
    "recommendation_task_context",
    "recommendation_clarification",
    "recommendation_agent_message",
    "recommendation_agent_result",
    "recommendation_agent_artifact",
    "recommendation_orchestration_result",
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def build_request(run_id: str, *, user_id: int, evaluation_at: datetime) -> OrchestrationRequest:
    if user_id < 1:
        raise ValueError("user id must be positive")
    task_id = uuid5(NAMESPACE_URL, f"g4-clarification-readonly-task:{run_id}")
    trace_id = uuid5(NAMESPACE_URL, f"g4-clarification-readonly-trace:{run_id}")
    session_id = uuid5(NAMESPACE_URL, f"g4-clarification-readonly-session:{run_id}")
    return OrchestrationRequest(
        task_id=task_id,
        trace_id=trace_id,
        session_id=session_id,
        user_id=user_id,
        input_text=None,
        resource_types=(),
        output_type=None,
        constraints={},
        context_version=1,
        evaluation_at=evaluation_at,
        deadline_at=evaluation_at + timedelta(seconds=90),
        scene="HOME",
        limit=5,
    )


async def connect_mysql(values: dict[str, str]) -> Any:
    required = (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"clarification read-only verification requires runtime keys: {missing}")
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=90,
        charset="utf8mb4",
        autocommit=False,
    )


async def read_counts(connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in COUNT_TABLES:
            await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError(f"count query returned no row for {table}")
            counts[table] = int(row[0])
    return counts


def _request_spec(request: OrchestrationRequest) -> dict[str, object]:
    return {
        "scene": request.scene,
        "input_text": request.input_text,
        "resource_types": list(request.resource_types),
        "output_type": request.output_type,
        "limit": request.limit,
    }


async def execute(args: argparse.Namespace) -> dict[str, object]:
    run_id = validate_run_id(args.run_id)
    if args.user_id < 1:
        raise ValueError("user id must be positive")
    compose_values = read_env(args.env_file.resolve())
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secrets_values = read_env(args.secrets_file.resolve())
    values = {**compose_values, **secrets_values}
    connection = await connect_mysql(values)
    try:
        before_counts = await read_counts(connection)
        evaluation_at = datetime.now(UTC)
        request = build_request(run_id, user_id=args.user_id, evaluation_at=evaluation_at)
        orchestrator = build_port_orchestrator(
            MySQLCatalogRepository(connection),
            MySQLProfileSnapshotReader(connection),
            retry_policy=RetryPolicy(max_attempts=2),
        )
        first = await orchestrator.run(request)
        second = await orchestrator.run(request)
        after_counts = await read_counts(connection)
        await connection.rollback()
    finally:
        connection.close()

    if first.status.value != "WAITING_CLARIFICATION":
        raise ValueError(f"clarification branch returned {first.status.value}")
    if len(first.dispatches) != 4:
        raise ValueError("clarification branch must dispatch exactly four Agents")
    if len(first.transitions) != 4:
        raise ValueError("clarification branch must record four state transitions")
    if first.payload != second.payload or first.trace != second.trace:
        raise ValueError("clarification branch was not deterministic")
    questions = first.payload.get("questions")
    if not isinstance(questions, list) or len(questions) < 1:
        raise ValueError("clarification branch returned no questions")
    if before_counts != after_counts:
        raise ValueError("clarification read-only orchestration changed MySQL counts")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    evidence = {
        "schema_version": "g4-clarification-readonly-evidence-v1",
        "status": "PASS",
        "run_id": run_id,
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_host": "127.0.0.1",
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "user_id": args.user_id,
        "task_id": str(first.task_id),
        "trace_id": str(first.trace_id),
        "orchestration_status": first.status.value,
        "dispatch_count": len(first.dispatches),
        "transition_count": len(first.transitions),
        "query_spec": _request_spec(request),
        "questions": questions,
        "dispatches": [
            {
                "receiver": item.message.receiver,
                "agent_version": item.result.agent_version,
                "status": item.result.status.value,
                "confidence": item.result.confidence,
                "warnings": list(item.result.warnings),
                "fallback_used": item.result.fallback_used,
            }
            for item in first.dispatches
        ],
        "before_counts": before_counts,
        "after_counts": after_counts,
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
    (evidence_dir / "clarification-readonly.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G4 clarification read-only verification did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
