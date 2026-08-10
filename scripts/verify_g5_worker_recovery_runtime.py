"""Verify real MySQL Outbox failure/DEAD handling and restart recovery.

The verifier is intentionally two-phase. ``prepare`` appends two new behavior
facts, drives the first Outbox row through three injected failures, and records
the exact database checkpoint. The operator then restarts only the MySQL
container. ``resume`` proves that the DEAD row and a still-PENDING row survive
the restart, consumes the latter with the real refresh adapter, and writes the
final evidence. No cleanup or data removal is part of either phase.
"""

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

from backend.app.composition import build_profile_outbox_worker, build_research_behavior_service
from backend.app.config import AppSettings
from backend.app.feedback.domain.public import BehaviorAppendCommand
from backend.app.observability.adapters.mysql_transition import MySQLStateTransitionWriter
from backend.app.profile.adapters.refresh_mysql import MySQLProfileRefreshAdapter
from backend.app.profile.application.refresh import ProfileOutboxWorker
from backend.app.shared_kernel.contracts.enums import BehaviorEventType
from scripts.g5_runtime_permissions import grant_g5_runtime_projection
from scripts.replay_g2_profile import apply_replay
from scripts.seed_g2 import DEFAULT_SEED, insert_seed, sha256_bytes, validate_seed
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g5_feedback_runtime import (
    G5_TABLES,
    MIGRATIONS,
    PROTECTED_TABLES,
    apply_forward_migration,
    connect,
    read_counts,
    read_outbox_statuses,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


class InjectedRefreshFailureAdapter(MySQLProfileRefreshAdapter):
    """Use the real claim/mark SQL but fail before any profile projection write."""

    def __init__(self) -> None:
        super().__init__(transition_sink=MySQLStateTransitionWriter())
        self.failure_calls = 0

    async def apply_claim(
        self,
        connection: Any,
        work: dict[str, object],
        *,
        formula_version: str,
    ):
        self.failure_calls += 1
        raise RuntimeError("G5_INJECTED_REFRESH_FAILURE")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def evidence_dir(run_id: str) -> Path:
    return PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id


async def read_resource_id(connection: Any) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT id FROM resource_catalog ORDER BY id LIMIT 1")
        row = await cursor.fetchone()
    if row is None:
        raise ValueError("resource catalog has no target for worker recovery verification")
    return int(row[0])


async def read_outbox_row(connection: Any, *, source_event_id: int) -> dict[str, object] | None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT id, source_event_id, source_type, status, attempts, next_retry_at, "
            "locked_at, locked_by, last_error "
            "FROM profile_update_outbox WHERE source_event_id = %s AND source_type = 'BEHAVIOR'",
            (source_event_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "outbox_id": int(row[0]),
        "source_event_id": int(row[1]),
        "source_type": str(row[2]),
        "status": str(row[3]),
        "attempts": int(row[4]),
        "next_retry_at": row[5].isoformat() if row[5] is not None else None,
        "locked_at": row[6].isoformat() if row[6] is not None else None,
        "locked_by": str(row[7]) if row[7] is not None else None,
        "last_error": str(row[8]) if row[8] is not None else None,
    }


async def expedite_retry(
    values: dict[str, str],
    *,
    migration_user: str,
    migration_password: str,
    outbox_id: int,
) -> None:
    connection = await connect(
        values,
        user=migration_user,
        password=migration_password,
        autocommit=False,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE profile_update_outbox SET next_retry_at = NULL, updated_at = %s "
                "WHERE id = %s AND status = 'PENDING'",
                (datetime.now(UTC).replace(tzinfo=None), outbox_id),
            )
        await connection.commit()
    except BaseException:
        await connection.rollback()
        raise
    finally:
        connection.close()


async def prepare_environment(values: dict[str, str], *, user_id: int) -> None:
    migration_user = values["RECPRO_MYSQL_MIGRATION_USER"]
    migration_password = values["RECPRO_MYSQL_MIGRATION_PASSWORD"]
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
        user_id=user_id,
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
        runtime_user=values["RECPRO_MYSQL_USER"],
    )


def build_settings(values: dict[str, str]) -> AppSettings:
    return AppSettings(
        app_env="demo",
        mysql_host="127.0.0.1",
        mysql_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        mysql_database=values["RECPRO_MYSQL_DATABASE"],
        mysql_user=values["RECPRO_MYSQL_USER"],
        mysql_password=values["RECPRO_MYSQL_PASSWORD"],
        mysql_connect_timeout_seconds=10,
    )


