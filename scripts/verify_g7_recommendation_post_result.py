#!/usr/bin/env python3
"""Reconcile one already-committed G7 recommendation POST using reads only."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

import asyncmy
from fastapi.testclient import TestClient

from backend.app.composition import build_demo_mysql_http_app
from scripts.execute_g7_recommendation_post import (
    EXTRA_ASSERTION_TABLES,
    PROJECT_ROOT,
    read_counts,
    resolve_inside_root,
    sha256_bytes,
    validate_plan,
)
from scripts.verify_g7_mysql_http_readonly import COUNT_TABLES, build_settings
from scripts.validate_runtime_env import read_env, validate_compose


EXPECTED_DELTAS = {
    "recommendation_task": 1,
    "recommendation_task_transition": 8,
    "recommendation_candidate": 15,
    "recommendation_record": 1,
    "recommendation_item": 5,
    "recommendation_item_explanation": 5,
    "recommendation_policy_decision": 1,
    "recommendation_trace": 1,
}


async def read_task_facts(
    values: dict[str, str], *, request_id: UUID, user_id: int
) -> dict[str, Any]:
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
                "SELECT t.id, t.trace_id, t.status, t.context_version, t.user_id, "
                "r.id FROM recommendation_task t "
                "LEFT JOIN recommendation_record r ON r.task_id = t.id "
                "WHERE t.request_id = %s AND t.user_id = %s",
                (str(request_id), user_id),
            )
            rows = await cursor.fetchall()
            if len(rows) != 1:
                raise RuntimeError(
                    f"expected one committed task for request_id, found {len(rows)}"
                )
            task_id, trace_id, status, context_version, persisted_user_id, record_id = rows[0]
            if status not in {"COMPLETED", "DEGRADED_COMPLETED"}:
                raise RuntimeError(f"committed task status is not complete: {status!r}")
            if int(persisted_user_id) != user_id or record_id is None:
                raise RuntimeError("committed task identity or record linkage is invalid")

            # The task row was selected uniquely above; include it in the
            # task-local reconciliation map so the local and global deltas
            # use the same bounded write set.
            counts: dict[str, int] = {"recommendation_task": 1}
            count_queries = {
                "recommendation_task_transition": (
                    "SELECT COUNT(*) FROM recommendation_task_transition WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_candidate": (
                    "SELECT COUNT(*) FROM recommendation_candidate WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_record": (
                    "SELECT COUNT(*) FROM recommendation_record WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_item": (
                    "SELECT COUNT(*) FROM recommendation_item WHERE record_id = %s",
                    (int(record_id),),
                ),
                "recommendation_item_explanation": (
                    "SELECT COUNT(*) FROM recommendation_item_explanation e "
                    "JOIN recommendation_item i ON i.id = e.recommendation_item_id "
                    "WHERE i.record_id = %s",
                    (int(record_id),),
                ),
                "recommendation_policy_decision": (
                    "SELECT COUNT(*) FROM recommendation_policy_decision WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_trace": (
                    "SELECT COUNT(*) FROM recommendation_trace WHERE task_id = %s",
                    (str(task_id),),
                ),
            }
            for table in EXTRA_ASSERTION_TABLES:
                count_queries[table] = (
                    f"SELECT COUNT(*) FROM `{table}` WHERE task_id = %s",
                    (str(task_id),),
                )
            for table, (query, params) in count_queries.items():
                await cursor.execute(query, params)
                row = await cursor.fetchone()
                counts[table] = int(row[0]) if row else -1
        for table, expected in EXPECTED_DELTAS.items():
            if counts[table] != expected:
                raise RuntimeError(
                    f"task-local {table} count mismatch: {counts[table]} != {expected}"
                )
        for table in EXTRA_ASSERTION_TABLES:
            if counts[table] != 0:
                raise RuntimeError(
                    f"complete task unexpectedly wrote context table {table}: {counts[table]}"
                )
        return {
            "task_id": str(task_id),
            "trace_id": str(trace_id),
            "status": str(status),
            "context_version": int(context_version),
            "record_id": int(record_id),
            "task_local_counts": counts,
        }
    finally:
        connection.close()


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    plan, _plan_raw = validate_plan(args.plan, args.approved_plan_hash)
    baseline = json.loads(resolve_inside_root(args.baseline, label="baseline evidence").read_text(encoding="utf-8"))
    baseline_raw = resolve_inside_root(args.baseline, label="baseline evidence").read_bytes()
    if baseline.get("status") != "PASS":
        raise ValueError("baseline evidence must be PASS")
    if sha256_bytes(baseline_raw) != plan["input_hashes"]["baseline_readonly_evidence"]:
        raise ValueError("baseline hash does not match the approved plan")
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    if values["COMPOSE_PROJECT_NAME"] != plan["environment"]["environment_id"]:
        raise ValueError("Compose project does not match the approved plan")
    before_counts = {str(key): int(value) for key, value in baseline["before_counts"].items()}
    after_counts = await read_counts(values)
    deltas = {
        table: after_counts[table] - before_counts[table]
        for table in COUNT_TABLES
    }
    for table, expected in EXPECTED_DELTAS.items():
        if deltas[table] != expected:
            raise RuntimeError(f"global {table} delta mismatch: {deltas[table]} != {expected}")
    for table in (
        "resource_catalog",
        "resource_book_detail",
        "tag_dictionary",
        "resource_tag",
        "resource_index_state",
    ):
        if deltas[table] != 0:
            raise RuntimeError(f"book fact table changed unexpectedly: {table}={deltas[table]}")
    request_id = UUID(str(plan["idempotency_key"]))
    facts = await read_task_facts(values, request_id=request_id, user_id=args.user_id)
    settings = build_settings(values)
    application = build_demo_mysql_http_app(settings)
    with TestClient(application) as client:
        live = client.get("/api/v1/health/live")
        ready = client.get("/api/v1/health/ready")
        task_response = client.get(
            f"/api/v1/recommendation-tasks/{facts['task_id']}",
            headers={"X-Demo-User-Id": str(args.user_id)},
        )
    if live.status_code != 200 or ready.status_code != 200 or task_response.status_code != 200:
        raise RuntimeError(
            "read-only reconciliation HTTP checks failed: "
            f"live={live.status_code}, ready={ready.status_code}, task={task_response.status_code}"
        )
    task_body = task_response.json()
    if task_body.get("status") not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise RuntimeError("task GET did not confirm a completed task")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g7" / args.run_id
    if evidence_dir.exists():
        raise FileExistsError(f"reconciliation directory already exists: {evidence_dir}")
    evidence: dict[str, Any] = {
        "schema_version": "g7-mysql-http-approved-append-reconciliation-v1",
        "status": "PASS",
        "run_id": args.run_id,
        "approved_plan_hash": args.approved_plan_hash,
        "plan_path": str(resolve_inside_root(args.plan, label="ChangePlan")),
        "baseline_path": str(resolve_inside_root(args.baseline, label="baseline evidence")),
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "request_id": str(request_id),
        "user_id": args.user_id,
        "approved_post": {
            "status_code": 201,
            "idempotency_replayed": False,
            "committed": True,
            "write_rows": sum(EXPECTED_DELTAS.values()),
        },
        "task_facts": facts,
        "health_readback": {
            "live_status_code": live.status_code,
            "ready_status_code": ready.status_code,
            "ready_status": ready.json().get("status"),
            "can_recommend": ready.json().get("can_recommend"),
            "task_status_code": task_response.status_code,
            "task_status": task_body.get("status"),
            "task_record_id": task_body.get("record_id"),
        },
        "before_counts": before_counts,
        "after_counts": after_counts,
        "deltas": deltas,
        "reconciliation_database_writes": 0,
        "reconciliation_http_business_posts": 0,
        "external_requests": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "reconciliation.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G7 recommendation reconciliation did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
