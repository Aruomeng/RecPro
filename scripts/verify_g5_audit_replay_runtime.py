"""Verify G5 state-transition auditing and read-only historical profile replay."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

import asyncmy

from backend.app.composition import build_profile_outbox_worker, build_research_behavior_service
from backend.app.config import AppSettings
from backend.app.feedback.domain.public import BehaviorAppendCommand
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
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
AUDIT_TABLE = "domain_state_transition"


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
        raise ValueError("audit replay verifier requires a seeded resource")
    return int(row[0])


async def read_transition_rows(
    connection: Any,
    *,
    aggregate_ids: tuple[str, ...],
) -> list[dict[str, object]]:
    if not aggregate_ids:
        return []
    placeholders = ",".join("%s" for _ in aggregate_ids)
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT aggregate_type, aggregate_id, transition_type, from_state, to_state, "
            "version_before, version_after, causation_ref, actor_type "
            f"FROM {AUDIT_TABLE} WHERE aggregate_id IN ({placeholders}) ORDER BY id",
            aggregate_ids,
        )
        rows = await cursor.fetchall()
    return [
        {
            "aggregate_type": str(row[0]),
            "aggregate_id": str(row[1]),
            "transition_type": str(row[2]),
            "from_state": str(row[3]) if row[3] is not None else None,
            "to_state": str(row[4]),
            "version_before": int(row[5]) if row[5] is not None else None,
            "version_after": int(row[6]),
            "causation_ref": str(row[7]),
            "actor_type": str(row[8]),
        }
        for row in rows
    ]


async def append_fixture_pair(
    values: dict[str, str],
    *,
    run_id: str,
    user_id: int,
    resource_id: int,
) -> tuple[dict[str, object], dict[str, object]]:
    service = build_research_behavior_service(
        AppSettings(
            app_env="demo",
            mysql_host="127.0.0.1",
            mysql_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
            mysql_database=values["RECPRO_MYSQL_DATABASE"],
            mysql_user=values["RECPRO_MYSQL_USER"],
            mysql_password=values["RECPRO_MYSQL_PASSWORD"],
            mysql_connect_timeout_seconds=10,
        )
    )
    fixtures: list[dict[str, object]] = []
    for label, occurred_at in (
        ("early", datetime(2030, 1, 10, 12, 0, tzinfo=UTC)),
        ("late", datetime(2030, 1, 20, 12, 0, tzinfo=UTC)),
    ):
        event_uuid = uuid5(NAMESPACE_URL, f"g5-audit-replay:{label}:{run_id}")
        receipt = await service.append(
            BehaviorAppendCommand(
                event_uuid=event_uuid,
                user_id=user_id,
                session_id=uuid5(NAMESPACE_URL, f"g5-audit-session:{label}:{run_id}"),
                event_type=BehaviorEventType.VIEW_RESOURCE,
                occurred_at=occurred_at,
                resource_id=resource_id,
                enqueue_profile_update=True,
            )
        )
        if receipt.replayed or receipt.outbox_id is None:
            raise ValueError(f"{label} audit replay fixture unexpectedly replayed")
        fixtures.append(
            {
                "label": label,
                "event_id": receipt.event_id,
                "outbox_id": receipt.outbox_id,
                "event_uuid": str(event_uuid),
                "occurred_at": occurred_at.isoformat(),
            }
        )
    return fixtures[0], fixtures[1]


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
        raise ValueError("G5 audit/replay runtime credentials are required")
    if not values.get("RECPRO_MYSQL_ROOT_PASSWORD"):
        raise ValueError("G5 audit/replay runtime requires the operator root password")

    for migration in MIGRATIONS:
        await apply_forward_migration(
            host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
            database=values["RECPRO_MYSQL_DATABASE"],
            user=migration_user,
            password=migration_password,
            path=migration,
        )
    seed_bytes = DEFAULT_SEED.read_bytes()
    seed = validate_seed(json.loads(seed_bytes.decode("utf-8")))
    await insert_seed(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        migration_user=migration_user,
        migration_password=migration_password,
        seed=seed,
        env_values=values,
        source_hash=sha256_bytes(seed_bytes),
    )
    await apply_replay(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        migration_user=migration_user,
        migration_password=migration_password,
        user_id=args.user_id,
        as_of=datetime(2025, 12, 31, 23, 59, 59, 999000),
        formula_version="profile-g2-v1",
    )
    await grant_g5_runtime_projection(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        root_password=values["RECPRO_MYSQL_ROOT_PASSWORD"],
        runtime_user=runtime_user,
    )

    baseline_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        baseline = await read_counts(
            baseline_connection, G5_TABLES + PROTECTED_TABLES + (AUDIT_TABLE,)
        )
        baseline_statuses = await read_outbox_statuses(baseline_connection)
        resource_id = await read_resource_id(baseline_connection)
    finally:
        baseline_connection.close()
    if baseline_statuses.get("PENDING", 0) or baseline_statuses.get("PROCESSING", 0):
        raise ValueError(f"audit/replay baseline contains live Outbox work: {baseline_statuses}")

    early_fixture, late_fixture = await append_fixture_pair(
        values, run_id=run_id, user_id=args.user_id, resource_id=resource_id
    )
    append_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        after_append = await read_counts(
            append_connection, G5_TABLES + PROTECTED_TABLES + (AUDIT_TABLE,)
        )
    finally:
        append_connection.close()
    if after_append["user_behavior_event"] != baseline["user_behavior_event"] + 2:
        raise ValueError("historical replay fixtures changed behavior fact count unexpectedly")
    if after_append["profile_update_outbox"] != baseline["profile_update_outbox"] + 2:
        raise ValueError("historical replay fixtures changed Outbox count unexpectedly")
    if after_append[AUDIT_TABLE] != baseline[AUDIT_TABLE] + 2:
        raise ValueError("Outbox creation was not audited in the same transaction")

    reader_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        reader = MySQLProfileSnapshotReader(reader_connection)
        early_snapshot = await reader.get_snapshot(
            user_id=args.user_id, as_of=datetime(2030, 1, 15, tzinfo=UTC)
        )
        late_snapshot = await reader.get_snapshot(
            user_id=args.user_id, as_of=datetime(2030, 1, 25, tzinfo=UTC)
        )
        late_repeat = await reader.get_snapshot(
            user_id=args.user_id, as_of=datetime(2030, 1, 25, tzinfo=UTC)
        )
        after_reader = await read_counts(
            reader_connection, G5_TABLES + PROTECTED_TABLES + (AUDIT_TABLE,)
        )
    finally:
        reader_connection.close()
    if early_snapshot.event_count + 1 != late_snapshot.event_count:
        raise ValueError("as-of reader did not exclude the later behavior fixture")
    if early_snapshot.input_hash == late_snapshot.input_hash:
        raise ValueError("historical snapshots unexpectedly share an input hash")
    if late_snapshot.input_hash != late_repeat.input_hash:
        raise ValueError("historical snapshot replay was not deterministic")
    if after_reader != after_append:
        raise ValueError("read-only historical profile reader changed database counts")

    async def worker_connection_factory() -> Any:
        return await connect(
            values,
            user=migration_user,
            password=migration_password,
            autocommit=False,
        )

    worker = build_profile_outbox_worker(
        AppSettings(
            app_env="demo",
            mysql_host="127.0.0.1",
            mysql_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
            mysql_database=values["RECPRO_MYSQL_DATABASE"],
            mysql_user=runtime_user,
            mysql_password=runtime_password,
            mysql_connect_timeout_seconds=10,
        ),
        connection_factory=worker_connection_factory,
        worker_id=f"g5-audit-{run_id}",
        formula_version="profile-g2-v1",
    )
    receipts = await worker.run_once(limit=2)
    replay_receipts = await worker.run_once(limit=2)
    if len(receipts) != 2 or replay_receipts:
        raise ValueError("audit/replay worker did not consume exactly the two new Outbox rows")

    final_connection = await connect(
        values, user=runtime_user, password=runtime_password, autocommit=True
    )
    try:
        final_counts = await read_counts(
            final_connection, G5_TABLES + PROTECTED_TABLES + (AUDIT_TABLE,)
        )
        final_statuses = await read_outbox_statuses(final_connection)
        aggregate_ids = tuple(str(item["outbox_id"]) for item in (early_fixture, late_fixture))
        transition_rows = await read_transition_rows(
            final_connection, aggregate_ids=aggregate_ids + (str(args.user_id),)
        )
    finally:
        final_connection.close()
    if final_counts["profile_update_outbox"] != after_append["profile_update_outbox"]:
        raise ValueError("worker changed append-only Outbox row count")
    if final_counts[AUDIT_TABLE] != after_append[AUDIT_TABLE] + 6:
        raise ValueError("worker audit transition count did not match claim/profile/done writes")
    if final_statuses.get("PENDING", 0) or final_statuses.get("PROCESSING", 0):
        raise ValueError(f"audit/replay worker left live Outbox work: {final_statuses}")
    outbox_transition_types = [
        row["transition_type"]
        for row in transition_rows
        if row["aggregate_type"] == "PROFILE_OUTBOX"
    ]
    if outbox_transition_types.count("CREATED") != 2:
        raise ValueError("missing Outbox CREATED audit transitions")
    if outbox_transition_types.count("CLAIMED") != 2:
        raise ValueError("missing Outbox CLAIMED audit transitions")
    if outbox_transition_types.count("MARK_DONE") != 2:
        raise ValueError("missing Outbox MARK_DONE audit transitions")
    fixture_outbox_ids = {str(early_fixture["outbox_id"]), str(late_fixture["outbox_id"])}
    profile_rows = [
        row
        for row in transition_rows
        if row["aggregate_type"] == "USER_PROFILE"
        and any(
            row["causation_ref"].startswith(f"OUTBOX:{outbox_id}:EVENT:")
            for outbox_id in fixture_outbox_ids
        )
    ]
    if len(profile_rows) != 2 or any(row["transition_type"] != "REPLAY_APPLIED" for row in profile_rows):
        raise ValueError("missing profile replay audit transitions")
    for table in PROTECTED_TABLES:
        if final_counts[table] != baseline[table]:
            raise ValueError(f"historical replay changed protected table {table}")

    target_dir = evidence_dir(run_id)
    target_dir.mkdir(parents=True, exist_ok=False)
    evidence = {
        "schema_version": "g5-audit-replay-runtime-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "user_id": args.user_id,
        "resource_id": resource_id,
        "fixtures": {"early": early_fixture, "late": late_fixture},
        "baseline_counts": baseline,
        "after_append_counts": after_append,
        "after_reader_counts": after_reader,
        "final_counts": final_counts,
        "outbox_statuses_before": baseline_statuses,
        "outbox_statuses_after": final_statuses,
        "historical_snapshots": {
            "early": {
                "as_of": early_snapshot.as_of.isoformat(),
                "event_count": early_snapshot.event_count,
                "input_hash": early_snapshot.input_hash,
                "interest_count": len(early_snapshot.interests),
            },
            "late": {
                "as_of": late_snapshot.as_of.isoformat(),
                "event_count": late_snapshot.event_count,
                "input_hash": late_snapshot.input_hash,
                "interest_count": len(late_snapshot.interests),
            },
        },
        "transition_rows": transition_rows,
        "worker_receipt_count": len(receipts),
        "worker_replay_receipt_count": len(replay_receipts),
        "database_sql_actions": {
            "fact_inserts": "2 behavior + 2 Outbox + 8 audit transition rows",
            "controlled_updates": "Outbox claim/status and profile current projection",
            "deletes": 0,
            "ddl_drops_or_alters": 0,
        },
        "destructive_actions": 0,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (target_dir / "runtime.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G5 state-transition and historical replay evidence: {target_dir}")
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
        print(f"[FAIL] G5 state-transition/historical replay verification did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
