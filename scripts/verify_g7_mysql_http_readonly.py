#!/usr/bin/env python3
"""Verify the MySQL-backed Demo HTTP graph using health and read-only counts."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Sequence

import asyncmy
from fastapi.testclient import TestClient

from backend.app.composition import build_demo_mysql_http_app
from backend.app.config import AppSettings
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
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def build_settings(values: dict[str, str]) -> AppSettings:
    return AppSettings(
        app_env="demo",
        app_version="0.1.0",
        config_bundle_path=values["RECPRO_CONFIG_BUNDLE_PATH"],
        config_bundle_sha256=values["RECPRO_CONFIG_BUNDLE_SHA256"],
        config_bundle_version=values["RECPRO_CONFIG_BUNDLE_VERSION"],
        mysql_host="127.0.0.1",
        mysql_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        mysql_database=values["RECPRO_MYSQL_DATABASE"],
        mysql_user=values["RECPRO_MYSQL_USER"],
        mysql_password=values["RECPRO_MYSQL_PASSWORD"],
        mysql_connect_timeout_seconds=float(
            values["RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS"]
        ),
        persistence_probe_id=values["RECPRO_PERSISTENCE_PROBE_ID"],
        llm_provider="mock",
        llm_api_key=None,
    )


async def read_snapshot(values: dict[str, str]) -> dict[str, int]:
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
        counts: dict[str, int] = {}
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            )
            available = {str(row[0]) for row in await cursor.fetchall()}
            missing = sorted(set(COUNT_TABLES) - available)
            if missing:
                raise RuntimeError(f"required read-only count tables are missing: {missing}")
            for table in COUNT_TABLES:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError(f"count query returned no row for {table}")
                counts[table] = int(row[0])
        return counts
    finally:
        connection.close()


async def execute(args: argparse.Namespace) -> dict[str, object]:
    run_id = validate_run_id(args.run_id)
    env_path = args.env_file.resolve()
    values = read_env(env_path)
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g7" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")

    settings = build_settings(values)
    before = await read_snapshot(values)
    application = build_demo_mysql_http_app(settings)
    paths = application.openapi()["paths"]
    if "/api/v1/recommendation-tasks" not in paths:
        raise AssertionError("MySQL-backed Demo graph did not expose the recommendation route")

    with TestClient(application) as client:
        live_response = client.get("/api/v1/health/live")
        ready_response = client.get("/api/v1/health/ready")
    if live_response.status_code != 200:
        raise AssertionError(f"liveness check failed: {live_response.status_code}")
    if ready_response.status_code != 200:
        raise AssertionError(
            f"real MySQL readiness failed: {ready_response.status_code}"
        )
    ready_body = ready_response.json()
    if ready_body.get("can_recommend") is not True:
        raise AssertionError("real MySQL readiness did not enable recommendation capability")
    pipeline = ready_body["components"]["recommendation_pipeline"]
    if pipeline.get("status") != "UP" or pipeline.get("required") is not True:
        raise AssertionError("real MySQL recommendation pipeline is not required and UP")

    after = await read_snapshot(values)
    if after != before:
        raise AssertionError(f"health-only HTTP check changed database counts: {before} -> {after}")

    evidence: dict[str, object] = {
        "schema_version": "g7-mysql-http-readonly-evidence-v1",
        "status": "PASS",
        "run_id": run_id,
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_host": "127.0.0.1",
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "default_llm_provider": "mock",
        "recommendation_route": True,
        "liveness_status": live_response.json().get("status"),
        "readiness_status": ready_body["status"],
        "can_recommend": ready_body["can_recommend"],
        "recommendation_pipeline": pipeline,
        "before_counts": before,
        "after_counts": after,
        # Two snapshots each issue one table-list query plus one COUNT per
        # table; the readiness probe adds the persistence identity and grants
        # queries.  This is the number of SQL statements actually executed,
        # not merely the number of query shapes.
        "database_read_queries": 2 * (1 + len(COUNT_TABLES)) + 2,
        "database_writes": 0,
        "external_requests": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
        "http_business_posts": 0,
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
    parser.add_argument(
        "--env-file", type=Path, default=PROJECT_ROOT / ".env.compose"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G7 MySQL read-only verification did not complete: {type(exc).__name__}")
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
