#!/usr/bin/env python3
"""Apply one approved host-local MySQL personalized recommendation plan."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence

from fastapi.testclient import TestClient

from backend.app.composition import build_demo_mysql_http_app
from scripts.build_host_personalized_recommendation_plan import INPUTS, PROJECT_ROOT, _canonical
from scripts.validate_runtime_env import read_env
from scripts.verify_g7_mysql_http_readonly import build_settings, read_snapshot
from scripts.verify_host_recommendation_readiness import _profile


def _hash(path: Path) -> str: return sha256(path.read_bytes()).hexdigest()


def validate(path: Path, *, plan_id: str, plan_hash: str) -> dict[str, Any]:
    plan=json.loads(path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash: raise ValueError("approved plan identity does not match")
    unsigned=dict(plan); unsigned.pop("plan_hash",None)
    if sha256(_canonical(unsigned)).hexdigest()!=plan_hash: raise ValueError("approved plan canonical hash does not match")
    if plan.get("schema_version")!="host-personalized-recommendation-plan-v1" or plan.get("classification")!="S1_PERSONALIZED_RECOMMENDATION_APPEND" or plan.get("mode")!="APPLY": raise ValueError("plan is outside the personalized recommendation boundary")
    if plan.get("request",{}).get("user_id")!=1002 or plan.get("baseline",{}).get("profile_version")!=4: raise ValueError("plan does not bind user 1002 profile version 4")
    if plan.get("safety")!={"database_deletions":0,"file_deletions":0,"deepseek_requests":0,"neo4j_writes":0,"chroma_writes":0,"profile_updates":0,"behavior_writes":0,"feedback_writes":0}: raise ValueError("plan safety boundary differs")
    if plan.get("input_hashes")!={item:_hash(PROJECT_ROOT/item) for item in INPUTS}: raise ValueError("plan inputs no longer match executable code")
    if subprocess.run(["git","merge-base","--is-ancestor",str(plan.get("git_commit","")),"HEAD"],cwd=PROJECT_ROOT,check=False).returncode!=0: raise ValueError("plan commit is not an ancestor")
    return plan


async def apply(args: argparse.Namespace) -> dict[str, Any]:
    plan=validate(args.plan.resolve(strict=True),plan_id=args.plan_id,plan_hash=args.approved_plan_hash)
    values=read_env(args.env_file.resolve(strict=True)); runtime=dict(values); runtime.setdefault("RECPRO_MYSQL_HOST_PORT",runtime["RECPRO_MYSQL_PORT"])
    before=await read_snapshot(runtime); profile=await _profile(runtime,1002)
    if before!=plan["baseline"]["counts"] or profile is None or profile["profile_version"]!=4: raise ValueError("recommendation baseline or profile drifted")
    application=build_demo_mysql_http_app(build_settings(runtime)); request=plan["request"]; headers={"Accept":"application/json","Content-Type":"application/json","Idempotency-Key":request["request_id"],"X-Demo-User-Id":"1002"}
    with TestClient(application) as client:
        ready=client.get("/api/v1/health/ready")
        if ready.status_code!=200 or ready.json().get("can_recommend") is not True: raise RuntimeError("host recommendation readiness is unavailable")
        first=client.post("/api/v1/recommendation-tasks",json=request,headers=headers)
        after_first=await read_snapshot(runtime)
        replay=client.post("/api/v1/recommendation-tasks",json=request,headers=headers)
        after_replay=await read_snapshot(runtime)
    if first.status_code!=201 or first.headers.get("Idempotency-Replayed")!="false": raise RuntimeError("first personalized recommendation was not accepted exactly once")
    if replay.status_code!=200 or replay.headers.get("Idempotency-Replayed")!="true" or replay.json().get("task_id")!=first.json().get("task_id"): raise RuntimeError("idempotency replay was not exact")
    if after_first!=after_replay: raise RuntimeError("idempotency replay changed table counts")
    for target in plan["targets"]:
        table=target["identifier"].rsplit(".",1)[-1]; delta=after_first[table]-before[table]
        if not int(target["min_rows"])<=delta<=int(target["max_rows"]): raise RuntimeError(f"recommendation delta out of bound for {table}")
    return {"status":"PASS","plan_id":plan["plan_id"],"task_id":first.json().get("task_id"),"record_id":first.json().get("record_id"),"result_status":first.json().get("status"),"item_count":len(first.json().get("items",[])),"before_counts":before,"after_counts":after_first,"deepseek_requests":0,"neo4j_writes":0,"chroma_writes":0,"database_deletions":0}


def main(argv: Sequence[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--plan",type=Path,required=True); parser.add_argument("--plan-id",required=True); parser.add_argument("--approved-plan-hash",required=True); parser.add_argument("--env-file",type=Path,default=PROJECT_ROOT/".env.host")
    args=parser.parse_args(argv)
    try: print(json.dumps(asyncio.run(apply(args)),ensure_ascii=False,indent=2,sort_keys=True))
    except Exception as exc: print(f"[FAIL] host personalized recommendation: {type(exc).__name__}: {exc}"); return 1
    return 0


if __name__=="__main__": raise SystemExit(main())
