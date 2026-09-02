#!/usr/bin/env python3
"""Verify the frozen G8 cold-user guided branch with reads only.

This verifier exercises the exact ``cold_user_guided`` request from the G8
browser contract using the real MySQL-backed catalog/profile ports and the
deterministic local Agent registry.  It deliberately keeps the connection in
one transaction and rolls it back, never calls a projection writer, and does
not construct Neo4j, Chroma, or an external LLM provider.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy

from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
SCENARIO_ID = "cold_user_guided"
INPUT_TEXT = "我还不确定要研究什么，先帮我梳理方向"
RESOURCE_TYPES = ("BOOK", "PAPER")
OUTPUT_TYPE = "PERSONALIZED_FEED"
LIMIT = 6
COUNT_TARGETS = (
    ("recommendation_task", 1),
    ("recommendation_task_transition", 4),
    ("recommendation_policy_decision", 1),
    ("recommendation_trace", 1),
    ("recommendation_task_context", 1),
    ("recommendation_clarification", 1),
    ("recommendation_agent_message", 4),
    ("recommendation_agent_result", 4),
    ("recommendation_agent_artifact", 1),
    ("recommendation_orchestration_result", 1),
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("git HEAD is not a full commit hash")
    return commit


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use lowercase letters, digits, and hyphens")
    return value


def build_request(run_id: str, *, user_id: int) -> OrchestrationRequest:
    if isinstance(user_id, bool) or user_id < 1:
        raise ValueError("user id must be positive")
    request_id = uuid5(NAMESPACE_URL, f"g8-browser:{run_id}:cold:request")
    session_id = uuid5(NAMESPACE_URL, f"g8-browser:{run_id}:cold:session")
    task_id = uuid5(NAMESPACE_URL, f"task:{user_id}:{request_id}")
    trace_id = uuid5(NAMESPACE_URL, f"trace:{user_id}:{request_id}")
    # The live deadline must be in the future; all other request identities
    # remain deterministic because the evaluation timestamp is not persisted
    # in the read-only evidence payload.
    evaluation_at = datetime.now(UTC)
    return OrchestrationRequest(
        task_id=task_id,
        trace_id=trace_id,
        session_id=session_id,
        user_id=user_id,
        input_text=INPUT_TEXT,
        resource_types=RESOURCE_TYPES,
        output_type=OUTPUT_TYPE,
        constraints={},
        context_version=1,
        evaluation_at=evaluation_at,
        deadline_at=evaluation_at + timedelta(seconds=90),
        scene="SEARCH_AFTER",
        limit=LIMIT,
    )


def request_payload(run_id: str, *, user_id: int) -> dict[str, object]:
    request = build_request(run_id, user_id=user_id)
    return {
        "request_id": str(uuid5(NAMESPACE_URL, f"g8-browser:{run_id}:cold:request")),
        "session_id": str(request.session_id),
        "user_id": user_id,
        "scene": request.scene,
        "input_text": request.input_text,
        "requested_resource_types": list(request.resource_types),
        "requested_output_type": request.output_type,
        "limit": request.limit,
    }


async def connect_mysql(values: Mapping[str, str]) -> Any:
    required = (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"cold read-only verification requires runtime keys: {missing}")
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


async def read_snapshot(connection: Any) -> tuple[tuple[str, ...], dict[str, int]]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() ORDER BY table_name"
        )
        names = tuple(str(row[0]) for row in await cursor.fetchall())
        if not names or any(TABLE_PATTERN.fullmatch(name) is None for name in names):
            raise RuntimeError("database returned no safe table names")
        counts: dict[str, int] = {}
        for name in names:
            await cursor.execute(f"SELECT COUNT(*) FROM `{name}`")
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError(f"count query returned no row for {name}")
            counts[name] = int(row[0])
    return names, counts


async def read_identity_and_grants(values: Mapping[str, str]) -> dict[str, object]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT probe_id, DATABASE(), CURRENT_USER(), "
                "@@character_set_database, @@character_set_connection "
                "FROM recpro_runtime_probe WHERE probe_id = %s",
                (values["RECPRO_PERSISTENCE_PROBE_ID"],),
            )
            identity = await cursor.fetchone()
            if (
                identity is None
                or str(identity[0]) != values["RECPRO_PERSISTENCE_PROBE_ID"]
                or str(identity[1]) != values["RECPRO_MYSQL_DATABASE"]
                or str(identity[2]).split("@", maxsplit=1)[0] != values["RECPRO_MYSQL_USER"]
                or str(identity[3]) != "utf8mb4"
                or str(identity[4]) != "utf8mb4"
            ):
                raise RuntimeError("database identity or runtime probe does not match environment")
            await cursor.execute("SHOW GRANTS")
            grants = tuple(str(row[0]) for row in await cursor.fetchall() if row)
        if not GrantSafetyEvaluator(values["RECPRO_MYSQL_DATABASE"]).grants_are_safe(grants):
            raise RuntimeError("runtime grants failed the least-privilege guard")
        return {
            "probe_id": str(identity[0]),
            "database": str(identity[1]),
            "current_user": str(identity[2]),
            "grants_safe": True,
        }
    finally:
        connection.close()


def _request_spec(request: OrchestrationRequest) -> dict[str, object]:
    return {
        "scene": request.scene,
        "input_text": request.input_text,
        "resource_types": list(request.resource_types),
        "output_type": request.output_type,
        "limit": request.limit,
    }


def _dispatch_summary(result: Any) -> list[dict[str, object]]:
    return [
        {
            "receiver": dispatch.message.receiver,
            "agent_version": dispatch.result.agent_version,
            "status": dispatch.result.status.value,
            "confidence": dispatch.result.confidence,
            "warnings": list(dispatch.result.warnings),
            "fallback_used": dispatch.result.fallback_used,
        }
        for dispatch in result.dispatches
    ]


async def execute(args: argparse.Namespace) -> dict[str, object]:
    run_id = validate_run_id(args.run_id)
    if isinstance(args.user_id, bool) or args.user_id < 1:
        raise ValueError("user id must be positive")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")

    compose_values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    values = {**compose_values, **read_env(args.secrets_file.resolve(strict=True))}
    required = (
        "COMPOSE_PROJECT_NAME",
        "RECPRO_PERSISTENCE_PROBE_ID",
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")

    identity = await read_identity_and_grants(values)
    connection = await connect_mysql(values)
    try:
        before_names, before_counts = await read_snapshot(connection)
        request = build_request(run_id, user_id=args.user_id)
        orchestrator = build_port_orchestrator(
            MySQLCatalogRepository(connection),
            MySQLProfileSnapshotReader(connection),
            retry_policy=RetryPolicy(max_attempts=2),
        )
        first = await orchestrator.run(request)
        second = await orchestrator.run(request)
        after_names, after_counts = await read_snapshot(connection)
        await connection.rollback()
    finally:
        connection.close()

    if first.status.value != "WAITING_CLARIFICATION":
        raise ValueError(f"cold guided branch returned {first.status.value}")
    if len(first.dispatches) != 4 or len(first.transitions) != 4:
        raise ValueError("cold guided branch must dispatch four Agents and four transitions")
    if first.payload != second.payload or first.trace != second.trace:
        raise ValueError("cold guided branch was not deterministic")
    if before_names != after_names or before_counts != after_counts:
        raise ValueError("cold read-only orchestration changed MySQL table names or counts")
    questions = first.payload.get("questions")
    if not isinstance(questions, list) or len(questions) != 2:
        raise ValueError("cold guided branch must return exactly two clarification questions")
    if first.payload.get("decision", {}).get("delivery_strategy") != "GUIDED":
        raise ValueError("cold guided branch did not preserve GUIDED delivery")
    intent = first.payload.get("intent", {})
    if not isinstance(intent, dict) or intent.get("intent_type") != "UNCLEAR":
        raise ValueError("cold guided branch did not classify the goal as UNCLEAR")
    if "LLM_INTENT_SKIPPED_AMBIGUOUS_INPUT" not in first.payload.get("warnings", []):
        raise ValueError("cold guided branch did not prove provider-free fallback")

    payload = request_payload(run_id, user_id=args.user_id)
    target_deltas = {table: delta for table, delta in COUNT_TARGETS}
    evidence = {
        "schema_version": "g8-cold-user-guided-readonly-evidence-v1",
        "status": "PASS",
        "run_id": run_id,
        "scenario_id": SCENARIO_ID,
        "git_commit": current_git_commit(),
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_host": "127.0.0.1",
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "database_identity": identity,
        "request_payload": payload,
        "request_payload_sha256": sha256_bytes(canonical(payload)),
        "task_id": str(first.task_id),
        "trace_id": str(first.trace_id),
        "session_id": str(request.session_id),
        "user_id": args.user_id,
        "orchestration_status": first.status.value,
        "dispatch_count": len(first.dispatches),
        "transition_count": len(first.transitions),
        "query_spec": _request_spec(request),
        "response_summary": {
            "status": first.payload.get("status"),
            "context_version": first.payload.get("context_version"),
            "output_type": first.payload.get("decision", {}).get("output_type"),
            "delivery_strategy": first.payload.get("decision", {}).get("delivery_strategy"),
            "question_count": len(questions),
            "record_id": first.payload.get("record_id"),
        },
        "dispatches": _dispatch_summary(first),
        "before_table_names": list(before_names),
        "after_table_names": list(after_names),
        "before_counts": before_counts,
        "after_counts": after_counts,
        "expected_append_deltas": target_deltas,
        "expected_database_write_rows": sum(target_deltas.values()),
        "safety": {
            "mysql_mode": "SELECT_ONLY_ROLLBACK",
            "mysql_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "external_llm_requests": 0,
            "external_requests": 0,
            "outbox_claims": 0,
            "actual_delete_count": 0,
            "files_deleted": 0,
            "overwritten_inputs": 0,
        },
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output = evidence_dir / "readonly.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
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
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] G8 cold guided read-only verification did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
