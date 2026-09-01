#!/usr/bin/env python3
"""Execute one approved synthetic demo append plan; no update/delete capability."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence

import asyncmy

from scripts.build_synthetic_demo_behavior_change_plan import INPUTS, _canonical
from scripts.verify_synthetic_demo_behavior_import import reconcile
from scripts.plan_synthetic_demo_behavior_import import build_import_intent
from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def validate(plan_path: Path, *, plan_id: str, plan_hash: str) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash:
        raise ValueError("approved plan identity does not match")
    unsigned = dict(plan); unsigned.pop("plan_hash", None)
    if sha256(_canonical(unsigned)).hexdigest() != plan_hash:
        raise ValueError("approved plan canonical hash does not match")
    if (
        plan.get("schema_version") != "synthetic-demo-behavior-change-plan-v1"
        or plan.get("classification") != "S1_APPEND"
        or plan.get("mode") != "APPLY"
        or plan.get("max_changes") != 16
    ):
        raise ValueError("plan is outside the 16-row append boundary")
    if plan.get("target") != {"user_id": 1001, "synthetic_user_id": "synthetic-u-0001"}:
        raise ValueError("plan target is not the fixed synthetic demo user boundary")
    if plan.get("targets") != [{"kind": "MYSQL", "identifier": "recpro.user_behavior_event:synthetic-demo-20260901", "operation": "APPEND", "rows": 16}]:
        raise ValueError("plan contains an unexpected write target")
    if plan.get("safety") != {
        "database_deletions": 0,
        "file_deletions": 0,
        "profile_outbox_rows": 0,
        "profile_updates": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "deepseek_requests": 0,
    }:
        raise ValueError("plan safety budget differs from the fixed zero-side-effect boundary")
    if plan.get("input_hashes") != {item: _hash(PROJECT_ROOT / item) for item in INPUTS}:
        raise ValueError("plan inputs no longer match executable code")
    if subprocess.run(["git", "merge-base", "--is-ancestor", str(plan.get("git_commit", "")), "HEAD"], cwd=PROJECT_ROOT, check=False).returncode != 0:
        raise ValueError("plan commit is not an ancestor of current code")
    return plan


async def apply(args: argparse.Namespace) -> dict[str, Any]:
    plan = validate(args.plan.resolve(strict=True), plan_id=args.plan_id, plan_hash=args.approved_plan_hash)
    intent = build_import_intent(args.benchmark_dir, synthetic_user_id="synthetic-u-0001", target_user_id=1001)
    if plan["benchmark"] != intent["benchmark"] or plan["events"] != intent["events"]:
        raise ValueError("frozen benchmark intent differs from approved plan")
    values = read_env(args.env_file.resolve(strict=True))
    current = await reconcile(values, intent)
    if current != plan["reconciliation"] or not current["ready_for_append_plan"]:
        raise ValueError("read-only preconditions changed; append is refused")
    port = int(values.get("RECPRO_MYSQL_HOST_PORT") or values["RECPRO_MYSQL_PORT"])
    connection = await asyncmy.connect(host="127.0.0.1", port=port, user=values["RECPRO_MYSQL_USER"], password=values["RECPRO_MYSQL_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"], autocommit=False, charset="utf8mb4")
    try:
        inserted = 0
        async with connection.cursor() as cursor:
            for event in intent["events"]:
                await cursor.execute(
                    "INSERT INTO user_behavior_event (event_uuid,user_id,session_id,event_type,resource_id,reason_code,tag_evidence_json,occurred_at,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(3))",
                    (event["event_uuid"], 1001, event["session_uuid"], event["event_type"], current["resource_mappings"][event["resource_external_id"]], event["reason_code"], json.dumps({"origin":"SYNTHETIC_DEVELOPMENT_ONLY","dataset_version":intent["benchmark"]["dataset_version"]}, separators=(",", ":")), datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")).replace(tzinfo=None)),
                )
                inserted += max(0, int(cursor.rowcount))
            if inserted != 16:
                raise RuntimeError("append row count differs from approved 16-row budget")
        await connection.commit()
        return {"status": "PASS", "inserted_behavior_rows": inserted, "profile_outbox_rows": 0, "deletions": 0, "deepseek_requests": 0}
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True); parser.add_argument("--plan-id", required=True); parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host"); parser.add_argument("--benchmark-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(apply(args)), ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, asyncmy.Error) as exc:
        print(f"[FAIL] synthetic demo append: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