async def append_behavior_pair(
    values: dict[str, str],
    *,
    run_id: str,
    user_id: int,
    resource_id: int,
) -> tuple[dict[str, object], dict[str, object]]:
    service = build_research_behavior_service(build_settings(values))
    occurred_at = datetime.now(UTC)
    results: list[dict[str, object]] = []
    for label in ("dead", "recovery"):
        event_uuid = uuid5(NAMESPACE_URL, f"g5-worker-{label}:{run_id}")
        command = BehaviorAppendCommand(
            event_uuid=event_uuid,
            user_id=user_id,
            session_id=uuid5(NAMESPACE_URL, f"g5-worker-session:{label}:{run_id}"),
            event_type=BehaviorEventType.VIEW_RESOURCE,
            occurred_at=occurred_at,
            resource_id=resource_id,
            enqueue_profile_update=True,
        )
        receipt = await service.append(command)
        if receipt.replayed or receipt.outbox_id is None:
            raise ValueError(f"worker {label} fixture unexpectedly replayed")
        results.append(
            {
                "label": label,
                "event_uuid": str(event_uuid),
                "event_id": receipt.event_id,
                "outbox_id": receipt.outbox_id,
            }
        )
    return results[0], results[1]


async def prepare(args: argparse.Namespace, values: dict[str, str]) -> int:
    run_id = validate_run_id(args.run_id)
    target_dir = evidence_dir(run_id)
    target_dir.mkdir(parents=True, exist_ok=False)
    await prepare_environment(values, user_id=args.user_id)
    runtime_user = values["RECPRO_MYSQL_USER"]
    migration_user = values["RECPRO_MYSQL_MIGRATION_USER"]
    migration_password = values["RECPRO_MYSQL_MIGRATION_PASSWORD"]
    baseline_connection = await connect(
        values,
        user=runtime_user,
        password=values["RECPRO_MYSQL_PASSWORD"],
        autocommit=True,
    )
    try:
        baseline = await read_counts(baseline_connection, G5_TABLES + PROTECTED_TABLES)
        baseline_statuses = await read_outbox_statuses(baseline_connection)
        resource_id = await read_resource_id(baseline_connection)
    finally:
        baseline_connection.close()
    if baseline_statuses.get("PENDING", 0) or baseline_statuses.get("PROCESSING", 0):
        raise ValueError(f"baseline contains live Outbox work: {baseline_statuses}")

    dead_fixture, recovery_fixture = await append_behavior_pair(
        values,
        run_id=run_id,
        user_id=args.user_id,
        resource_id=resource_id,
    )
    after_append_connection = await connect(
        values,
        user=runtime_user,
        password=values["RECPRO_MYSQL_PASSWORD"],
        autocommit=True,
    )
    try:
        after_append = await read_counts(after_append_connection, G5_TABLES + PROTECTED_TABLES)
        dead_row = await read_outbox_row(
            after_append_connection, source_event_id=int(dead_fixture["event_id"])
        )
        recovery_row = await read_outbox_row(
            after_append_connection, source_event_id=int(recovery_fixture["event_id"])
        )
    finally:
        after_append_connection.close()
    if dead_row is None or recovery_row is None:
        raise ValueError("worker fixtures did not create both Outbox rows")
    if dead_row["status"] != "PENDING" or recovery_row["status"] != "PENDING":
        raise ValueError("worker fixtures are not initially PENDING")
    if int(dead_row["outbox_id"]) >= int(recovery_row["outbox_id"]):
        raise ValueError("failure fixture must be claimed before recovery fixture")
    if after_append["user_behavior_event"] != baseline["user_behavior_event"] + 2:
        raise ValueError("worker fixture behavior fact delta mismatch")
    if after_append["profile_update_outbox"] != baseline["profile_update_outbox"] + 2:
        raise ValueError("worker fixture Outbox delta mismatch")
    for table in PROTECTED_TABLES:
        if after_append[table] != baseline[table]:
            raise ValueError(f"worker fixture changed protected table {table}")

    async def failure_connection_factory() -> Any:
        return await connect(
            values,
            user=migration_user,
            password=migration_password,
            autocommit=False,
        )

    failing_adapter = InjectedRefreshFailureAdapter()
    failing_worker = ProfileOutboxWorker(
        connection_factory=failure_connection_factory,
        refresh_port=failing_adapter,
        worker_id=f"g5-dead-{run_id}",
        max_attempts=3,
    )
    attempts: list[dict[str, object]] = []
    for failure_no in range(1, 4):
        receipts = await failing_worker.run_once(limit=1)
        if receipts:
            raise ValueError("injected failure worker unexpectedly produced a receipt")
        row_connection = await connect(
            values,
            user=runtime_user,
            password=values["RECPRO_MYSQL_PASSWORD"],
            autocommit=True,
        )
        try:
            row = await read_outbox_row(
                row_connection, source_event_id=int(dead_fixture["event_id"])
            )
        finally:
            row_connection.close()
        if row is None:
            raise ValueError("failure fixture disappeared after injected failure")
        attempts.append({"failure_no": failure_no, "row": row})
        if failure_no < 3:
            await expedite_retry(
                values,
                migration_user=migration_user,
                migration_password=migration_password,
                outbox_id=int(row["outbox_id"]),
            )
    after_failure_connection = await connect(
        values,
        user=runtime_user,
        password=values["RECPRO_MYSQL_PASSWORD"],
        autocommit=True,
    )
    try:
        after_failure = await read_counts(after_failure_connection, G5_TABLES + PROTECTED_TABLES)
        dead_row = await read_outbox_row(
            after_failure_connection, source_event_id=int(dead_fixture["event_id"])
        )
        recovery_row = await read_outbox_row(
            after_failure_connection, source_event_id=int(recovery_fixture["event_id"])
        )
    finally:
        after_failure_connection.close()
    if dead_row is None or dead_row["status"] != "DEAD" or dead_row["attempts"] != 3:
        raise ValueError(f"failure fixture did not reach DEAD: {dead_row}")
    if dead_row["last_error"] != "RuntimeError":
        raise ValueError(f"unexpected DEAD error code: {dead_row}")
    if recovery_row is None or recovery_row["status"] != "PENDING":
        raise ValueError(f"recovery fixture was not left pending: {recovery_row}")
    for table in G5_TABLES:
        if table == "profile_update_outbox":
            if after_failure[table] != after_append[table]:
                raise ValueError("failure worker changed Outbox fact count")
        elif after_failure[table] != after_append[table]:
            raise ValueError(f"failure worker changed profile/fact table {table}")
    for table in PROTECTED_TABLES:
        if after_failure[table] != after_append[table]:
            raise ValueError(f"failure worker changed protected table {table}")

    checkpoint = {
        "schema_version": "g5-worker-recovery-checkpoint-v1",
        "run_id": run_id,
        "status": "PREPARED_FOR_MYSQL_RESTART",
        "user_id": args.user_id,
        "resource_id": resource_id,
        "dead_fixture": dead_fixture,
        "recovery_fixture": recovery_fixture,
        "baseline_counts": baseline,
        "after_append_counts": after_append,
        "after_failure_counts": after_failure,
        "baseline_outbox_statuses": baseline_statuses,
        "failure_attempts": attempts,
        "dead_row": dead_row,
        "recovery_row": recovery_row,
        "database_sql_actions": {
            "fact_inserts": "2 behavior + 2 Outbox rows",
            "controlled_updates": "3 claim + 3 failure-status updates plus 2 retry schedule test updates",
            "deletes": 0,
            "ddl_drops_or_alters": 0,
        },
        "destructive_actions": 0,
        "prepared_at": datetime.now(UTC).isoformat(),
    }
    (target_dir / "prepare.json").write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G5 Worker recovery prepare checkpoint: {target_dir / 'prepare.json'}")
    return 0


