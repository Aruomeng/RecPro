"""Verify G4 real Catalog/Profile ports through an isolated MySQL read path."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy

from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from backend.app.recommendation.agents.base import RetryPolicy
from scripts.migrate_g2 import apply_statements, split_statements
from scripts.replay_g2_profile import apply_replay
from scripts.seed_g2 import DEFAULT_SEED, insert_seed, sha256_bytes, validate_seed
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MIGRATIONS = tuple(
    PROJECT_ROOT / "infra/mysql/migrations" / name
    for name in (
        "001_g2_core.sql",
        "002_g3_recommendation.sql",
        "003_g3_task_transition.sql",
        "004_g3_clarification_debug.sql",
        "005_g4_agent_execution.sql",
    )
)
COUNT_TABLES = (
    "resource_catalog",
    "resource_tag",
    "user_profile",
    "user_interest_tag",
    "user_negative_preference",
    "profile_replay_run",
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


async def apply_forward_migration(*, host_port: int, database: str, user: str, password: str, path: Path) -> None:
    await apply_statements(
        host_port=host_port,
        database=database,
        admin_user=user,
        admin_password=password,
        statements=split_statements(path.read_text(encoding="utf-8")),
    )


async def read_counts(connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in COUNT_TABLES:
            await cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = int((await cursor.fetchone())[0])
    return counts


async def connect(values: dict[str, str], *, autocommit: bool) -> Any:
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=autocommit,
    )


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    migration_user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    migration_password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    runtime_user = values.get("RECPRO_MYSQL_USER", "")
    runtime_password = values.get("RECPRO_MYSQL_PASSWORD", "")
    if not migration_user or not migration_password or not runtime_user or not runtime_password:
        raise ValueError("G4 real-port runtime credentials are required")
    host_port = int(values["RECPRO_MYSQL_HOST_PORT"])
    database = values["RECPRO_MYSQL_DATABASE"]

    await apply_forward_migration(
        host_port=host_port,
        database=database,
        user=migration_user,
        password=migration_password,
        path=MIGRATIONS[0],
    )
    seed_bytes = DEFAULT_SEED.read_bytes()
    seed = validate_seed(json.loads(seed_bytes.decode("utf-8")))
    await insert_seed(
        host_port=host_port,
        database=database,
        migration_user=migration_user,
        migration_password=migration_password,
        seed=seed,
        env_values=values,
        source_hash=sha256_bytes(seed_bytes),
    )
    await apply_replay(
        host_port=host_port,
        database=database,
        migration_user=migration_user,
        migration_password=migration_password,
        user_id=args.user_id,
        as_of=datetime(2025, 12, 31, 23, 59, 59, 999000),
        formula_version="profile-g2-v1",
    )
    for migration in MIGRATIONS[1:]:
        await apply_forward_migration(
            host_port=host_port,
            database=database,
            user=migration_user,
            password=migration_password,
            path=migration,
        )

    before_connection = await connect(values, autocommit=True)
    try:
        before = await read_counts(before_connection)
    finally:
        before_connection.close()

    evaluation_at = datetime(2025, 12, 31, 23, 59, 59, 999000, tzinfo=UTC)
    task_id = uuid5(NAMESPACE_URL, f"g4-real-port-task:{run_id}")
    trace_id = uuid5(NAMESPACE_URL, f"g4-real-port-trace:{run_id}")
    session_id = uuid5(NAMESPACE_URL, f"g4-real-port-session:{run_id}")
    connection = await connect(values, autocommit=False)
    try:
        catalog = MySQLCatalogRepository(connection)
        profile = MySQLProfileSnapshotReader(connection)
        orchestrator = build_port_orchestrator(
            catalog,
            profile,
            retry_policy=RetryPolicy(max_attempts=2),
        )
        request = OrchestrationRequest(
            task_id=task_id,
            trace_id=trace_id,
            user_id=args.user_id,
            session_id=session_id,
            input_text="多智能体推荐系统",
            resource_types=("BOOK", "PAPER"),
            limit=5,
            evaluation_at=evaluation_at,
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )
        first = await orchestrator.run(request)
        second = await orchestrator.run(request)
        await connection.rollback()
    finally:
        connection.close()
    if first.status.value != "COMPLETED":
        raise ValueError(f"real-port orchestration returned {first.status.value}")
    if first.payload != second.payload or first.trace != second.trace:
        raise ValueError("real-port orchestration was not deterministic")
    if len(first.dispatches) != 7:
        raise ValueError("real-port orchestration did not dispatch seven Agents")
    profile_dispatch = next(item for item in first.dispatches if item.message.receiver == "UserProfileAgent")
    semantic_dispatch = next(item for item in first.dispatches if item.message.receiver == "ResourceSemanticAgent")
    recall_dispatch = next(item for item in first.dispatches if item.message.receiver == "CandidateRecallAgent")
    if int(profile_dispatch.result.payload.get("event_count", 0)) <= 0:
        raise ValueError("real profile port returned no replayed events")
    if int(semantic_dispatch.result.payload.get("catalog_count", 0)) <= 0:
        raise ValueError("real catalog semantic port returned no resources")
    if int(recall_dispatch.result.payload.get("candidate_count", 0)) <= 0:
        raise ValueError("real catalog recall port returned no candidates")

    after_connection = await connect(values, autocommit=True)
    try:
        after = await read_counts(after_connection)
    finally:
        after_connection.close()
    if after != before:
        raise ValueError("real Catalog/Profile path changed database facts")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence = {
        "schema_version": "g4-real-port-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "task_id": str(task_id),
        "trace_id": str(trace_id),
        "evaluation_at": evaluation_at.isoformat(),
        "orchestration_status": first.status.value,
        "dispatch_count": len(first.dispatches),
        "profile": {
            "agent_version": profile_dispatch.result.agent_version,
            "event_count": profile_dispatch.result.payload.get("event_count"),
            "profile_version": profile_dispatch.result.payload.get("profile_version"),
        },
        "catalog": {
            "agent_version": semantic_dispatch.result.agent_version,
            "resource_count": semantic_dispatch.result.payload.get("catalog_count"),
            "candidate_count": recall_dispatch.result.payload.get("candidate_count"),
        },
        "before_counts": before,
        "after_counts": after,
        "database_sql_actions": {"selects": "read-only adapters only", "inserts": 0, "updates": 0, "deletes": 0},
        "destructive_actions": 0,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "real-ports-runtime.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G4 real-port runtime evidence: {evidence_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G4 real-port runtime verification did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
