"""Verify opt-in G5 interaction HTTP routes against the real MySQL fact layer."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

import asyncmy
from fastapi.testclient import TestClient

from backend.app.composition import (
    build_profile_outbox_worker,
    build_research_behavior_service,
    build_research_feedback_service,
)
from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.recommendation.adapters.mysql import MySQLRecommendationTaskService
from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from scripts.replay_g2_profile import apply_replay
from scripts.seed_g2 import DEFAULT_SEED, insert_seed, sha256_bytes, validate_seed
from scripts.g5_runtime_permissions import grant_g5_runtime_projection
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g5_feedback_runtime import (
    G5_TABLES,
    MIGRATIONS,
    PROTECTED_TABLES,
    apply_forward_migration,
    connect,
    read_counts,
    read_outbox_statuses,
    task_command,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


async def read_resource_state(
    connection: Any,
    *,
    user_id: int,
    resource_id: int,
    state_type: str,
) -> dict[str, object] | None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT state_type, source_event_id, state_version, suppress_until "
            "FROM user_resource_state "
            "WHERE user_id = %s AND resource_id = %s AND state_type = %s",
            (user_id, resource_id, state_type),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "state_type": str(row[0]),
        "source_event_id": int(row[1]),
        "state_version": int(row[2]),
        "suppress_until": row[3].isoformat() if row[3] is not None else None,
    }


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
        raise ValueError("G5 HTTP runtime credentials are required")
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
    await grant_g5_runtime_projection(
        host_port=host_port,
        database=database,
        root_password=values["RECPRO_MYSQL_ROOT_PASSWORD"],
        runtime_user=runtime_user,
    )

    recommendation_service = MySQLRecommendationTaskService(
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
    recommendation = await recommendation_service.create_task(
        task_command(run_id, user_id=args.user_id),
        idempotency_key=str(task_command(run_id, user_id=args.user_id).request_id),
    )
    items = list(recommendation.payload.get("items", ()))
    if not items:
        raise ValueError("G5 HTTP runtime recommendation produced no item")
    item_id = int(items[0]["item_id"])
    resource_id = int(items[0]["resource"]["resource_id"])

    before_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        before = await read_counts(before_connection, G5_TABLES + PROTECTED_TABLES)
        before_state = await read_resource_state(
            before_connection,
            user_id=args.user_id,
            resource_id=resource_id,
            state_type="HIDDEN",
        )
    finally:
        before_connection.close()

    settings = AppSettings(
        app_env="demo",
        mysql_host="127.0.0.1",
        mysql_port=host_port,
        mysql_database=database,
        mysql_user=runtime_user,
        mysql_password=runtime_password,
        mysql_connect_timeout_seconds=10,
    )
    feedback_service = build_research_feedback_service(settings)
    behavior_service = build_research_behavior_service(settings)
    application = create_app(
        settings=settings,
        readiness_probe=UpProbe(),
        config_bundle_probe=UpProbe(),
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        feedback_api_enabled=True,
    )
    impression_uuid = uuid5(NAMESPACE_URL, f"g5-http-impression:{run_id}")
    feedback_uuid = uuid5(NAMESPACE_URL, f"g5-http-feedback:{run_id}")
    behavior_uuid = uuid5(NAMESPACE_URL, f"g5-http-behavior:{run_id}")
    impression_body = {
        "impressions": [
            {
                "impression_uuid": str(impression_uuid),
                "recommendation_item_id": item_id,
                "position": 1,
                "rendered_at": "2025-12-30T12:00:00Z",
                "visible_started_at": "2025-12-30T12:00:00Z",
                "visible_ms": 1500,
                "max_visible_ratio": 0.8,
            }
        ]
    }
    with TestClient(application) as client:
        impression_first = client.post(
            "/api/v1/recommendation-impressions/batch",
            json=impression_body,
            headers={"Idempotency-Key": f"batch-{run_id}", "X-Demo-User-Id": str(args.user_id)},
        )
        impression_replay = client.post(
            "/api/v1/recommendation-impressions/batch",
            json=impression_body,
            headers={"Idempotency-Key": f"batch-{run_id}", "X-Demo-User-Id": str(args.user_id)},
        )
        feedback_first = client.post(
            f"/api/v1/recommendation-items/{item_id}/feedback",
            json={
                "feedback_uuid": str(feedback_uuid),
                "impression_uuid": str(impression_uuid),
                "feedback_type": "NOT_INTERESTED",
                "reason_code": "TOPIC_NOT_INTERESTED",
            },
            headers={"Idempotency-Key": str(feedback_uuid), "X-Demo-User-Id": str(args.user_id)},
        )
        feedback_replay = client.post(
            f"/api/v1/recommendation-items/{item_id}/feedback",
            json={
                "feedback_uuid": str(feedback_uuid),
                "impression_uuid": str(impression_uuid),
                "feedback_type": "NOT_INTERESTED",
                "reason_code": "TOPIC_NOT_INTERESTED",
            },
            headers={"Idempotency-Key": str(feedback_uuid), "X-Demo-User-Id": str(args.user_id)},
        )
        behavior_response = client.post(
            "/api/v1/behavior-events",
            json={
                "event_uuid": str(behavior_uuid),
                "session_id": str(uuid4()),
                "event_type": "CLICK_RECOMMENDATION",
                "resource_id": resource_id,
                "recommendation_item_id": item_id,
                "impression_uuid": str(impression_uuid),
                "occurred_at": "2025-12-30T12:02:00Z",
            },
            headers={"Idempotency-Key": str(behavior_uuid), "X-Demo-User-Id": str(args.user_id)},
        )
    if impression_first.status_code != 200 or impression_first.json()["accepted_count"] != 1:
        raise ValueError("HTTP impression first-write contract failed")
    if impression_replay.status_code != 200 or impression_replay.json()["replayed_count"] != 1:
        raise ValueError("HTTP impression replay contract failed")
    if feedback_first.status_code != 202 or feedback_first.json()["status"] != "ACCEPTED":
        raise ValueError("HTTP feedback pending contract failed")
    if feedback_replay.status_code != 200 or feedback_replay.json()["status"] != "REPLAYED":
        raise ValueError("HTTP feedback replay contract failed")
    if behavior_response.status_code != 202:
        raise ValueError(f"HTTP behavior contract failed: {behavior_response.text}")
    feedback_event_id = int(feedback_first.json()["behavior_event_id"])
    behavior_event_id = int(behavior_response.json()["event_id"])

    after_http_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        after_http = await read_counts(after_http_connection, G5_TABLES + PROTECTED_TABLES)
        after_state = await read_resource_state(
            after_http_connection,
            user_id=args.user_id,
            resource_id=resource_id,
            state_type="HIDDEN",
        )
    finally:
        after_http_connection.close()
    expected_delta = {
        "recommendation_impression": 1,
        "recommendation_feedback": 1,
        "user_behavior_event": 3,
        "profile_update_outbox": 2,
        "user_resource_state": 1,
    }
    for table, delta in expected_delta.items():
        observed_delta = after_http[table] - before[table]
        if table == "user_resource_state":
            # The first feedback for a resource inserts its current projection;
            # a later feedback updates that same row under the column allowlist.
            if observed_delta not in (0, 1):
                raise ValueError(f"HTTP fact delta mismatch for {table}")
            continue
        if observed_delta != delta:
            raise ValueError(f"HTTP fact delta mismatch for {table}")
    if after_state is None or after_state["source_event_id"] != feedback_event_id:
        raise ValueError("HTTP feedback did not update the HIDDEN resource projection")
    for table in PROTECTED_TABLES:
        if after_http[table] != before[table]:
            raise ValueError(f"HTTP interaction changed protected table {table}")

    async def worker_connection_factory() -> Any:
        return await connect(
            values,
            user=migration_user,
            password=migration_password,
            autocommit=False,
        )

    worker = build_profile_outbox_worker(
        settings,
        connection_factory=worker_connection_factory,
        worker_id=f"g5-http-{run_id}",
    )
    receipts = await worker.run_once(limit=100)
    replay_receipts = await worker.run_once(limit=100)
    if replay_receipts:
        raise ValueError("HTTP-created outbox items were reclaimed after DONE")
    if not {feedback_event_id, behavior_event_id}.issubset(
        {receipt.source_event_id for receipt in receipts}
    ):
        raise ValueError("worker did not consume both HTTP-created outbox items")

    after_worker_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        after_worker = await read_counts(after_worker_connection, G5_TABLES + PROTECTED_TABLES)
        statuses = await read_outbox_statuses(after_worker_connection)
    finally:
        after_worker_connection.close()
    if after_worker["profile_update_outbox"] != after_http["profile_update_outbox"]:
        raise ValueError("worker changed outbox fact count")
    if statuses.get("PENDING", 0) or statuses.get("PROCESSING", 0):
        raise ValueError(f"worker left live outbox work: {statuses}")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence = {
        "schema_version": "g5-feedback-http-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "user_id": args.user_id,
        "recommendation_item_id": item_id,
        "resource_id": resource_id,
        "impression_uuid": str(impression_uuid),
        "feedback_uuid": str(feedback_uuid),
        "behavior_uuid": str(behavior_uuid),
        "feedback_behavior_event_id": feedback_event_id,
        "direct_behavior_event_id": behavior_event_id,
        "before_counts": before,
        "after_http_counts": after_http,
        "after_worker_counts": after_worker,
        "expected_http_delta": expected_delta,
        "observed_http_delta": {
            table: after_http[table] - before[table] for table in expected_delta
        },
        "resource_state_before": before_state,
        "resource_state_after_http": after_state,
        "worker_receipt_count": len(receipts),
        "outbox_statuses_after_worker": statuses,
        "database_sql_actions": {
            "fact_inserts": "impression + feedback + 3 behavior + 2 outbox rows",
            "controlled_projection_updates": "user_resource_state plus outbox claim/status and profile projection",
            "deletes": 0,
            "ddl_drops_or_alters": 0,
        },
        "destructive_actions": 0,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "http-runtime.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G5 HTTP runtime evidence: {evidence_dir}")
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
        print(f"[FAIL] G5 HTTP runtime verification did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
