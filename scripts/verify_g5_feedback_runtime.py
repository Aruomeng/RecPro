"""Verify the G5 append-only feedback and profile-outbox vertical slice."""

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

from backend.app.composition import build_profile_outbox_worker, build_research_feedback_service
from backend.app.config import AppSettings
from backend.app.feedback.domain.public import FeedbackCommand, ImpressionCommand
from backend.app.recommendation.adapters.mysql import MySQLRecommendationTaskService
from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.recommendation.domain.public import RecommendationTaskCommand
from backend.app.shared_kernel.contracts.enums import FeedbackType, NegativeReasonCode
from scripts.migrate_g2 import apply_statements, split_statements
from scripts.g5_runtime_permissions import grant_g5_runtime_projection
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
        "006_g5_feedback_state.sql",
        "007_g5_state_transition_audit.sql",
    )
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
PROTECTED_TABLES = (
    "resource_catalog",
    "resource_tag",
    "tag_dictionary",
    "user_declared_profile",
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


async def connect(
    values: dict[str, str], *, user: str, password: str, autocommit: bool
) -> Any:
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=user,
        password=password,
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


async def read_outbox_statuses(connection: Any) -> dict[str, int]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT status, COUNT(*) FROM profile_update_outbox GROUP BY status ORDER BY status"
        )
        return {str(row[0]): int(row[1]) for row in await cursor.fetchall()}


