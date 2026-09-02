#!/usr/bin/env python3
"""Freeze a no-database ChangePlan for one bounded Intent Agent probe."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from scripts.g4_llm_plan_policy import load_deepseek_intent_policy, policy_hash


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts/safety/change-plan.schema.json"
INPUTS = (
    "backend/app/config.py", "backend/app/llm/adapters/deepseek.py",
    "backend/app/llm/prompts.py", "backend/app/recommendation/agents/llm_agents.py",
    "contracts/prompts/rec-prompts-v1.0.1.json", "scripts/g4_llm_plan_policy.py",
    "scripts/build_deepseek_intent_probe_plan.py", "scripts/execute_deepseek_intent_probe.py",
)
FIXTURE_TEXT = "多智能体、知识图谱与智慧图书馆"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def head() -> str:
    value = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None: raise ValueError("invalid Git commit")
    return value


def clean() -> None:
    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip():
        raise ValueError("worktree must be clean before freezing an external-call plan")


def build(run_id: str, env_file: Path) -> dict[str, Any]:
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", run_id) is None: raise ValueError("run id is invalid")
    clean(); commit = head(); _, policy = load_deepseek_intent_policy(env_file)
    fixture = {"input_text": FIXTURE_TEXT, "resource_types": ["BOOK"], "expected_intents": ["TOPIC_RECOMMENDATION", "GENERAL_RECOMMENDATION"]}
    plan: dict[str, Any] = {
        "schema_version":"1.0.0", "plan_id":str(uuid5(NAMESPACE_URL, f"deepseek-intent-probe:{commit}:{run_id}")),
        "created_at":datetime.now(UTC).isoformat().replace("+00:00","Z"), "git_commit":commit,
        "classification":"S0_READ_ONLY", "mode":"APPLY",
        "intent":"Run one direct, non-sensitive IntentUnderstandingAgent probe against the configured DeepSeek deepseek-v4-flash capability to distinguish a real provider failure from a rule fallback. The probe never constructs a recommendation task or opens MySQL, Neo4j, Chroma, Workspace, feedback, or profile ports.",
        "environment":{"environment_id":"recpro-local-deepseek-intent-probe", "workspace":str(ROOT), "host_fingerprint":"sha256:"+hashlib.sha256(f"{commit}:{run_id}:deepseek-intent".encode()).hexdigest(), "database_identity":None, "index_namespace":None},
        "targets":[
            {"kind":"FILE","identifier":f"artifacts/verification/deepseek-intent-probe/{run_id}/result.json","operation":"CREATE","expected_before_count":0,"expected_after_min_count":1},
            {"kind":"GIT","identifier":commit,"operation":"READ","expected_before_count":1,"expected_after_min_count":1},
        ],
        "input_hashes":{path:sha(ROOT/path) for path in sorted(INPUTS)} | {"deepseek_intent_policy":policy_hash(policy), "fixture":hashlib.sha256(canonical(fixture)).hexdigest()},
        "idempotency_key":str(uuid5(NAMESPACE_URL,f"deepseek-intent-probe-key:{run_id}")), "request_run_id":run_id,
        "max_changes":0,
        "preconditions":[
            "The user approves this exact plan identity before its external model request.",
            "The configured provider is DeepSeek, model is deepseek-v4-flash, and the capability is intent.classify.",
            "Only the fixed non-sensitive text is provided to the agent; no account, identifier, profile, recommendation result, graph data, SQL, Cypher, prompt output, or credential is transmitted or persisted.",
            "The adapter may make at most two provider attempts for this one Intent Agent invocation; raw model response is never written to evidence.",
            "All database, graph, vector, Workspace, feedback, behavior, profile, outbox, container, volume, deletion, and overwrite counts remain zero.",
        ],
        "safety_assertions":{"file_deletions":0,"database_physical_deletions":0,"overwrite_existing":False,"destructive_capabilities_required":False,"counts_must_not_decrease":True},
    }
    plan["plan_hash"]=hashlib.sha256(canonical(plan)).hexdigest()
    Draft202012Validator(json.loads(SCHEMA.read_text()), format_checker=FormatChecker()).validate(plan)
    return plan


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--run-id",required=True); parser.add_argument("--env-file",default=".env.host"); parser.add_argument("--output",required=True); args=parser.parse_args()
    value=build(args.run_id,(ROOT/args.env_file).resolve(strict=True)); output=(ROOT/args.output).resolve(); output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf-8") as h: json.dump(value,h,ensure_ascii=False,indent=2,sort_keys=True); h.write("\n")
    print(json.dumps({"status":"PASS","mode":"NO_DATABASE_PLAN_BUILD","plan_id":value["plan_id"],"plan_hash":value["plan_hash"],"path":str(output.relative_to(ROOT)),"database_writes":0,"deepseek_requests":0},ensure_ascii=False,indent=2))
