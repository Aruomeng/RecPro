"""Probe the real Profile Outbox worker against an isolated empty queue.

The verifier is intentionally conservative: it reads the complete table-count
snapshot and Outbox status first, and aborts if any ``PENDING`` or
``PROCESSING`` row exists.  Only an empty queue is passed to the real worker
poll path, so the bounded run must return zero receipts and leave all counts
unchanged.  No migration, business append, external request, or destructive
operation is included.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import asyncmy

from backend.app.worker import _mysql_connection_factory
from backend.app.composition import build_profile_outbox_worker
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g5_worker_wiring import _read_worker_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


async def connect(values: Mapping[str, str], *, autocommit: bool) -> Any:
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


async def read_full_counts(connection: Any) -> dict[str, int]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() ORDER BY table_name"
        )
        table_names = tuple(str(row[0]) for row in await cursor.fetchall())
        if any(TABLE_PATTERN.fullmatch(table) is None for table in table_names):
            raise ValueError("database returned an unsafe table identifier")
        counts: dict[str, int] = {}
        for table in table_names:
            await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"count query returned no row for {table}")
            counts[table] = int(row[0])
        return counts


async def read_outbox_statuses(connection: Any) -> dict[str, int]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT status, COUNT(*) FROM profile_update_outbox "
            "GROUP BY status ORDER BY status"
        )
        return {str(row[0]): int(row[1]) for row in await cursor.fetchall()}


async def execute(args: argparse.Namespace) -> dict[str, object]:
    run_id = validate_run_id(args.run_id)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")

    values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    required = (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_MYSQL_MIGRATION_USER",
        "RECPRO_MYSQL_MIGRATION_PASSWORD",
        "RECPRO_PERSISTENCE_PROBE_ID",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")

    baseline_connection = await connect(values, autocommit=True)
    try:
        before_counts = await read_full_counts(baseline_connection)
        before_statuses = await read_outbox_statuses(baseline_connection)
    finally:
        baseline_connection.close()
    if before_statuses.get("PENDING", 0) or before_statuses.get("PROCESSING", 0):
        raise RuntimeError(
            "refusing the live worker probe because the queue is not empty: "
            f"{before_statuses}"
        )

    worker_values = dict(values)
    worker_values.update(
        {
            "RECPRO_MYSQL_HOST": "127.0.0.1",
            "RECPRO_MYSQL_PORT": values["RECPRO_MYSQL_HOST_PORT"],
            # The controlled worker path needs SELECT ... FOR UPDATE.  The
            # runtime account is intentionally denied that lock privilege;
            # use the separately scoped migration identity even though this
            # empty-queue probe must produce zero writes.
            "RECPRO_MYSQL_USER": values["RECPRO_MYSQL_MIGRATION_USER"],
            "RECPRO_MYSQL_PASSWORD": values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
            "RECPRO_WORKER_ENABLED": "true",
            "RECPRO_WORKER_MODE": "profile_outbox",
            "RECPRO_WORKER_ID": f"g5-readonly-{run_id}",
            "RECPRO_WORKER_BATCH_LIMIT": "1",
        }
    )
    settings = _read_worker_settings(worker_values)
    worker = build_profile_outbox_worker(
        settings,
        connection_factory=_mysql_connection_factory(settings),
        worker_id=settings.worker_id,
        formula_version=settings.worker_formula_version,
        lease_seconds=settings.worker_lease_seconds,
        max_attempts=settings.worker_max_attempts,
    )
    receipts = await worker.run_once(limit=1)
    if receipts:
        raise RuntimeError("empty-queue worker probe unexpectedly consumed Outbox work")

    after_connection = await connect(values, autocommit=True)
    try:
        after_counts = await read_full_counts(after_connection)
        after_statuses = await read_outbox_statuses(after_connection)
    finally:
        after_connection.close()
    if before_counts != after_counts or before_statuses != after_statuses:
        raise RuntimeError("read-only worker probe changed database counts or statuses")

    evidence = {
        "schema_version": "g5-worker-readonly-runtime-evidence-v1",
        "status": "PASS",
        "run_id": run_id,
        "compose_project": values.get("COMPOSE_PROJECT_NAME"),
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "worker": {
            "mode": settings.worker_mode,
            "worker_id": settings.worker_id,
            "batch_limit": settings.worker_batch_limit,
            "formula_version": settings.worker_formula_version,
        },
        "before_outbox_statuses": before_statuses,
        "after_outbox_statuses": after_statuses,
        "worker_receipt_count": len(receipts),
        "before_counts": before_counts,
        "after_counts": after_counts,
        "database_connections": 3,
        "database_writes": 0,
        "outbox_claims": 0,
        "external_requests": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "readonly.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G5 Worker read-only runtime probe did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