async def resume(args: argparse.Namespace, values: dict[str, str]) -> int:
    run_id = validate_run_id(args.run_id)
    target_dir = evidence_dir(run_id)
    checkpoint_path = target_dir / "prepare.json"
    if not checkpoint_path.is_file():
        raise ValueError("prepare checkpoint is required before resume")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("run_id") != run_id:
        raise ValueError("prepare checkpoint run id does not match resume run id")
    if checkpoint.get("status") != "PREPARED_FOR_MYSQL_RESTART":
        raise ValueError("prepare checkpoint is not in the expected restart state")
    runtime_user = values["RECPRO_MYSQL_USER"]
    connection = await connect(
        values,
        user=runtime_user,
        password=values["RECPRO_MYSQL_PASSWORD"],
        autocommit=True,
    )
    try:
        after_restart = await read_counts(connection, G5_TABLES + PROTECTED_TABLES)
        statuses_after_restart = await read_outbox_statuses(connection)
        dead_row = await read_outbox_row(
            connection, source_event_id=int(checkpoint["dead_fixture"]["event_id"])
        )
        recovery_row = await read_outbox_row(
            connection, source_event_id=int(checkpoint["recovery_fixture"]["event_id"])
        )
    finally:
        connection.close()
    if after_restart != checkpoint["after_failure_counts"]:
        raise ValueError("database counts changed across MySQL restart")
    if dead_row is None or dead_row["status"] != "DEAD" or dead_row["attempts"] != 3:
        raise ValueError(f"DEAD row was not recoverable after restart: {dead_row}")
    if recovery_row is None or recovery_row["status"] != "PENDING":
        raise ValueError(f"PENDING row was not recoverable after restart: {recovery_row}")

    async def worker_connection_factory() -> Any:
        return await connect(
            values,
            user=values["RECPRO_MYSQL_MIGRATION_USER"],
            password=values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
            autocommit=False,
        )

    worker = build_profile_outbox_worker(
        build_settings(values),
        connection_factory=worker_connection_factory,
        worker_id=f"g5-recovery-{run_id}",
        formula_version="profile-g2-v1",
    )
    receipts = await worker.run_once(limit=1)
    replay_receipts = await worker.run_once(limit=1)
    recovery_event_id = int(checkpoint["recovery_fixture"]["event_id"])
    if len(receipts) != 1 or receipts[0].source_event_id != recovery_event_id:
        raise ValueError("healthy worker did not consume the recovered pending row")
    if replay_receipts:
        raise ValueError("healthy worker reclaimed a completed row after restart")

    after_worker_connection = await connect(
        values,
        user=runtime_user,
        password=values["RECPRO_MYSQL_PASSWORD"],
        autocommit=True,
    )
    try:
        after_worker = await read_counts(after_worker_connection, G5_TABLES + PROTECTED_TABLES)
        statuses_after_worker = await read_outbox_statuses(after_worker_connection)
        dead_row = await read_outbox_row(
            after_worker_connection, source_event_id=int(checkpoint["dead_fixture"]["event_id"])
        )
        recovery_row = await read_outbox_row(
            after_worker_connection, source_event_id=recovery_event_id
        )
    finally:
        after_worker_connection.close()
    if dead_row is None or dead_row["status"] != "DEAD" or dead_row["attempts"] != 3:
        raise ValueError("DEAD row changed during healthy recovery")
    if recovery_row is None or recovery_row["status"] != "DONE":
        raise ValueError(f"recovered row did not reach DONE: {recovery_row}")
    if after_worker["profile_update_outbox"] != after_restart["profile_update_outbox"]:
        raise ValueError("worker changed the append-only Outbox row count")
    if after_worker["profile_replay_run"] <= after_restart["profile_replay_run"]:
        raise ValueError("recovered worker did not persist a replay run")
    if after_worker["profile_change_log"] <= after_restart["profile_change_log"]:
        raise ValueError("recovered worker did not persist profile change facts")
    for table in PROTECTED_TABLES:
        if after_worker[table] != after_restart[table]:
            raise ValueError(f"recovery worker changed protected table {table}")

    evidence = {
        "schema_version": "g5-worker-recovery-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "user_id": checkpoint["user_id"],
        "resource_id": checkpoint["resource_id"],
        "dead_fixture": checkpoint["dead_fixture"],
        "recovery_fixture": checkpoint["recovery_fixture"],
        "checkpoint": checkpoint,
        "after_restart_counts": after_restart,
        "after_worker_counts": after_worker,
        "outbox_statuses_after_restart": statuses_after_restart,
        "outbox_statuses_after_worker": statuses_after_worker,
        "dead_row_after_restart": dead_row,
        "recovery_row_after_worker": recovery_row,
        "healthy_worker_receipt_count": len(receipts),
        "healthy_worker_replay_receipt_count": len(replay_receipts),
        "database_sql_actions": {
            "fact_inserts": "prepare checkpoint: 2 behavior + 2 Outbox rows",
            "controlled_updates": "failure claim/status, retry schedule, restart recovery claim/apply/done",
            "deletes": 0,
            "ddl_drops_or_alters": 0,
        },
        "destructive_actions": 0,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (target_dir / "runtime.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G5 Worker recovery runtime evidence: {target_dir}")
    return 0


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    if not values.get("RECPRO_MYSQL_ROOT_PASSWORD"):
        raise ValueError("G5 Worker recovery requires the operator root password for the scoped grant")
    if args.phase == "prepare":
        return await prepare(args, values)
    return await resume(args, values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase", choices=("prepare", "resume"), required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G5 Worker recovery verification did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
