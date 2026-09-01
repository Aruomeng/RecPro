#!/usr/bin/env python3
"""Consume only the approved interrupted synthetic profile Outbox once."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import asyncmy

from backend.app.composition import build_profile_outbox_worker
from scripts.build_current_synthetic_profile_demo_change_plan import PROJECT_ROOT, _canonical, _port
from scripts.build_current_synthetic_profile_demo_recovery_plan import INPUTS, reconcile
from scripts.validate_runtime_env import read_env
from scripts.verify_g7_mysql_http_readonly import build_settings


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def validate(path: Path, *, plan_id: str, plan_hash: str) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash:
        raise ValueError("approved recovery plan identity does not match")
    unsigned=dict(plan); unsigned.pop("plan_hash", None)
    if sha256(_canonical(unsigned)).hexdigest() != plan_hash:
        raise ValueError("approved recovery plan canonical hash does not match")
    if plan.get("schema_version") != "current-synthetic-profile-demo-recovery-plan-v1" or plan.get("classification") != "S2_PROFILE_DEMO_RECOVERY" or plan.get("mode") != "APPLY":
        raise ValueError("plan is outside the exact Outbox recovery boundary")
    if plan.get("source_plan") != {"plan_id":"d1f28f89-1822-54fa-a0fc-6e9334ace128", "plan_hash":"e500a6046f95e41fc13a9271f51082452bc64db5b7fe85495165cc20274de669"}:
        raise ValueError("recovery plan source does not match the interrupted plan")
    if plan.get("safety") != {"database_deletions":0,"file_deletions":0,"behavior_appends":0,"recommendation_tasks":0,"deepseek_requests":0,"neo4j_writes":0,"chroma_writes":0}:
        raise ValueError("recovery plan safety boundary differs")
    if plan.get("input_hashes") != {item:_hash(PROJECT_ROOT / item) for item in INPUTS}:
        raise ValueError("recovery inputs no longer match executable code")
    if subprocess.run(["git","merge-base","--is-ancestor",str(plan.get("git_commit","")),"HEAD"], cwd=PROJECT_ROOT, check=False).returncode != 0:
        raise ValueError("recovery plan commit is not an ancestor")
    return plan


async def _connection(values: Mapping[str,str]) -> Any:
    return await asyncmy.connect(host="127.0.0.1",port=_port(values),user=values["RECPRO_MYSQL_MIGRATION_USER"],password=values["RECPRO_MYSQL_MIGRATION_PASSWORD"],db=values["RECPRO_MYSQL_DATABASE"],autocommit=False,charset="utf8mb4")


async def apply(args: argparse.Namespace) -> dict[str, Any]:
    plan=validate(args.plan.resolve(strict=True),plan_id=args.plan_id,plan_hash=args.approved_plan_hash)
    values=read_env(args.env_file.resolve(strict=True))
    before=await reconcile(values,{"intent":{"profile_refresh_batch":{"source_event_uuid":"1a142fce-362f-5296-b698-58e734f2b422"}}})
    if before != plan["reconciliation"] or not before["ready_for_recovery"]:
        raise ValueError("recovery preconditions drifted; no Outbox may be consumed")
    worker_values=dict(values); worker_values.setdefault("RECPRO_MYSQL_HOST_PORT",str(_port(values)))
    settings=build_settings(worker_values)
    async def factory() -> Any: return await _connection(values)
    worker=build_profile_outbox_worker(settings,connection_factory=factory,worker_id="synthetic-profile-recovery-54",formula_version="profile-g2-v1",max_attempts=3,allowed_outbox_ids=(54,))
    receipts=await worker.run_once(limit=1)
    replay=await worker.run_once(limit=1)
    if len(receipts)!=1 or replay or int(receipts[0].outbox_id)!=54:
        raise RuntimeError("recovery Worker did not consume only Outbox #54 once")
    after=await reconcile(values,{"intent":{"profile_refresh_batch":{"source_event_uuid":"1a142fce-362f-5296-b698-58e734f2b422"}}})
    expected=plan["expected_deltas"]
    for table,delta in expected.items():
        if after["table_counts_before"][table]-before["table_counts_before"][table] != int(delta):
            raise RuntimeError(f"recovery observed delta differs for {table}")
    if after["outbox"]["status"] != "DONE" or after["outbox"]["attempts"] != 1 or after["profile_version_before"] != 4:
        raise RuntimeError("recovery did not reach the expected one-time terminal state")
    return {"status":"PASS","plan_id":plan["plan_id"],"outbox_id":54,"profile_version_after":4,"before_counts":before["table_counts_before"],"after_counts":after["table_counts_before"],"database_deletions":0,"behavior_appends":0,"deepseek_requests":0,"neo4j_writes":0,"chroma_writes":0}


def main(argv: Sequence[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--plan",type=Path,required=True); parser.add_argument("--plan-id",required=True); parser.add_argument("--approved-plan-hash",required=True); parser.add_argument("--env-file",type=Path,default=PROJECT_ROOT / ".env.host")
    args=parser.parse_args(argv)
    try: print(json.dumps(asyncio.run(apply(args)),ensure_ascii=False,indent=2,sort_keys=True))
    except (OSError,RuntimeError,ValueError,KeyError,TypeError,asyncmy.errors.Error,json.JSONDecodeError) as exc: print(f"[FAIL] synthetic profile-demo recovery: {type(exc).__name__}: {exc}"); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
