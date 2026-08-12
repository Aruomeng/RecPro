#!/usr/bin/env python3
"""Verify the opt-in G5 feedback/behavior HTTP graph without business writes.

This verifier composes the real MySQL-backed interaction services, checks the
route contract and health endpoints, and compares full table-count snapshots.
It never runs migrations, seeds data, sends a business POST, claims outbox
work, calls Neo4j/Chroma, or invokes an external LLM.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import asyncmy
from fastapi.testclient import TestClient

from backend.app.composition import (
    build_demo_mysql_http_app,
    build_research_behavior_service,
    build_research_feedback_service,
)
from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g7_mysql_http_readonly import build_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
REQUIRED_ROUTES = (
    "/api/v1/recommendation-impressions/batch",
    "/api/v1/recommendation-items/{item_id}/feedback",
    "/api/v1/behavior-events",
)
G5_TABLES = (
    "recommendation_impression",
    "recommendation_feedback",
    "user_behavior_event",
    "profile_update_outbox",
    "user_resource_state",
    "profile_replay_run",
    "profile_change_log",
    "user_profile",
    "user_interest_tag",
    "user_negative_preference",
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


async def read_snapshot(values: Mapping[str, str]) -> tuple[tuple[str, ...], dict[str, int]]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=60,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() ORDER BY table_name"
            )
            table_names = tuple(str(row[0]) for row in await cursor.fetchall())
            if any(TABLE_PATTERN.fullmatch(table) is None for table in table_names):
                raise RuntimeError("database returned an unsafe table identifier")
            counts: dict[str, int] = {}
            for table in table_names:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError(f"count query returned no row for {table}")
                counts[table] = int(row[0])
        return table_names, counts
    finally:
        connection.close()


async def read_identity_and_grants(values: Mapping[str, str]) -> dict[str, Any]:
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
                "SELECT probe_id, DATABASE(), CURRENT_USER() "
                "FROM recpro_runtime_probe WHERE probe_id = %s",
                (values["RECPRO_PERSISTENCE_PROBE_ID"],),
            )
            identity = await cursor.fetchone()
            if identity is None:
                raise RuntimeError("runtime probe identity was not found")
            if identity[1] != values["RECPRO_MYSQL_DATABASE"]:
                raise RuntimeError("database identity does not match the environment")
            await cursor.execute("SHOW GRANTS")
            grants = tuple(str(row[0]) for row in await cursor.fetchall() if row)
        safe = GrantSafetyEvaluator(values["RECPRO_MYSQL_DATABASE"]).grants_are_safe(grants)
        if not safe:
            raise RuntimeError("runtime grants failed the least-privilege guard")
        return {
            "probe_id": str(identity[0]),
            "database": str(identity[1]),
            "current_user": str(identity[2]),
            "grants_safe": True,
        }
    finally:
        connection.close()


def build_readonly_app(values: Mapping[str, str]):
    settings = build_settings(dict(values))
    feedback_service = build_research_feedback_service(settings)
    behavior_service = build_research_behavior_service(settings)
    return build_demo_mysql_http_app(
        settings,
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        feedback_api_enabled=True,
    )


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validate_run_id(args.run_id)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")

    compose_values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secret_values = read_env(args.secrets_file.resolve(strict=True))
    values = {**compose_values, **secret_values}
    required = (
        "COMPOSE_PROJECT_NAME",
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_PERSISTENCE_PROBE_ID",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")

    before_names, before_counts = await read_snapshot(values)
    identity = await read_identity_and_grants(values)
    application = build_readonly_app(values)
    paths = application.openapi().get("paths", {})
    missing_routes = [path for path in REQUIRED_ROUTES if path not in paths]
    if missing_routes:
        raise RuntimeError(f"feedback HTTP routes are missing: {missing_routes}")
    route_methods = {
        path: sorted(method for method in paths[path] if method in {"get", "post", "put", "patch", "delete"})
        for path in REQUIRED_ROUTES
    }
    if any(methods != ["post"] for methods in route_methods.values()):
        raise RuntimeError(f"unexpected feedback route methods: {route_methods}")

    with TestClient(application) as client:
        live = client.get("/api/v1/health/live")
        ready = client.get("/api/v1/health/ready")
    if live.status_code != 200 or ready.status_code != 200:
        raise RuntimeError(
            f"opt-in feedback health failed: live={live.status_code}, ready={ready.status_code}"
        )
    ready_payload = ready.json()
    if ready_payload.get("can_recommend") is not True:
        raise RuntimeError("opt-in feedback graph did not preserve recommendation readiness")

    after_names, after_counts = await read_snapshot(values)
    if before_names != after_names or before_counts != after_counts:
        raise RuntimeError("health/openapi-only feedback verification changed database counts")

    evidence = {
        "schema_version": "g5-feedback-http-readonly-evidence-v1",
        "status": "PASS",
        "run_id": run_id,
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_host": "127.0.0.1",
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "route_methods": route_methods,
        "health": {
            "live_status_code": live.status_code,
            "ready_status_code": ready.status_code,
            "ready_status": ready_payload.get("status"),
            "can_recommend": ready_payload.get("can_recommend"),
        },
        "database_identity": identity,
        "g5_before_counts": {table: before_counts[table] for table in G5_TABLES},
        "g5_after_counts": {table: after_counts[table] for table in G5_TABLES},
        "before_counts": before_counts,
        "after_counts": after_counts,
        "database_writes": 0,
        "business_posts": 0,
        "outbox_claims": 0,
        "external_requests": 0,
        "external_llm_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "readonly.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G5 feedback HTTP read-only verification did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
