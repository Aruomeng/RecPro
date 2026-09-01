#!/usr/bin/env python3
"""Read-only reconciliation for the chronological synthetic profile demo."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import asyncmy

from scripts.evaluation_runtime import reserve_directory, write_json_exclusive
from scripts.plan_current_synthetic_profile_demo import (
    build_current_profile_demo_intent,
    _parse_utc,
)
from scripts.validate_runtime_env import read_env
from scripts.verify_synthetic_demo_behavior_import import reconcile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def _port(values: Mapping[str, str]) -> int:
    raw = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    if raw is None or not raw.isdigit():
        raise ValueError("a valid MySQL host port is required")
    return int(raw)


async def reconcile_current(
    values: Mapping[str, str], intent: Mapping[str, Any],
) -> dict[str, Any]:
    base = await reconcile(values, intent)
    user_id = int(intent["target"]["user_id"])
    connection = await asyncmy.connect(
        host="127.0.0.1", port=_port(values), user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10, read_timeout=30, charset="utf8mb4", autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT MAX(occurred_at) FROM user_behavior_event WHERE user_id=%s", (user_id,))
            latest = (await cursor.fetchone())[0]
            await cursor.execute(
                "SELECT status, COUNT(*) FROM profile_update_outbox WHERE user_id=%s "
                "AND status IN ('PENDING','PROCESSING') GROUP BY status ORDER BY status",
                (user_id,),
            )
            pending = {str(status): int(count) for status, count in await cursor.fetchall()}
            await cursor.execute(
                "SELECT profile_version, updated_at FROM user_profile WHERE user_id=%s", (user_id,)
            )
            profile = await cursor.fetchone()
    finally:
        connection.close()
    base_at = _parse_utc(str(intent["timeline"]["base_occurred_at"]))
    latest_at = latest.replace(tzinfo=UTC) if latest is not None else None
    chronological = latest_at is None or base_at > latest_at
    return {
        **base,
        "target_latest_behavior_at": latest_at.isoformat().replace("+00:00", "Z") if latest_at else None,
        "timeline_base_at": base_at.isoformat().replace("+00:00", "Z"),
        "timeline_is_strictly_chronological": chronological,
        "target_pending_or_processing_outbox": pending,
        "target_profile_before": (
            {"profile_version": int(profile[0]), "updated_at": profile[1].replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")}
            if profile else None
        ),
        "ready_for_profile_demo_plan": bool(
            base["ready_for_append_plan"] and chronological and not pending and profile is not None
        ),
    }


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if _RUN_ID.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    output = PROJECT_ROOT / "artifacts" / "verification" / "synthetic-profile-demo" / args.run_id
    if output.exists():
        raise FileExistsError("read-only evidence directory already exists")
    intent = build_current_profile_demo_intent(
        args.benchmark_dir, base_occurred_at=args.base_occurred_at,
    )
    result = await reconcile_current(read_env(args.env_file.resolve(strict=True)), intent)
    evidence = {
        "schema_version": "current-synthetic-profile-demo-reconciliation-v1",
        "status": "PASS" if result["ready_for_profile_demo_plan"] else "BLOCKED",
        "run_id": args.run_id,
        "intent": intent,
        "reconciliation": result,
        "safety": {"database_reads": 7, "database_writes": 0, "deepseek_requests": 0, "deletions": 0},
    }
    reserve_directory(output)
    write_json_exclusive(output / "reconciliation.json", evidence)
    return evidence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--base-occurred-at", default="2026-09-01T12:00:00.000Z")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, asyncmy.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] current synthetic profile-demo reconciliation: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
