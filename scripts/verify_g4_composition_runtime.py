"""Verify the explicit research composition root and atomic G4 persistence."""

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

from backend.app.composition import build_research_orchestration_service
from backend.app.config import AppSettings
from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.recommendation.adapters.mysql import MySQLRecommendationTaskService
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.domain.public import RecommendationTaskCommand
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
G4_TABLES = (
    "recommendation_agent_message",
    "recommendation_agent_result",
    "recommendation_agent_artifact",
    "recommendation_orchestration_result",
)
PROTECTED_TABLES = (
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


async def apply_forward_migration(
    *, host_port: int, database: str, user: str, password: str, path: Path
) -> None:
    await apply_statements(
        host_port=host_port,
        database=database,
        admin_user=user,
        admin_password=password,
        statements=split_statements(path.read_text(encoding="utf-8")),
    )


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


async def read_counts(connection: Any, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in tables:
            await cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = int((await cursor.fetchone())[0])
    return counts


def command_for(run_id: str, *, user_id: int) -> RecommendationTaskCommand:
    return RecommendationTaskCommand(
        request_id=uuid5(NAMESPACE_URL, f"g4-composition-request:{run_id}"),
        session_id=uuid5(NAMESPACE_URL, f"g4-composition-session:{run_id}"),
        user_id=user_id,
        scene="SEARCH_AFTER",
        input_text="多智能体推荐系统",
        resource_types=("BOOK", "PAPER"),
        output_type="TOPIC_RESOURCES",
        source_resource_id=None,
        source_item_id=None,
        evaluation_at=datetime(2025, 12, 31, 23, 59, 59, 999000),
        constraints={},
        limit=5,
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
        raise ValueError("G4 composition runtime credentials are required")
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

    g3_service = MySQLRecommendationTaskService(
        host="127.0.0.1",
        port=host_port,
        database=database,
        user=runtime_user,
        password=runtime_password,
        connect_timeout=10,
        catalog_repository_factory=MySQLCatalogRepository,
        config_bundle_version=values["RECPRO_CONFIG_BUNDLE_VERSION"],
        dataset_version=str(seed["dataset_version"]),
    )
    command = command_for(run_id, user_id=args.user_id)
    task_result = await g3_service.create_task(command, idempotency_key=str(command.request_id))
    task_id = UUID(str(task_result.payload["task_id"]))
    trace_id = UUID(str(task_result.payload["trace_id"]))

    baseline_connection = await connect(values, autocommit=True)
    try:
        baseline = await read_counts(baseline_connection, G4_TABLES + PROTECTED_TABLES)
    finally:
        baseline_connection.close()

    settings = AppSettings(
        app_env="development",
        mysql_host="127.0.0.1",
        mysql_port=host_port,
        mysql_database=database,
        mysql_user=runtime_user,
        mysql_password=runtime_password,
        mysql_connect_timeout_seconds=10,
    )
    service = build_research_orchestration_service(settings)
    evaluation_at = datetime(2025, 12, 31, 23, 59, 59, 999000, tzinfo=UTC)
    request = OrchestrationRequest(
        task_id=task_id,
        trace_id=trace_id,
        user_id=args.user_id,
        session_id=command.session_id,
        input_text=command.input_text,
        resource_types=command.resource_types,
        output_type=command.output_type,
        limit=command.limit,
        evaluation_at=evaluation_at,
        deadline_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    first = await service.run(request)
    after_first_connection = await connect(values, autocommit=True)
    try:
        after_first = await read_counts(after_first_connection, G4_TABLES + PROTECTED_TABLES)
    finally:
        after_first_connection.close()
    second = await service.run(request)
    after_replay_connection = await connect(values, autocommit=True)
    try:
        after_replay = await read_counts(after_replay_connection, G4_TABLES + PROTECTED_TABLES)
    finally:
        after_replay_connection.close()

    expected_delta = {
        "recommendation_agent_message": 7,
        "recommendation_agent_result": 7,
        "recommendation_agent_artifact": 1,
        "recommendation_orchestration_result": 1,
    }
    if first.status.value != "COMPLETED" or len(first.dispatches) != 7:
        raise ValueError("research composition did not complete seven dispatches")
    if first.payload != second.payload or first.trace != second.trace:
        raise ValueError("research composition replay was not deterministic")
    for table, delta in expected_delta.items():
        if after_first[table] != baseline[table] + delta:
            raise ValueError(f"composition commit delta mismatch for {table}")
    if after_replay != after_first:
        raise ValueError("composition idempotent replay changed fact counts")
    for table in PROTECTED_TABLES:
        if after_replay[table] != baseline[table]:
            raise ValueError(f"composition path changed protected table {table}")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence = {
        "schema_version": "g4-composition-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "composition_root": "research",
        "task_id": str(task_id),
        "trace_id": str(trace_id),
        "evaluation_at": evaluation_at.isoformat(),
        "orchestration_status": first.status.value,
        "dispatch_count": len(first.dispatches),
        "artifact_type": "ORCHESTRATION_TRACE",
        "before_counts": baseline,
        "after_first_counts": after_first,
        "after_replay_counts": after_replay,
        "expected_first_delta": expected_delta,
        "database_sql_actions": {
            "reads": "Catalog/Profile SELECT plus append identity SELECTs",
            "g4_inserts_first_run": 16,
            "updates": 0,
            "deletes": 0,
        },
        "destructive_actions": 0,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "composition-runtime.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G4 composition runtime evidence: {evidence_dir}")
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
        print(f"[FAIL] G4 composition runtime verification did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
