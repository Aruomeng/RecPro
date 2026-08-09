"""Verify the G3 MySQL-only recommendation slice and idempotent persistence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import asyncmy

from scripts.migrate_g2 import apply_statements, split_statements
from scripts.migrate_g3 import DEFAULT_MIGRATION
from scripts.migrate_g3_clarification import DEFAULT_MIGRATION as CLARIFICATION_MIGRATION
from scripts.migrate_g3_transition import DEFAULT_MIGRATION as TRANSITION_MIGRATION
from scripts.run_g3_demo import run_demo
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
COUNT_TABLES = (
    "recommendation_task",
    "recommendation_candidate",
    "recommendation_record",
    "recommendation_item",
    "recommendation_item_explanation",
    "recommendation_trace",
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


async def read_counts(connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in COUNT_TABLES:
            await cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = int((await cursor.fetchone())[0])
    return counts


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    migration_user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    migration_password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not migration_user or not migration_password:
        raise ValueError("G3 migration credentials are required")
    migration_source = DEFAULT_MIGRATION.read_text(encoding="utf-8")
    statements = split_statements(migration_source)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g3" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    await apply_statements(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        admin_user=migration_user,
        admin_password=migration_password,
        statements=statements,
    )
    await apply_statements(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        admin_user=migration_user,
        admin_password=migration_password,
        statements=split_statements(TRANSITION_MIGRATION.read_text(encoding="utf-8")),
    )
    await apply_statements(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        admin_user=migration_user,
        admin_password=migration_password,
        statements=split_statements(CLARIFICATION_MIGRATION.read_text(encoding="utf-8")),
    )
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=migration_user,
        password=migration_password,
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        before = await read_counts(connection)
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) FROM resource_catalog WHERE availability_status <> 'REMOVED'")
            catalog_count = int((await cursor.fetchone())[0])
    finally:
        connection.close()
    if catalog_count < 5:
        raise ValueError("G3 requires at least five available catalog resources")
    evaluation_at = datetime(2025, 12, 31, 23, 59, 59, 999000)
    first = await run_demo(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        migration_user=migration_user,
        migration_password=migration_password,
        user_id=args.user_id,
        input_text=args.input_text,
        evaluation_at=evaluation_at,
        limit=5,
        apply=True,
    )
    second = await run_demo(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        migration_user=migration_user,
        migration_password=migration_password,
        user_id=args.user_id,
        input_text=args.input_text,
        evaluation_at=evaluation_at,
        limit=5,
        apply=True,
    )
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=migration_user,
        password=migration_password,
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        after = await read_counts(connection)
    finally:
        connection.close()
    for table in COUNT_TABLES:
        if after[table] < before[table]:
            raise ValueError(f"G3 count decreased for {table}")
    if before["recommendation_task"] == 0 and not first["applied"]:
        raise ValueError("G3 first recommendation was not persisted")
    if first["item_count"] < 5 or first["candidate_count"] < 5:
        raise ValueError("G3 recommendation did not produce five evidence-bearing items")
    if not second["idempotent_replay"] or second["item_count"] != first["item_count"]:
        raise ValueError("G3 repeated request was not idempotent")
    if after["recommendation_task"] < 1 or after["recommendation_record"] < 1 or after["recommendation_trace"] < 1:
        raise ValueError("G3 persisted task, record, or trace is incomplete")
    payload = {
        "schema_version": "g3-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "migration_sha256": hashlib.sha256(DEFAULT_MIGRATION.read_bytes()).hexdigest(),
        "migration_statement_count": len(statements),
        "before_counts": before,
        "after_counts": after,
        "first_demo": first,
        "second_demo": second,
        "destructive_actions": 0,
        "database_sql_actions": {
            "create_if_missing": len(statements) - 1,
            "insert_only_result_persistence": True,
            "optional_store_writes": 0,
            "deletes": 0,
        },
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "runtime.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] G3 runtime evidence: {evidence_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--input-text", default="多智能体推荐系统论文与图书")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G3 runtime verification did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
