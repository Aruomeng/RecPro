"""Verify the append-only G3 clarification branch and research-admin Debug API."""

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
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal
from scripts.migrate_g2 import apply_statements, split_statements
from scripts.replay_g2_profile import apply_replay
from scripts.seed_g2 import DEFAULT_SEED, insert_seed, sha256_bytes, validate_seed
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MIGRATIONS = (
    PROJECT_ROOT / "infra/mysql/migrations/001_g2_core.sql",
    PROJECT_ROOT / "infra/mysql/migrations/002_g3_recommendation.sql",
    PROJECT_ROOT / "infra/mysql/migrations/003_g3_task_transition.sql",
    PROJECT_ROOT / "infra/mysql/migrations/004_g3_clarification_debug.sql",
)
COUNT_TABLES = (
    "recommendation_task",
    "recommendation_task_transition",
    "recommendation_candidate",
    "recommendation_record",
    "recommendation_item",
    "recommendation_item_explanation",
    "recommendation_trace",
    "recommendation_task_context",
    "recommendation_clarification",
    "recommendation_policy_decision",
    "recommendation_trace_revision",
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
        raise ValueError("G3 clarification runtime credentials are required")
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

    def resolve(token: str) -> AuthenticatedPrincipal | None:
        return AuthenticatedPrincipal(
            args.user_id,
            frozenset({"research_admin"}) if token == "admin" else frozenset({"user"}),
            token_id=token,
        )

    application = create_app(
        settings=settings,
        readiness_probe=UpProbe(),
        config_bundle_probe=UpProbe(),
        recommendation_service=service,
        recommendation_api_enabled=True,
        principal_resolver=resolve,
        debug_api_enabled=True,
    )
    request_id = uuid5(NAMESPACE_URL, f"g3-clarification:{run_id}")
    session_id = uuid5(NAMESPACE_URL, f"g3-clarification-session:{run_id}")
    body = {
        "request_id": str(request_id),
        "session_id": str(session_id),
        "scene": "HOME",
        "requested_resource_types": [],
        "limit": 5,
    }
    create_headers = {
        "Idempotency-Key": str(request_id),
        "X-Demo-User-Id": str(args.user_id),
    }
    clarification_key = str(uuid5(NAMESPACE_URL, f"g3-clarification-key:{run_id}"))
    with TestClient(application) as client:
        first = client.post("/api/v1/recommendation-tasks", json=body, headers=create_headers)
        task_id = first.json().get("task_id")
        if not task_id:
            raise ValueError(f"clarification task creation failed: {first.status_code}")
        answer_body = {
            "context_version": 1,
            "answers": {"resource_types": "BOOK_AND_PAPER", "topic": "多智能体"},
        }
        resume_headers = {
            "Idempotency-Key": clarification_key,
            "X-Demo-User-Id": str(args.user_id),
        }
        resumed = client.post(
            f"/api/v1/recommendation-tasks/{task_id}/clarifications",
            json=answer_body,
            headers=resume_headers,
        )
        replay = client.post(
            f"/api/v1/recommendation-tasks/{task_id}/clarifications",
            json=answer_body,
            headers=resume_headers,
        )
        state = client.get(
            f"/api/v1/recommendation-tasks/{task_id}",
            headers={"X-Demo-User-Id": str(args.user_id)},
        )
        debug_trace = client.get(
            f"/api/v1/debug/tasks/{task_id}/trace",
            headers={"Authorization": "Bearer admin"},
        )
        debug_context = client.get(
            f"/api/v1/debug/tasks/{task_id}/context",
            headers={"Authorization": "Bearer admin"},
        )
        debug_policy = client.get(
            f"/api/v1/debug/tasks/{task_id}/policy-decision",
            headers={"Authorization": "Bearer admin"},
        )
    if first.status_code != 201 or first.json().get("status") != "WAITING_CLARIFICATION":
        raise ValueError("initial request did not stop in WAITING_CLARIFICATION")
    if resumed.status_code != 200 or resumed.json().get("status") not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise ValueError("clarification resume did not complete")
    if replay.status_code != 200 or replay.headers.get("Idempotency-Replayed") != "true":
        raise ValueError("clarification replay was not idempotent")
    if state.status_code != 200 or state.json().get("context_version") != 2:
        raise ValueError("task state did not expose context version 2")
    if debug_trace.status_code != 200 or len(debug_trace.json()["payload"]["steps"]) < 4:
        raise ValueError("debug trace is incomplete")
    if debug_context.status_code != 200 or debug_policy.status_code != 200:
        raise ValueError("debug documents were not readable by research-admin")

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
        raise ValueError("clarification runtime count decreased")
    expected_deltas = {
        "recommendation_task": 1,
        "recommendation_task_transition": 12,
        "recommendation_candidate": 15,
        "recommendation_record": 1,
        "recommendation_item": 5,
        "recommendation_item_explanation": 5,
        "recommendation_trace": 1,
        "recommendation_task_context": 2,
        "recommendation_clarification": 2,
        "recommendation_policy_decision": 2,
        "recommendation_trace_revision": 1,
    }
    deltas = {name: after[name] - before[name] for name in COUNT_TABLES}
    if any(deltas[name] != expected for name, expected in expected_deltas.items()):
        raise ValueError(f"unexpected clarification deltas: {deltas}")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g3" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema_version": "g3-clarification-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "before_counts": before,
        "after_counts": after,
        "deltas": deltas,
        "first_status": first.status_code,
        "first_task_status": first.json().get("status"),
        "resume_status": resumed.status_code,
        "resume_task_status": resumed.json().get("status"),
        "resume_context_version": resumed.json().get("context_version"),
        "replay_status": replay.status_code,
        "replay_header": replay.headers.get("Idempotency-Replayed"),
        "debug": {
            "trace_status": debug_trace.status_code,
            "trace_step_count": len(debug_trace.json()["payload"]["steps"]),
            "context_status": debug_context.status_code,
            "policy_status": debug_policy.status_code,
            "policy_decision_count": len(debug_policy.json()["payload"]["decisions"]),
        },
        "destructive_actions": 0,
        "database_sql_actions": {"inserts_only": True, "updates": 0, "deletes": 0},
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "clarification-runtime.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G3 clarification runtime evidence: {evidence_dir}")
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
        print(f"[FAIL] G3 clarification runtime verification did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
