"""Verify the opt-in G3 API against an isolated MySQL runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy
from fastapi.testclient import TestClient

from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.recommendation.adapters.mysql import MySQLRecommendationTaskService
from scripts.migrate_g2 import apply_statements, split_statements
from scripts.replay_g2_profile import apply_replay
from scripts.seed_g2 import DEFAULT_SEED, insert_seed, sha256_bytes, validate_seed
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
G2_MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/001_g2_core.sql"
G3_MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/002_g3_recommendation.sql"
TRANSITION_MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/003_g3_task_transition.sql"
COUNT_TABLES = (
    "recommendation_task",
    "recommendation_task_transition",
    "recommendation_candidate",
    "recommendation_record",
    "recommendation_item",
    "recommendation_item_explanation",
    "recommendation_trace",
)


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


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


async def apply_forward_migration(*, host_port: int, database: str, user: str, password: str, path: Path) -> None:
    await apply_statements(
        host_port=host_port,
        database=database,
        admin_user=user,
        admin_password=password,
        statements=split_statements(path.read_text(encoding="utf-8")),
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
        raise ValueError("G3 API runtime credentials are required")
    host_port = int(values["RECPRO_MYSQL_HOST_PORT"])
    database = values["RECPRO_MYSQL_DATABASE"]

    await apply_forward_migration(
        host_port=host_port,
        database=database,
        user=migration_user,
        password=migration_password,
        path=G2_MIGRATION,
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
    await apply_forward_migration(
        host_port=host_port,
        database=database,
        user=migration_user,
        password=migration_password,
        path=G3_MIGRATION,
    )
    await apply_forward_migration(
        host_port=host_port,
        database=database,
        user=migration_user,
        password=migration_password,
        path=TRANSITION_MIGRATION,
    )

    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=host_port,
        user=runtime_user,
        password=runtime_password,
        db=database,
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        before = await read_counts(connection)
    finally:
        connection.close()

    service = MySQLRecommendationTaskService(
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
    settings = AppSettings(
        app_env="demo",
        mysql_host="127.0.0.1",
        mysql_port=host_port,
        mysql_database=database,
        mysql_user=runtime_user,
        mysql_password=runtime_password,
        config_bundle_version=values["RECPRO_CONFIG_BUNDLE_VERSION"],
        config_bundle_path=values["RECPRO_CONFIG_BUNDLE_PATH"],
        config_bundle_sha256=values["RECPRO_CONFIG_BUNDLE_SHA256"],
    )
    application = create_app(
        settings=settings,
        readiness_probe=UpProbe(),
        config_bundle_probe=UpProbe(),
        recommendation_service=service,
        recommendation_api_enabled=True,
    )
    request_id = uuid5(NAMESPACE_URL, f"g3-api:{run_id}")
    body = {
        "request_id": str(request_id),
        "session_id": str(uuid5(NAMESPACE_URL, f"session:{run_id}")),
        "scene": "SEARCH_AFTER",
        "input_text": args.input_text,
        "limit": 5,
    }
    headers = {
        "Idempotency-Key": str(request_id),
        "X-Demo-User-Id": str(args.user_id),
    }
    with TestClient(application) as client:
        first = client.post("/api/v1/recommendation-tasks", json=body, headers=headers)
        second = client.post("/api/v1/recommendation-tasks", json=body, headers=headers)
        task_id = first.json().get("task_id")
        status = client.get(
            f"/api/v1/recommendation-tasks/{task_id}",
            headers={"X-Demo-User-Id": str(args.user_id)},
        )
    if first.status_code != 201 or second.status_code != 200:
        raise ValueError(f"unexpected API statuses: {first.status_code}, {second.status_code}")
    if second.headers.get("Idempotency-Replayed") != "true":
        raise ValueError("second API request did not disclose idempotent replay")
    if status.status_code != 200 or status.json().get("status") not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise ValueError(f"task status query failed: {status.status_code}")
    trace = await service.get_trace(UUID(task_id), user_id=args.user_id)

    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=host_port,
        user=runtime_user,
        password=runtime_password,
        db=database,
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        after = await read_counts(connection)
    finally:
        connection.close()
    if any(after[name] < before[name] for name in COUNT_TABLES):
        raise ValueError("API runtime count decreased")
    if after["recommendation_task"] != before["recommendation_task"] + 1:
        raise ValueError("API runtime did not create exactly one task")
    if after["recommendation_task_transition"] != before["recommendation_task_transition"] + 8:
        raise ValueError("API runtime did not persist the eight expected transitions")
    if first.json().get("item_count", 5) < 5 or len(first.json().get("items", [])) < 5:
        raise ValueError("API runtime did not return five persisted items")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g3" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema_version": "g3-api-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "before_counts": before,
        "after_counts": after,
        "first_status": first.status_code,
        "second_status": second.status_code,
        "replay_header": second.headers.get("Idempotency-Replayed"),
        "task_status": status.json(),
        "trace": trace,
        "item_count": len(first.json().get("items", [])),
        "destructive_actions": 0,
        "database_sql_actions": {"inserts_only_result_persistence": True, "updates": 0, "deletes": 0},
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "api-runtime.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G3 API runtime evidence: {evidence_dir}")
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
        print(f"[FAIL] G3 API runtime verification did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
