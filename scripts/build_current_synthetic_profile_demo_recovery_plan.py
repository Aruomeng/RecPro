#!/usr/bin/env python3
"""Build an exact no-append recovery plan for one interrupted synthetic Outbox."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

import asyncmy

from scripts.build_current_synthetic_profile_demo_change_plan import PROJECT_ROOT, _canonical, _port
from scripts.validate_runtime_env import read_env


INPUTS = (
    "scripts/build_current_synthetic_profile_demo_recovery_plan.py",
    "scripts/execute_current_synthetic_profile_demo_recovery_plan.py",
    "backend/app/profile/adapters/refresh_mysql.py",
    "backend/app/profile/replay.py",
)
_TABLES = ("user_behavior_event", "profile_update_outbox", "profile_replay_run", "profile_change_log", "domain_state_transition", "user_profile", "user_interest_tag", "user_negative_preference")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


async def reconcile(values: Mapping[str, str], source_plan: Mapping[str, Any]) -> dict[str, Any]:
    intent = source_plan["intent"]
    source_uuid = str(intent["profile_refresh_batch"]["source_event_uuid"])
    connection = await asyncmy.connect(host="127.0.0.1", port=_port(values), user=values["RECPRO_MYSQL_USER"], password=values["RECPRO_MYSQL_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"], autocommit=True, charset="utf8mb4")
    try:
        async with connection.cursor() as cursor:
            counts: dict[str, int] = {}
            for table in _TABLES:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                counts[table] = int((await cursor.fetchone())[0])
            await cursor.execute("SELECT id,user_id,source_event_id,source_type,status,attempts FROM profile_update_outbox WHERE id=%s", (54,))
            outbox = await cursor.fetchone()
            await cursor.execute("SELECT id,event_uuid,user_id FROM user_behavior_event WHERE event_uuid=%s", (source_uuid,))
            source_event = await cursor.fetchone()
            await cursor.execute("SELECT COUNT(*) FROM user_behavior_event WHERE user_id=1002 AND reason_code='SYNTHETIC_DEVELOPMENT_ONLY'")
            synthetic_events = int((await cursor.fetchone())[0])
            await cursor.execute("SELECT profile_version FROM user_profile WHERE user_id=1002")
            profile = await cursor.fetchone()
    finally:
        connection.close()
    ready = bool(
        outbox is not None and source_event is not None and int(outbox[0]) == 54 and int(outbox[1]) == 1002
        and int(outbox[2]) == int(source_event[0]) and str(outbox[3]) == "SYNTHETIC_BATCH"
        and str(outbox[4]) == "PENDING" and int(outbox[5]) == 0 and int(source_event[2]) == 1002
        and synthetic_events == 16 and profile is not None and int(profile[0]) == 3
    )
    return {
        "table_counts_before": counts,
        "outbox": {"id": int(outbox[0]), "user_id": int(outbox[1]), "source_event_id": int(outbox[2]), "source_type": str(outbox[3]), "status": str(outbox[4]), "attempts": int(outbox[5])} if outbox else None,
        "source_event": {"id": int(source_event[0]), "event_uuid": str(source_event[1]), "user_id": int(source_event[2])} if source_event else None,
        "synthetic_event_count": synthetic_events,
        "profile_version_before": int(profile[0]) if profile else None,
        "ready_for_recovery": ready,
    }


async def build(args: argparse.Namespace) -> dict[str, Any]:
    source = json.loads(args.source_plan.resolve(strict=True).read_text(encoding="utf-8"))
    if source.get("plan_id") != "d1f28f89-1822-54fa-a0fc-6e9334ace128" or source.get("plan_hash") != "e500a6046f95e41fc13a9271f51082452bc64db5b7fe85495165cc20274de669":
        raise ValueError("recovery is bound only to the interrupted synthetic profile-demo plan")
    values = read_env(args.env_file.resolve(strict=True))
    state = await reconcile(values, source)
    if not state["ready_for_recovery"]:
        raise ValueError("interrupted synthetic Outbox is not in the exact recoverable state")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    plan: dict[str, Any] = {
        "schema_version": "current-synthetic-profile-demo-recovery-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"libramas:synthetic-profile-recovery:{commit}:54")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S2_PROFILE_DEMO_RECOVERY",
        "mode": "APPLY",
        "source_plan": {"plan_id": source["plan_id"], "plan_hash": source["plan_hash"]},
        "reconciliation": state,
        "expected_deltas": {"user_behavior_event": 0, "profile_update_outbox": 0, "profile_replay_run": 1, "profile_change_log": 16, "domain_state_transition": 3, "user_profile": 0, "user_interest_tag": 14, "user_negative_preference": 0},
        "controlled_updates": {"profile_update_outbox": 1, "user_profile": 1, "user_interest_tag": 17, "user_negative_preference": 0},
        "max_row_increase": 34,
        "input_hashes": {item: _sha(PROJECT_ROOT / item) for item in INPUTS},
        "safety": {"database_deletions": 0, "file_deletions": 0, "behavior_appends": 0, "recommendation_tasks": 0, "deepseek_requests": 0, "neo4j_writes": 0, "chroma_writes": 0},
        "preconditions": ["only Outbox #54 may be claimed", "no new behavior or Outbox fact may be appended", "source event #122 and user 1002 profile version 3 remain unchanged"],
    }
    plan["plan_hash"] = sha256(_canonical(plan)).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-plan", type=Path, required=True); parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host"); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(build(args)); output=args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle: json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] synthetic profile-demo recovery ChangePlan: {type(exc).__name__}: {exc}"); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
