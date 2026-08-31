#!/usr/bin/env python3
"""Build/apply one bounded DeepSeek Workspace runtime acceptance probe.

The probe creates only an in-memory anonymous Workspace, sends one public
``SESSION_STARTED`` observation, and verifies the real Agent event chain. It
does not construct a catalog, open a database connection, or invoke any
business write service.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.agent_workspace import AgentWorkspaceBroker, BackgroundPlanningCoordinator
from backend.app.agent_workspace.adapters.deepseek_planner import DeepSeekBackgroundPlanner
from backend.app.config import AppSettings
from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from backend.app.llm.prompts import load_prompt_bundle
from backend.app.main import create_app


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts/safety/change-plan.schema.json"
PROMPT = ROOT / "contracts/prompts/background-planning-prompts-v1.json"
RUN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
CONFIRMATION = "YES_REAL_BACKGROUND_DEEPSEEK_RUNTIME"
GUEST_ID = 9_000_001


class RuntimeProbeFailure(RuntimeError):
    """A public, redacted runtime outcome that did not meet acceptance."""

    def __init__(self, outcome: Mapping[str, object]) -> None:
        super().__init__("runtime background planner did not reach PLANNED")
        self.outcome = dict(outcome)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True)
    value = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Git HEAD is invalid")
    return value


def clean() -> None:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True)
    if result.stdout.strip():
        raise ValueError("worktree must be clean")


def load_settings(env_file: Path) -> AppSettings:
    settings = AppSettings(_env_file=str(env_file.resolve(strict=True)))
    if settings.app_env != "demo" or settings.llm_provider != "deepseek" or settings.llm_api_key is None:
        raise ValueError("runtime probe requires demo DeepSeek configuration")
    if settings.llm_model != "deepseek-v4-flash" or settings.llm_timeout_seconds > 20:
        raise ValueError("runtime probe model policy is not approved")
    return settings


def policy(settings: AppSettings) -> dict[str, object]:
    return {
        "provider": "deepseek", "model": settings.llm_model, "base_url": settings.llm_base_url,
        "timeout_seconds": settings.llm_timeout_seconds, "max_output_tokens": min(settings.llm_max_output_tokens, 256),
        "max_attempts": 1, "maximum_external_requests": 1, "prompt_version": "prompt-v3",
        "planner_budget": {"per_session": 3, "minimum_interval_seconds": 600, "per_device_day": 12},
    }


def identities(run_id: str) -> dict[str, str]:
    return {
        "session_id": str(uuid5(NAMESPACE_URL, f"background-runtime-session:{run_id}")),
        "workspace_request_id": str(uuid5(NAMESPACE_URL, f"background-runtime-workspace:{run_id}")),
        "observation_id": str(uuid5(NAMESPACE_URL, f"background-runtime-observation:{run_id}")),
        "device_id": "background-runtime-probe",
    }


def code_hashes() -> dict[str, str]:
    paths = {
        "planner_adapter": "backend/app/agent_workspace/adapters/deepseek_planner.py",
        "workspace_runtime": "backend/app/agent_workspace/runtime.py",
        "workspace_api": "backend/app/api/agent_workspaces.py",
        "deepseek_adapter": "backend/app/llm/adapters/deepseek.py",
        "prompt_bundle": "contracts/prompts/background-planning-prompts-v1.json",
    }
    return {key: digest((ROOT / path).read_bytes()) for key, path in paths.items()}


def artifact(run_id: str, name: str) -> Path:
    return ROOT / "artifacts/verification/background-planning" / run_id / name


def build(*, run_id: str, env_file: Path) -> dict[str, Any]:
    if RUN.fullmatch(run_id) is None:
        raise ValueError("invalid run id")
    clean()
    settings = load_settings(env_file)
    current = commit()
    identities_value = identities(run_id)
    policy_value = policy(settings)
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"background-runtime-plan:{run_id}")),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_commit": current,
        "classification": "S0_READ_ONLY",
        "mode": "DRY_RUN",
        "intent": "Execute one DeepSeek background-planning request through an in-memory anonymous Workspace SESSION_STARTED event and verify public Agent events; no persistence adapters or business services are composed.",
        "environment": {"environment_id": "demo-research-workspace-runtime", "workspace": str(ROOT), "host_fingerprint": "sha256:" + digest(f"{current}:{run_id}:workspace-runtime".encode()), "database_identity": None, "index_namespace": None},
        "targets": [
            {"kind": "GIT", "identifier": f"commit:{current}", "operation": "READ", "expected_before_count": 1, "expected_after_min_count": 1},
            {"kind": "FILE", "identifier": "contracts/prompts/background-planning-prompts-v1.json", "operation": "READ", "expected_before_count": 1, "expected_after_min_count": 1},
        ],
        "input_hashes": {"model_policy": digest(canonical(policy_value)), "identities": digest(canonical(identities_value)), **code_hashes()},
        "idempotency_key": identities_value["observation_id"],
        "request_run_id": run_id,
        "max_changes": 0,
        "preconditions": [
            "exact plan id/hash approval is required", "exactly one DeepSeek request and no retries",
            "only fixed anonymous guest context is sent", "only public Agent event metadata is persisted as evidence",
            "MySQL, Neo4j, Chroma, catalog, feedback, behavior, audit and business HTTP write services are not constructed",
            "the create request is the only in-memory Workspace POST; it emits the single implicit SESSION_STARTED observation",
        ],
        "safety_assertions": {"file_deletions": 0, "database_physical_deletions": 0, "overwrite_existing": False, "destructive_capabilities_required": False, "counts_must_not_decrease": True},
    }
    plan["plan_hash"] = digest(canonical(plan))
    errors = list(Draft202012Validator(json.loads(SCHEMA.read_text()), format_checker=FormatChecker()).iter_errors(plan))
    if errors:
        raise ValueError("invalid ChangePlan: " + "; ".join(error.message for error in errors))
    return plan


def validate(path: Path, *, plan_id: str, plan_hash: str, run_id: str) -> dict[str, Any]:
    if HASH.fullmatch(plan_hash) is None:
        raise ValueError("invalid plan hash")
    plan = json.loads(path.resolve(strict=True).read_text())
    unsigned = dict(plan); unsigned.pop("plan_hash", None)
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash or digest(canonical(unsigned)) != plan_hash:
        raise ValueError("approved plan identity does not match")
    if plan.get("request_run_id") != run_id or plan.get("git_commit") != commit():
        raise ValueError("run identity or reviewed code differs")
    if plan.get("input_hashes") != {"model_policy": plan["input_hashes"]["model_policy"], "identities": plan["input_hashes"]["identities"], **code_hashes()}:
        raise ValueError("runtime code differs from reviewed plan")
    clean()
    return plan


def execute(*, plan: Mapping[str, Any], run_id: str, env_file: Path) -> dict[str, object]:
    settings = load_settings(env_file)
    ids = identities(run_id)
    if digest(canonical(ids)) != plan["input_hashes"]["identities"] or digest(canonical(policy(settings))) != plan["input_hashes"]["model_policy"]:
        raise ValueError("runtime policy differs from reviewed plan")
    bundle = load_prompt_bundle(PROMPT, expected_version="prompt-v3")
    provider = DeepSeekLLMProvider(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model, timeout_seconds=settings.llm_timeout_seconds, max_output_tokens=min(settings.llm_max_output_tokens, 256), max_attempts=1, prompt_version=bundle.bundle_version, prompt_bundle=bundle)
    broker = AgentWorkspaceBroker(background_planner=BackgroundPlanningCoordinator(planner=DeepSeekBackgroundPlanner(provider)))
    probe_settings = AppSettings(app_env="demo", mysql_password="runtime-probe-no-database-password")
    app = create_app(settings=probe_settings, agent_workspace_broker=broker, managed_resources=(broker,))
    logging.disable(logging.INFO)
    try:
      with TestClient(app) as client:
        created = client.post("/api/v1/agent-workspaces", json={"session_id": ids["session_id"], "mode": "guest", "device_id": ids["device_id"]})
        if created.status_code != 202:
            raise RuntimeError("in-memory workspace create failed")
        workspace_id = created.json()["workspace"]["workspace_id"]
        # ``AgentWorkspaceBroker.create`` deliberately emits the first
        # SESSION_STARTED observation itself. Do not post a duplicate event:
        # the production ten-minute budget must reject that duplicate too.
        deadline = time.monotonic() + settings.llm_timeout_seconds + 3
        snapshot: Mapping[str, object] | None = None
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/agent-workspaces/{workspace_id}")
            if response.status_code != 200:
                raise RuntimeError("in-memory workspace snapshot failed")
            snapshot = response.json()
            background = snapshot.get("context_summary", {}).get("background_planning", {})
            if isinstance(background, Mapping) and background.get("status") in {"PLANNED", "DEGRADED", "FAILED"}:
                break
            time.sleep(0.2)
        if snapshot is None:
            raise RuntimeError("runtime planner did not produce a snapshot")
        background = snapshot["context_summary"].get("background_planning", {})
        events = snapshot.get("recent_events", [])
        event_types = [item.get("event_type") for item in events if isinstance(item, Mapping)]
        outcome = {
            "workspace_id": workspace_id,
            "background_status": background.get("status") if isinstance(background, Mapping) else "MISSING",
            "reason_code": background.get("reason_code") if isinstance(background, Mapping) else "BACKGROUND_OUTCOME_MISSING",
            "provider": background.get("provider") if isinstance(background, Mapping) else "unknown",
            "model": background.get("model") if isinstance(background, Mapping) else "unknown",
            "model_requests": background.get("model_requests") if isinstance(background, Mapping) else 0,
            "directive_count": background.get("directive_count") if isinstance(background, Mapping) else 0,
            "event_types": event_types[-16:],
        }
        if outcome["background_status"] != "PLANNED" or outcome["model_requests"] != 1 or "AGENT_STARTED" not in event_types or "AGENT_COMPLETED" not in event_types:
            raise RuntimeProbeFailure(outcome)
        return outcome
    finally:
      logging.disable(logging.NOTSET)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build"); build_parser.add_argument("--run-id", required=True); build_parser.add_argument("--llm-env-file", type=Path, default=ROOT / ".env.host")
    apply = sub.add_parser("apply"); apply.add_argument("--apply", action="store_true", required=True); apply.add_argument("--run-id", required=True); apply.add_argument("--plan", type=Path, required=True); apply.add_argument("--plan-id", required=True); apply.add_argument("--approved-plan-hash", required=True); apply.add_argument("--confirm-external-llm", required=True); apply.add_argument("--llm-env-file", type=Path, default=ROOT / ".env.host")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            plan = build(run_id=args.run_id, env_file=args.llm_env_file); output = artifact(args.run_id, "runtime-change-plan.json")
            output.parent.mkdir(parents=True, exist_ok=False); output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"status": "PLAN_PENDING_APPROVAL", "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "path": str(output)}, ensure_ascii=False)); return 0
        if args.confirm_external_llm != CONFIRMATION:
            raise ValueError("exact external LLM confirmation is required")
        plan = validate(args.plan, plan_id=args.plan_id, plan_hash=args.approved_plan_hash, run_id=args.run_id)
        output = artifact(args.run_id, "runtime-apply.json")
        if output.exists(): raise FileExistsError("runtime apply receipt already exists")
        output.parent.mkdir(parents=True, exist_ok=True)
        outcome = execute(plan=plan, run_id=args.run_id, env_file=args.llm_env_file)
        evidence = {"schema_version": "background-planning-runtime-apply-v1", "status": "PASS", "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "run_id": args.run_id, "git_commit": plan["git_commit"], "outcome": outcome, "external_llm_requests": 1, "in_memory_workspace_creates": 1, "implicit_session_started_observations": 1, "in_memory_workspace_observation_posts": 0, "database_writes": 0, "neo4j_writes": 0, "chroma_writes": 0, "business_posts": 0, "files_deleted": 0, "database_physical_deletions": 0}
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"); print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    except RuntimeProbeFailure as exc:
        output = artifact(args.run_id, "runtime-apply.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            evidence = {"schema_version": "background-planning-runtime-apply-v1", "status": "FAIL", "plan_id": args.plan_id, "plan_hash": args.approved_plan_hash, "run_id": args.run_id, "failure": exc.outcome, "external_llm_requests": 1, "database_writes": 0, "neo4j_writes": 0, "chroma_writes": 0, "business_posts": 0, "files_deleted": 0, "database_physical_deletions": 0}
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"status": "FAIL", "error": "RuntimeProbeFailure"}, ensure_ascii=False)); return 1
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, ensure_ascii=False)); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