def task_command(run_id: str, *, user_id: int) -> RecommendationTaskCommand:
    return RecommendationTaskCommand(
        request_id=uuid5(NAMESPACE_URL, f"g5-feedback-request:{run_id}"),
        session_id=uuid5(NAMESPACE_URL, f"g5-feedback-session:{run_id}"),
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


async def read_target_tag(connection: Any, *, resource_id: int) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT tag_id FROM resource_tag WHERE resource_id = %s ORDER BY tag_id LIMIT 1",
            (resource_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        raise ValueError("feedback target resource has no tag evidence")
    return int(row[0])


async def read_profile_facts(
    connection: Any, *, user_id: int, tag_id: int
) -> dict[str, object]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT profile_version, profile_confidence, topic_focus_strength "
            "FROM user_profile WHERE user_id = %s",
            (user_id,),
        )
        profile = await cursor.fetchone()
        await cursor.execute(
            "SELECT negative_weight, source_count, profile_version "
            "FROM user_negative_preference "
            "WHERE user_id = %s AND tag_id = %s AND reason_code = 'TOPIC_NOT_INTERESTED'",
            (user_id, tag_id),
        )
        negative = await cursor.fetchone()
    return {
        "profile_version": int(profile[0]) if profile is not None else 0,
        "profile_confidence": float(profile[1]) if profile is not None else 0.0,
        "topic_focus_strength": float(profile[2]) if profile is not None else 0.0,
        "negative_weight": float(negative[0]) if negative is not None else 0.0,
        "negative_source_count": int(negative[1]) if negative is not None else 0,
        "negative_profile_version": int(negative[2]) if negative is not None else 0,
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
        raise ValueError("G5 runtime credentials are required")
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
    recommendation_command = task_command(run_id, user_id=args.user_id)
    recommendation = await g3_service.create_task(
        recommendation_command, idempotency_key=str(recommendation_command.request_id)
    )
    items = list(recommendation.payload.get("items", ()))
    if not items:
        raise ValueError("G5 runtime recommendation produced no item to expose")
    item_id = int(items[0]["item_id"])
    resource_id = int(items[0]["resource"]["resource_id"])

    baseline_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        baseline = await read_counts(baseline_connection, G5_TABLES + PROTECTED_TABLES)
        target_tag_id = await read_target_tag(baseline_connection, resource_id=resource_id)
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
    feedback_service = build_research_feedback_service(settings)
    impression_uuid = uuid5(NAMESPACE_URL, f"g5-impression:{run_id}")
    feedback_uuid = uuid5(NAMESPACE_URL, f"g5-feedback:{run_id}")
    rendered_at = datetime(2025, 12, 30, 12, 0, tzinfo=UTC)
    impression_command = ImpressionCommand(
        impression_uuid=impression_uuid,
        recommendation_item_id=item_id,
        user_id=args.user_id,
        position=1,
        rendered_at=rendered_at,
        visible_started_at=rendered_at,
        visible_ms=1500,
        max_visible_ratio=0.8,
    )
    first_impression = await feedback_service.record_impression(impression_command)
    replay_impression = await feedback_service.record_impression(impression_command)
    if replay_impression.replayed is not True or first_impression.replayed is True:
        raise ValueError("impression UUID replay contract failed")

    feedback_command = FeedbackCommand(
        feedback_uuid=feedback_uuid,
        recommendation_item_id=item_id,
        user_id=args.user_id,
        feedback_type=FeedbackType.NOT_INTERESTED,
        occurred_at=datetime(2025, 12, 30, 12, 1, tzinfo=UTC),
        impression_uuid=impression_uuid,
        reason_code=NegativeReasonCode.TOPIC_NOT_INTERESTED,
    )
    first_feedback = await feedback_service.record_feedback(feedback_command)
    replay_feedback = await feedback_service.record_feedback(feedback_command)
    if replay_feedback.replayed is not True or first_feedback.replayed is True:
        raise ValueError("feedback UUID replay contract failed")
    if first_feedback.outbox_id is None:
        raise ValueError("feedback did not enqueue a profile refresh")

    after_feedback_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        after_feedback = await read_counts(
            after_feedback_connection, G5_TABLES + PROTECTED_TABLES
        )
        after_feedback_statuses = await read_outbox_statuses(after_feedback_connection)
    finally:
        after_feedback_connection.close()
    expected_feedback_delta = {
        "recommendation_impression": 1,
        "recommendation_feedback": 1,
        "user_behavior_event": 2,
        "profile_update_outbox": 1,
        "user_resource_state": 1,
    }
    for table, delta in expected_feedback_delta.items():
        if after_feedback[table] != baseline[table] + delta:
            raise ValueError(f"G5 feedback delta mismatch for {table}")
    for table in PROTECTED_TABLES:
        if after_feedback[table] != baseline[table]:
            raise ValueError(f"feedback path changed protected table {table}")

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
        worker_id=f"g5-{run_id}",
        formula_version="profile-g2-v1",
    )
    worker_receipts = await worker.run_once(limit=100)
    replay_worker_receipts = await worker.run_once(limit=100)
    if replay_worker_receipts:
        raise ValueError("profile outbox worker was not idempotent after DONE claims")
    if not any(receipt.source_event_id == first_feedback.behavior_event_id for receipt in worker_receipts):
        raise ValueError("worker did not consume the feedback profile outbox item")

    after_worker_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        after_worker = await read_counts(after_worker_connection, G5_TABLES + PROTECTED_TABLES)
        after_worker_statuses = await read_outbox_statuses(after_worker_connection)
        profile_facts = await read_profile_facts(
            after_worker_connection, user_id=args.user_id, tag_id=target_tag_id
        )
    finally:
        after_worker_connection.close()
    if after_worker["profile_update_outbox"] != after_feedback["profile_update_outbox"]:
        raise ValueError("worker changed the append-only outbox row count")
    if after_worker["user_behavior_event"] != after_feedback["user_behavior_event"]:
        raise ValueError("worker changed behavior fact count")
    if after_worker["recommendation_feedback"] != after_feedback["recommendation_feedback"]:
        raise ValueError("worker changed feedback fact count")
    if after_worker["recommendation_impression"] != after_feedback["recommendation_impression"]:
        raise ValueError("worker changed impression fact count")
    if after_worker["profile_replay_run"] <= baseline["profile_replay_run"]:
        raise ValueError("worker did not persist an as-of replay run")
    if after_worker["profile_change_log"] <= baseline["profile_change_log"]:
        raise ValueError("worker did not persist profile change facts")
    if after_worker_statuses.get("PENDING", 0) or after_worker_statuses.get("PROCESSING", 0):
        raise ValueError(f"profile outbox still has live work: {after_worker_statuses}")
    if profile_facts["negative_weight"] <= 0 or profile_facts["negative_source_count"] <= 0:
        raise ValueError("as-of profile replay did not materialize negative feedback")
    if profile_facts["profile_version"] <= 0:
        raise ValueError("as-of profile replay did not materialize a current profile")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence = {
        "schema_version": "g5-feedback-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "user_id": args.user_id,
        "recommendation_item_id": item_id,
        "resource_id": resource_id,
        "target_tag_id": target_tag_id,
        "impression_uuid": str(impression_uuid),
        "feedback_uuid": str(feedback_uuid),
        "feedback_behavior_event_id": first_feedback.behavior_event_id,
        "feedback_outbox_id": first_feedback.outbox_id,
        "before_counts": baseline,
        "after_feedback_counts": after_feedback,
        "after_worker_counts": after_worker,
        "expected_feedback_delta": expected_feedback_delta,
        "outbox_statuses_before_worker": after_feedback_statuses,
        "outbox_statuses_after_worker": after_worker_statuses,
        "worker_receipt_count": len(worker_receipts),
        "profile_facts": profile_facts,
        "database_sql_actions": {
            "fact_inserts": 4,
            "controlled_projection_updates": "outbox claim/status and current profile projection only",
            "deletes": 0,
            "ddl_drops_or_alters": 0,
        },
        "destructive_actions": 0,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "g5-runtime.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G5 feedback runtime evidence: {evidence_dir}")
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
        print(f"[FAIL] G5 feedback runtime verification did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
