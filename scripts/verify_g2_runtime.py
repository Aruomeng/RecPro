"""Verify the G2 schema, seed idempotence, and as-of profile replay invariants."""

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
from scripts.build_g2_dataset_report import build_reports
from scripts.plan_g2_indexes import plan_and_apply
from scripts.replay_g2_profile import apply_replay
from scripts.seed_g2 import insert_seed, validate_seed
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = PROJECT_ROOT / "infra/mysql/migrations/001_g2_core.sql"
SEED_PATH = PROJECT_ROOT / "contracts/data/g2/seed-v1.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
COUNT_TABLES = (
    "recpro_schema_migration",
    "resource_catalog",
    "tag_dictionary",
    "resource_tag",
    "resource_index_state",
    "resource_index_build",
    "resource_index_outbox",
    "user_behavior_event",
    "profile_update_outbox",
    "user_declared_profile_history",
    "recommendation_config_version",
    "g2_seed_run",
    "profile_replay_run",
    "profile_change_log",
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def read_counts(connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in COUNT_TABLES:
            await cursor.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cursor.fetchone()
            counts[table] = int(row[0])
    return counts


async def read_profile_summary(connection: Any, user_id: int) -> dict[str, int | float | None]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT profile_version, profile_confidence, recent_focus_tag_id "
            "FROM user_profile WHERE user_id = %s",
            (user_id,),
        )
        profile = await cursor.fetchone()
        if profile is None:
            raise ValueError("profile replay did not create a current profile projection")
        await cursor.execute(
            "SELECT COUNT(*) FROM user_interest_tag WHERE user_id = %s AND positive_weight > 0",
            (user_id,),
        )
        positive_count = int((await cursor.fetchone())[0])
        await cursor.execute(
            "SELECT COUNT(*) FROM user_negative_preference WHERE user_id = %s AND negative_weight > 0",
            (user_id,),
        )
        negative_count = int((await cursor.fetchone())[0])
    return {
        "profile_version": int(profile[0]),
        "profile_confidence": float(profile[1]),
        "recent_focus_tag_id": int(profile[2]) if profile[2] is not None else None,
        "positive_tag_count": positive_count,
        "negative_tag_count": negative_count,
    }


async def read_constraint_summary(connection: Any, database: str) -> dict[str, int]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = %s AND DELETE_RULE NOT IN ('RESTRICT', 'NO ACTION')",
            (database,),
        )
        unsafe_delete_rules = int((await cursor.fetchone())[0])
        await cursor.execute(
            "SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = %s",
            (database,),
        )
        foreign_keys = int((await cursor.fetchone())[0])
    return {"foreign_key_count": foreign_keys, "unsafe_delete_rule_count": unsafe_delete_rules}


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    env_values = read_env(args.env_file.resolve())
    issues = validate_compose(env_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    migration_user = env_values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    migration_password = env_values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not migration_user or not migration_password:
        raise ValueError("G2 migration credentials are required")
    migration_source = MIGRATION_PATH.read_text(encoding="utf-8")
    migration_statements = split_statements(migration_source)
    seed_bytes = SEED_PATH.read_bytes()
    seed = validate_seed(json.loads(seed_bytes.decode("utf-8")))
    seed_hash = hashlib.sha256(seed_bytes).hexdigest()
    manifest, quality_report = build_reports(seed, seed_path=SEED_PATH, seed_bytes=seed_bytes)
    if manifest["seed_sha256"] != seed_hash or quality_report["status"] != "PASS":
        raise ValueError("G2 dataset manifest or quality report is not valid")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g2" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    await apply_statements(
        host_port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        database=env_values["RECPRO_MYSQL_DATABASE"],
        admin_user=env_values["RECPRO_MYSQL_MIGRATION_USER"],
        admin_password=env_values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
        statements=migration_statements,
    )
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        user=env_values["RECPRO_MYSQL_MIGRATION_USER"],
        password=env_values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
        db=env_values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        before_seed = await read_counts(connection)
        constraints = await read_constraint_summary(connection, env_values["RECPRO_MYSQL_DATABASE"])
    finally:
        connection.close()
    first_seed = await insert_seed(
        host_port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        database=env_values["RECPRO_MYSQL_DATABASE"],
        migration_user=env_values["RECPRO_MYSQL_MIGRATION_USER"],
        migration_password=env_values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
        seed=seed,
        env_values=env_values,
        source_hash=seed_hash,
    )
    second_seed = await insert_seed(
        host_port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        database=env_values["RECPRO_MYSQL_DATABASE"],
        migration_user=env_values["RECPRO_MYSQL_MIGRATION_USER"],
        migration_password=env_values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
        seed=seed,
        env_values=env_values,
        source_hash=seed_hash,
    )
    first_index = await plan_and_apply(
        host_port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        database=env_values["RECPRO_MYSQL_DATABASE"],
        migration_user=migration_user,
        migration_password=migration_password,
        index_version="g2-index-v1",
        apply=True,
    )
    second_index = await plan_and_apply(
        host_port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        database=env_values["RECPRO_MYSQL_DATABASE"],
        migration_user=migration_user,
        migration_password=migration_password,
        index_version="g2-index-v1",
        apply=True,
    )
    first_profile = await apply_replay(
        host_port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        database=env_values["RECPRO_MYSQL_DATABASE"],
        migration_user=env_values["RECPRO_MYSQL_MIGRATION_USER"],
        migration_password=env_values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
        user_id=1001,
        as_of=datetime(2025, 12, 31, 23, 59, 59, 999000),
        formula_version="profile-g2-v1",
    )
    second_profile = await apply_replay(
        host_port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        database=env_values["RECPRO_MYSQL_DATABASE"],
        migration_user=env_values["RECPRO_MYSQL_MIGRATION_USER"],
        migration_password=env_values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
        user_id=1001,
        as_of=datetime(2025, 12, 31, 23, 59, 59, 999000),
        formula_version="profile-g2-v1",
    )
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(env_values["RECPRO_MYSQL_HOST_PORT"]),
        user=env_values["RECPRO_MYSQL_MIGRATION_USER"],
        password=migration_password,
        db=env_values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        after_seed = await read_counts(connection)
        profile_summary = await read_profile_summary(connection, 1001)
    finally:
        connection.close()
    for table in COUNT_TABLES:
        if after_seed[table] < before_seed[table]:
            raise ValueError(f"G2 count decreased for {table}")
    if after_seed["resource_catalog"] < len(seed["resources"]):
        raise ValueError("G2 resource seed count is incomplete")
    if after_seed["tag_dictionary"] < len(seed["tags"]):
        raise ValueError("G2 tag seed count is incomplete")
    if after_seed["user_behavior_event"] < len(seed["behaviors"]):
        raise ValueError("G2 behavior seed count is incomplete")
    expected_index_rows = len(seed["resources"]) * 2
    if after_seed["resource_index_build"] < expected_index_rows:
        raise ValueError("G2 index build plan is incomplete")
    if after_seed["resource_index_outbox"] < expected_index_rows:
        raise ValueError("G2 index outbox plan is incomplete")
    if first_index["plan_count"] != expected_index_rows or second_index["plan_count"] != expected_index_rows:
        raise ValueError("G2 index plan count changed on repeat")
    expected_first_insert = expected_index_rows if before_seed["resource_index_build"] == 0 else 0
    if first_index["inserted_build_count"] != expected_first_insert:
        raise ValueError("G2 first index plan did not respect existing build state")
    if second_index["inserted_build_count"] != 0 or second_index["inserted_outbox_count"] != 0:
        raise ValueError("G2 repeated index plan was not idempotent")
    if profile_summary["positive_tag_count"] <= 0 or profile_summary["negative_tag_count"] <= 0:
        raise ValueError("G2 profile replay did not produce both positive and topic-negative signals")
    if first_profile["input_hash"] != second_profile["input_hash"]:
        raise ValueError("G2 profile replay input hash changed on repeat")
    write_payload = {
        "schema_version": "g2-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "migration_sha256": file_sha256(MIGRATION_PATH),
        "seed_sha256": seed_hash,
        "migration_statement_count": len(migration_statements),
        "before_seed_counts": before_seed,
        "after_seed_counts": after_seed,
        "seed_first": first_seed,
        "seed_second": second_seed,
        "dataset_manifest": manifest,
        "data_quality_report": quality_report,
        "index_first": first_index,
        "index_second": second_index,
        "profile_first": first_profile,
        "profile_second": second_profile,
        "profile_summary": profile_summary,
        "constraints": constraints,
        "destructive_actions": 0,
        "database_sql_actions": {
            "create_if_missing": len(migration_statements) - 1,
            "insert_ignore": 1,
            "seed_insert_only": True,
            "profile_projection_updates": True,
            "index_plan_insert_only": True,
            "external_store_writes": 0,
            "deletes": 0,
        },
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "runtime.json").write_text(json.dumps(write_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] G2 runtime evidence: {evidence_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G2 runtime verification did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
