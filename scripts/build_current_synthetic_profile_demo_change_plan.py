#!/usr/bin/env python3
"""Build the exact ChangePlan for one chronological synthetic profile demo."""

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

from backend.app.profile.replay import BehaviorForReplay, ResourceTagEvidence, compute_profile_snapshot
from scripts.plan_current_synthetic_profile_demo import build_current_profile_demo_intent, _parse_utc
from scripts.validate_runtime_env import read_env
from scripts.verify_current_synthetic_profile_demo import reconcile_current


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "scripts/plan_current_synthetic_profile_demo.py",
    "scripts/verify_current_synthetic_profile_demo.py",
    "scripts/build_current_synthetic_profile_demo_change_plan.py",
    "scripts/execute_current_synthetic_profile_demo_change_plan.py",
    "backend/app/profile/adapters/refresh_mysql.py",
    "backend/app/profile/replay.py",
)
_COUNT_TABLES = (
    "user_behavior_event", "profile_update_outbox", "profile_replay_run", "profile_change_log",
    "domain_state_transition", "user_profile", "user_interest_tag", "user_negative_preference",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _port(values: Mapping[str, str]) -> int:
    raw = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    if raw is None or not raw.isdigit():
        raise ValueError("a valid MySQL host port is required")
    return int(raw)


async def _preview(
    values: Mapping[str, str], intent: Mapping[str, Any], reconciliation: Mapping[str, Any],
) -> dict[str, Any]:
    user_id = int(intent["target"]["user_id"])
    as_of = _parse_utc(str(intent["timeline"]["final_occurred_at"]))
    connection = await asyncmy.connect(
        host="127.0.0.1", port=_port(values), user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10, read_timeout=30, charset="utf8mb4", autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id,event_uuid,event_type,resource_id,occurred_at,reason_code "
                "FROM user_behavior_event WHERE user_id=%s AND occurred_at<=%s ORDER BY occurred_at,id,event_uuid",
                (user_id, as_of.replace(tzinfo=None)),
            )
            existing = await cursor.fetchall()
            planned_resources = tuple(sorted({int(reconciliation["resource_mappings"][str(event["resource_external_id"])]) for event in intent["events"]}))
            resource_ids = tuple(sorted({int(row[3]) for row in existing if row[3] is not None} | set(planned_resources)))
            tag_map: dict[int, list[ResourceTagEvidence]] = {item: [] for item in resource_ids}
            if resource_ids:
                placeholders = ",".join("%s" for _ in resource_ids)
                await cursor.execute(
                    "SELECT resource_id,tag_id,weight,confidence FROM resource_tag "
                    f"WHERE resource_id IN ({placeholders}) ORDER BY resource_id,tag_id,source", resource_ids,
                )
                for resource_id, tag_id, weight, confidence in await cursor.fetchall():
                    tag_map[int(resource_id)].append(ResourceTagEvidence(int(tag_id), float(weight), float(confidence)))
            await cursor.execute("SELECT tag_id FROM user_interest_tag WHERE user_id=%s", (user_id,))
            current_interests = {int(row[0]) for row in await cursor.fetchall()}
            await cursor.execute("SELECT tag_id,reason_code FROM user_negative_preference WHERE user_id=%s", (user_id,))
            current_negatives = {(int(row[0]), str(row[1])) for row in await cursor.fetchall()}
            await cursor.execute("SELECT COUNT(*) FROM user_interest_tag WHERE user_id=%s", (user_id,))
            interest_rows_before = int((await cursor.fetchone())[0])
            await cursor.execute("SELECT COUNT(*) FROM user_negative_preference WHERE user_id=%s", (user_id,))
            negative_rows_before = int((await cursor.fetchone())[0])
            counts: dict[str, int] = {}
            for table in _COUNT_TABLES:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                counts[table] = int((await cursor.fetchone())[0])
    finally:
        connection.close()
    replay_events = [
        BehaviorForReplay(
            event_id=int(row[0]), event_uuid=str(row[1]), event_type=str(row[2]),
            resource_id=int(row[3]) if row[3] is not None else None,
            occurred_at=row[4].replace(tzinfo=UTC),
            reason_code=str(row[5]) if row[5] is not None else None,
            tags=tuple(tag_map.get(int(row[3]), ())) if row[3] is not None else (),
        )
        for row in existing
    ]
    for index, event in enumerate(intent["events"], start=1):
        resource_id = int(reconciliation["resource_mappings"][str(event["resource_external_id"])])
        replay_events.append(BehaviorForReplay(
            event_id=-index, event_uuid=str(event["event_uuid"]), event_type=str(event["event_type"]),
            resource_id=resource_id, occurred_at=_parse_utc(str(event["occurred_at"])),
            reason_code=str(event["reason_code"]), tags=tuple(tag_map.get(resource_id, ())),
        ))
    snapshot = compute_profile_snapshot(
        user_id=user_id, as_of=as_of, events=tuple(replay_events), formula_version="profile-g2-v1",
    )
    interest_inserts = sum(1 for item in snapshot.interests if item.tag_id not in current_interests)
    negative_inserts = sum(
        1 for item in snapshot.negatives if (item.tag_id, item.reason_code) not in current_negatives
    )
    expected_deltas = {
        "user_behavior_event": 16,
        "profile_update_outbox": 1,
        "profile_replay_run": 1,
        "profile_change_log": 16,
        "domain_state_transition": 3,
        "user_profile": 0,
        "user_interest_tag": interest_inserts,
        "user_negative_preference": negative_inserts,
    }
    return {
        "table_counts_before": counts,
        "expected_deltas": expected_deltas,
        "profile_update_rows": {
            "user_profile": 1,
            "user_interest_tag": interest_rows_before + interest_inserts,
            "user_negative_preference": negative_rows_before + negative_inserts,
        },
        "preview": {
            "event_count": snapshot.event_count,
            "interest_signal_count": len(snapshot.interests),
            "negative_signal_count": len(snapshot.negatives),
            "preview_input_hash": snapshot.input_hash,
        },
    }


async def build(args: argparse.Namespace) -> dict[str, Any]:
    intent = build_current_profile_demo_intent(args.benchmark_dir, base_occurred_at=args.base_occurred_at)
    values = read_env(args.env_file.resolve(strict=True))
    reconciliation = await reconcile_current(values, intent)
    if not reconciliation["ready_for_profile_demo_plan"]:
        raise ValueError("chronological synthetic profile demo is not ready for a ChangePlan")
    preview = await _preview(values, intent, reconciliation)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    plan: dict[str, Any] = {
        "schema_version": "current-synthetic-profile-demo-change-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"libramas:current-synthetic-profile-demo:{commit}:{intent['intent_hash']}")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S2_CONTROLLED_PROFILE_DEMO",
        "mode": "APPLY",
        "intent": intent,
        "reconciliation": reconciliation,
        "projection_preview": preview,
        "targets": [
            {"kind": "MYSQL", "identifier": f"recpro.{table}", "operation": "APPEND" if delta else "UPDATE_ONLY", "rows": delta}
            for table, delta in preview["expected_deltas"].items()
        ],
        "max_row_increase": sum(preview["expected_deltas"].values()),
        "input_hashes": {item: _sha(PROJECT_ROOT / item) for item in INPUTS},
        "safety": {"database_deletions": 0, "file_deletions": 0, "neo4j_writes": 0, "chroma_writes": 0, "deepseek_requests": 0, "recommendation_tasks": 0},
        "preconditions": [
            "user 1002 remains a research-demo identity outside iam_user_account",
            "all 16 deterministic UUIDs remain absent",
            "2026-09 timeline remains after existing user 1002 behavior",
            "user 1002 has no PENDING or PROCESSING Outbox",
            "all listed table counts and profile preview remain unchanged",
        ],
    }
    plan["plan_hash"] = sha256(_canonical(plan)).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--base-occurred-at", default="2026-09-01T12:00:00.000Z")
    parser.add_argument("--output", type=Path, help="new JSON path; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(build(args))
        if args.output is not None:
            output = args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] current synthetic profile-demo ChangePlan: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
