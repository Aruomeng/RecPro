#!/usr/bin/env python3
"""Apply one approved DeepSeek Intent Agent probe without touching storage."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from backend.app.llm.factory import build_llm_provider
from backend.app.recommendation.agents.llm_agents import LLMIntentUnderstandingAgent
from backend.app.shared_kernel.contracts.agent import AgentMessage
from backend.app.shared_kernel.contracts.enums import MessageType
from scripts.build_deepseek_intent_probe_plan import FIXTURE_TEXT, INPUTS, ROOT, SCHEMA, canonical, sha
from scripts.g4_llm_plan_policy import load_deepseek_intent_policy, policy_hash


def load(path: Path, plan_id: str, plan_hash: str) -> dict[str, Any]:
    plan=json.loads(path.resolve(strict=True).read_text()); Draft202012Validator(json.loads(SCHEMA.read_text()),format_checker=FormatChecker()).validate(plan)
    unsigned=dict(plan); unsigned.pop("plan_hash",None)
    if plan.get("plan_id")!=plan_id or plan.get("plan_hash")!=plan_hash or hashlib.sha256(canonical(unsigned)).hexdigest()!=plan_hash: raise ValueError("approved plan identity/hash mismatch")
    if subprocess.run(["git","merge-base","--is-ancestor",str(plan["git_commit"]),"HEAD"],cwd=ROOT).returncode!=0: raise ValueError("approved commit is not an ancestor")
    expected={p:sha(ROOT/p) for p in sorted(INPUTS)}
    if {k:v for k,v in plan["input_hashes"].items() if k not in {"deepseek_intent_policy","fixture"}} != expected: raise ValueError("probe code boundary changed")
    return plan


async def run(args: argparse.Namespace) -> dict[str, Any]:
    plan=load(Path(args.plan),args.plan_id,args.plan_hash); settings, policy=load_deepseek_intent_policy((ROOT/args.env_file).resolve(strict=True))
    if policy_hash(policy)!=plan["input_hashes"]["deepseek_intent_policy"]: raise ValueError("DeepSeek policy changed after approval")
    fixture={"input_text":FIXTURE_TEXT,"resource_types":["BOOK"],"expected_intents":["TOPIC_RECOMMENDATION","GENERAL_RECOMMENDATION"]}
    if hashlib.sha256(canonical(fixture)).hexdigest()!=plan["input_hashes"]["fixture"]: raise ValueError("fixed probe fixture changed")
    output=ROOT/"artifacts/verification/deepseek-intent-probe"/str(plan["request_run_id"])/"result.json"
    if output.exists(): raise ValueError("refusing to overwrite probe evidence")
    now=datetime.now(UTC); message=AgentMessage(schema_version="g4-orchestrator-v1",message_id=uuid5(NAMESPACE_URL,f"intent-probe-message:{plan['request_run_id']}"),trace_id=uuid5(NAMESPACE_URL,f"intent-probe-trace:{plan['request_run_id']}"),task_id=uuid5(NAMESPACE_URL,f"intent-probe-task:{plan['request_run_id']}"),sender="RecommendationOrchestrator",receiver="IntentUnderstandingAgent",message_type=MessageType.INTENT_RESOLVE,payload={"input_text":FIXTURE_TEXT,"resource_types":["BOOK"]},deadline_at=now+timedelta(seconds=30),attempt=1,idempotency_key=str(plan["idempotency_key"]),context_version=1,created_at=now)
    result=await LLMIntentUnderstandingAgent(build_llm_provider(settings)).handle(message)
    success=not result.fallback_used and result.agent_version=="intent-llm-prompt-v1"
    payload=result.payload if isinstance(result.payload,dict) else {}
    report={"status":"PASS" if success else "DEGRADED","mode":"APPROVED_DEEPSEEK_INTENT_PROBE","plan_id":args.plan_id,"plan_hash":args.plan_hash,"run_id":plan["request_run_id"],"agent_version":result.agent_version,"fallback_used":result.fallback_used,"warnings":list(result.warnings),"fallback_reason_code":payload.get("llm_fallback_reason_code"),"normalized_intent":payload.get("intent_type"),"provider":payload.get("llm_provider") if success else None,"prompt_id":payload.get("prompt_id") if success else None,"attempts":payload.get("llm_attempts") if success else None,"external_llm_requests_max":2,"database_writes":0,"neo4j_writes":0,"chroma_writes":0,"workspace_writes":0,"file_deletions":0,"database_physical_deletions":0,"raw_model_text_persisted":False,"checked_at":datetime.now(UTC).isoformat()}
    output.parent.mkdir(parents=True,exist_ok=False); output.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    return report | {"evidence_path":str(output.relative_to(ROOT))}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--apply",action="store_true"); parser.add_argument("--plan",required=True); parser.add_argument("--plan-id",required=True); parser.add_argument("--plan-hash",required=True); parser.add_argument("--env-file",default=".env.host"); args=parser.parse_args()
    if not args.apply: raise SystemExit("refusing to call an external model without --apply")
    print(json.dumps(asyncio.run(run(args)),ensure_ascii=False,indent=2,sort_keys=True))
