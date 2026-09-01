#!/usr/bin/env python3
"""Apply one approved chronological synthetic profile-demo ChangePlan."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import asyncmy

from backend.app.composition import build_profile_outbox_worker
from scripts.build_current_synthetic_profile_demo_change_plan import (
    INPUTS, PROJECT_ROOT, _canonical, _preview,
)
from scripts.plan_current_synthetic_profile_demo import build_current_profile_demo_intent, _parse_utc
from scripts.validate_runtime_env import read_env
from scripts.verify_current_synthetic_profile_demo import reconcile_current
from scripts.verify_g7_mysql_http_readonly import build_settings


_COUNT_TABLES = (
    "user_behavior_event", "profile_update_outbox", "profile_replay_run", "profile_change_log",
    "domain_state_transition", "user_profile", "user_interest_tag", "user_negative_preference",
)


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _port(values: Mapping[str, str]) -> int:
    raw = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    if raw is None or not raw.isdigit():
        raise ValueError("a valid MySQL host port is required")
    return int(raw)


def validate(plan_path: Path, *, plan_id: str, plan_hash: str) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash:
        raise ValueError("approved plan identity does not match")
    unsigned = dict(plan); unsigned.pop("plan_hash", None)
    if sha256(_canonical(unsigned)).hexdigest() != plan_hash:
        raise ValueError("approved plan canonical hash does not match")
    if plan.get("schema_version") != "current-synthetic-profile-demo-change-plan-v1" or plan.get("classification") != "S2_CONTROLLED_PROFILE_DEMO" or plan.get("mode") != "APPLY":
        raise ValueError("plan is outside the chronological profile-demo boundary")
    intent = plan.get("intent", {})
    if intent.get("target") != {"user_id": 1002, "synthetic_user_id": "synthetic-u-0001"}:
        raise ValueError("plan target is not the fixed profile-demo user boundary")
    expected = {
        "user_behavior_event": 16, "profile_update_outbox": 1, "profile_replay_run": 1,
        "profile_change_log": 16, "domain_state_transition": 3, "user_profile": 0,
    }
    observed = plan.get("projection_preview", {}).get("expected_deltas", {})
    if any(observed.get(key) != value for key, value in expected.items()):
        raise ValueError("plan does not retain the fixed append/update boundary")
    if plan.get("safety") != {"database_deletions": 0, "file_deletions": 0, "neo4j_writes": 0, "chroma_writes": 0, "deepseek_requests": 0, "recommendation_tasks": 0}:
        raise ValueError("plan safety budget differs from the fixed zero-side-effect boundary")
    if plan.get("input_hashes") != {item: _hash(PROJECT_ROOT / item) for item in INPUTS}:
        raise ValueError("plan inputs no longer match executable code")
    if subprocess.run(["git", "merge-base", "--is-ancestor", str(plan.get("git_commit", "")), "HEAD"], cwd=PROJECT_ROOT, check=False).returncode != 0:
        raise ValueError("plan commit is not an ancestor of current code")
    return plan


async def _counts(values: Mapping[str, str]) -> dict[str, int]:
    connection = await asyncmy.connect(host="127.0.0.1", port=_port(values), user=values["RECPRO_MYSQL_USER"], password=values["RECPRO_MYSQL_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"], autocommit=True, charset="utf8mb4")
    try:
        async with connection.cursor() as cursor:
            result: dict[str, int] = {}
            for table in _COUNT_TABLES:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                result[table] = int((await cursor.fetchone())[0])
            return result
    finally:
        connection.close()


async def _migration_connection(values: Mapping[str, str]) -> Any:
    return await asyncmy.connect(host="127.0.0.1", port=_port(values), user=values["RECPRO_MYSQL_MIGRATION_USER"], password=values["RECPRO_MYSQL_MIGRATION_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"], autocommit=False, charset="utf8mb4")


async def apply(args: argparse.Namespace) -> dict[str, Any]:
    plan = validate(args.plan.resolve(strict=True), plan_id=args.plan_id, plan_hash=args.approved_plan_hash)
    intent = build_current_profile_demo_intent(args.benchmark_dir, base_occurred_at=str(plan["intent"]["timeline"]["base_occurred_at"]))
    if intent != plan["intent"]:
        raise ValueError("frozen profile-demo intent differs from approved plan")
    values = read_env(args.env_file.resolve(strict=True))
    reconciliation = await reconcile_current(values, intent)
    if reconciliation != plan["reconciliation"] or not reconciliation["ready_for_profile_demo_plan"]:
        raise ValueError("read-only preconditions changed; profile-demo apply is refused")
    preview = await _preview(values, intent, reconciliation)
    if preview != plan["projection_preview"]:
        raise ValueError("profile projection preview drifted; profile-demo apply is refused")
    before = await _counts(values)
    if before != preview["table_counts_before"]:
        raise ValueError("table-count baseline drifted; profile-demo apply is refused")

    connection = await _migration_connection(values)
    try:
        async with connection.cursor() as cursor:
            for event in intent["events"]:
                await cursor.execute(
                    "INSERT INTO user_behavior_event (event_uuid,user_id,session_id,event_type,resource_id,reason_code,tag_evidence_json,occurred_at,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(3))",
                    (str(event["event_uuid"]), 1002, str(event["session_uuid"]), str(event["event_type"]), int(reconciliation["resource_mappings"][str(event["resource_external_id"])]), str(event["reason_code"]), json.dumps({"origin":"SYNTHETIC_DEVELOPMENT_ONLY","dataset_version":intent["benchmark"]["dataset_version"]}, separators=(",", ":")), _parse_utc(str(event["occurred_at"])).replace(tzinfo=None)),
                )
            source_uuid = str(intent["profile_refresh_batch"]["source_event_uuid"])
            await cursor.execute("SELECT id FROM user_behavior_event WHERE event_uuid=%s FOR UPDATE", (source_uuid,))
            source = await cursor.fetchone()
            if source is None:
                raise RuntimeError("synthetic batch source event was not inserted")
            source_event_id = int(source[0])
            await cursor.execute(
                "INSERT INTO profile_update_outbox (user_id,source_event_id,source_type,payload_json,status,attempts,next_retry_at,locked_at,locked_by,last_error,created_at,updated_at) VALUES (%s,%s,'SYNTHETIC_BATCH',%s,'PENDING',0,NULL,NULL,NULL,NULL,UTC_TIMESTAMP(3),UTC_TIMESTAMP(3))",
                (1002, source_event_id, json.dumps({"origin":"SYNTHETIC_DEVELOPMENT_ONLY","batch_events":16}, separators=(",", ":"))),
            )
            outbox_id = int(cursor.lastrowid)
        await connection.commit()
    except Exception:
        await connection.rollback(); raise
    finally:
        connection.close()

    worker_values = dict(values)
    worker_values.setdefault("RECPRO_MYSQL_HOST_PORT", str(_port(values)))
    settings = build_settings(worker_values)

    async def connection_factory() -> Any:
        return await _migration_connection(values)

    worker = build_profile_outbox_worker(settings, connection_factory=connection_factory, worker_id=f"synthetic-profile-demo-{outbox_id}", formula_version="profile-g2-v1", max_attempts=3, allowed_outbox_ids=(outbox_id,))
    receipts = await worker.run_once(limit=1)
    replay = await worker.run_once(limit=1)
    if len(receipts) != 1 or replay or int(receipts[0].outbox_id) != outbox_id:
        raise RuntimeError("exact Worker did not consume the synthetic batch once")
    after = await _counts(values)
    expected_deltas = preview["expected_deltas"]
    for table, delta in expected_deltas.items():
        if after[table] - before[table] != int(delta):
            raise RuntimeError(f"observed delta differs for {table}")
    if int(receipts[0].profile_version) <= int(reconciliation["target_profile_before"]["profile_version"]):
        raise RuntimeError("profile version did not advance")
    return {"status":"PASS", "plan_id":plan["plan_id"], "outbox_id":outbox_id, "source_event_id":source_event_id, "profile_version_after":int(receipts[0].profile_version), "before_counts":before, "after_counts":after, "database_deletions":0, "deepseek_requests":0, "neo4j_writes":0, "chroma_writes":0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True); parser.add_argument("--plan-id", required=True); parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host"); parser.add_argument("--benchmark-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(apply(args)), ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] current synthetic profile-demo apply: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
