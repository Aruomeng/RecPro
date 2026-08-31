#!/usr/bin/env python3
"""Build or apply one bounded DeepSeek background-planning ChangePlan.

The program is intentionally isolated from the web application and every
persistence adapter.  ``build`` reads configuration and source files only;
``apply`` can make at most one explicit DeepSeek request after verifying the
approved plan ID/hash and a fixed, anonymous Workspace context.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from backend.app.agent_workspace.adapters.deepseek_planner import DeepSeekBackgroundPlanner
from backend.app.agent_workspace.application.background_planning import (
    DirectiveValidator,
    PlanningContextSanitizer,
)
from backend.app.agent_workspace.ports.planning import PlanningContext
from backend.app.config import AppSettings
from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from backend.app.llm.prompts import load_prompt_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
PROMPT_PATH = PROJECT_ROOT / "contracts" / "prompts" / "background-planning-prompts-v1.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CONFIRMATION = "YES_REAL_BACKGROUND_DEEPSEEK"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    value = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Git HEAD is not a full hash")
    return value


def ensure_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    if result.stdout.strip():
        raise ValueError("worktree must be clean before a model plan is frozen or applied")


def resolve_inside_root(value: Path, *, label: str, strict: bool = True) -> Path:
    path = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = path.resolve(strict=strict)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def fixed_context(run_id: str) -> tuple[PlanningContext, str]:
    """Return a deterministic anonymous context with no user or catalog IDs."""

    context = PlanningContext(
        workspace_id=uuid5(NAMESPACE_URL, f"background-planning-workspace:{run_id}"),
        session_id=uuid5(NAMESPACE_URL, f"background-planning-session:{run_id}"),
        device_id="approved-background-planning-probe",
        mode="guest",
        context_version=1,
        trigger="SESSION_STARTED",
        route="/",
        query="多智能体与智慧图书馆推荐",
        top_topics=("多智能体", "智慧图书馆", "推荐系统"),
        source_statuses={"mysql": "UP", "neo4j": "UP", "chroma": "UP", "llm": "UP"},
        external_context=(),
        personalization_enabled=False,
        profile_summary=None,
    )
    sanitized = PlanningContextSanitizer().sanitize(context)
    context_json = json.dumps(
        {
            "mode": sanitized.mode,
            "context_version": sanitized.context_version,
            "trigger": sanitized.trigger,
            "route": sanitized.route,
            "query": sanitized.query,
            "top_topics": list(sanitized.top_topics),
            "source_statuses": dict(sanitized.source_statuses),
            "external_context": list(sanitized.external_context),
            "profile_summary": None,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(context_json) > 3000:
        raise ValueError("fixed background context exceeds the prompt boundary")
    return context, context_json


def load_settings(path: Path) -> AppSettings:
    settings = AppSettings(_env_file=str(path.resolve(strict=True)))
    if settings.app_env != "demo":
        raise ValueError("real background planning is limited to the demo research runtime")
    if settings.llm_provider != "deepseek" or settings.llm_api_key is None:
        raise ValueError("real background planning requires configured DeepSeek credentials")
    if settings.llm_model != "deepseek-v4-flash":
        raise ValueError("real background planning requires deepseek-v4-flash")
    if settings.llm_timeout_seconds > 20:
        raise ValueError("real background planning timeout may not exceed 20 seconds")
    return settings


def model_policy(settings: AppSettings) -> dict[str, object]:
    return {
        "provider": "deepseek",
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_output_tokens": min(settings.llm_max_output_tokens, 256),
        "max_attempts": 1,
        "maximum_external_requests": 1,
        "prompt_bundle": PROMPT_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "prompt_version": "prompt-v3",
    }


def build_plan(*, run_id: str, llm_env_file: Path) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    ensure_clean_worktree()
    settings = load_settings(llm_env_file)
    commit = git_commit()
    _context, context_json = fixed_context(run_id)
    prompt_bytes = PROMPT_PATH.read_bytes()
    prompt_hash = sha256_bytes(prompt_bytes)
    bundle = load_prompt_bundle(PROMPT_PATH, expected_sha256=prompt_hash, expected_version="prompt-v3")
    bundle.task("workspace.background_plan")
    policy = model_policy(settings)
    request_id = uuid5(NAMESPACE_URL, f"background-planning-request:{run_id}")
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"background-planning-plan:{run_id}")),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S0_READ_ONLY",
        "mode": "DRY_RUN",
        "intent": (
            "Execute one explicit DeepSeek deepseek-v4-flash background-planning probe against "
            "a fixed anonymous Workspace context; at most one external request, no database, "
            "Neo4j, Chroma, HTTP business, filesystem mutation or Agent tool call."
        ),
        "environment": {
            "environment_id": "demo-research-background-planning",
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": "sha256:" + sha256_bytes(f"{commit}:{run_id}:background-planning".encode()),
            "database_identity": None,
            "index_namespace": None,
        },
        "targets": [
            {"kind": "GIT", "identifier": f"commit:{commit}", "operation": "READ", "expected_before_count": 1, "expected_after_min_count": 1},
            {"kind": "FILE", "identifier": PROMPT_PATH.relative_to(PROJECT_ROOT).as_posix(), "operation": "READ", "expected_before_count": 1, "expected_after_min_count": 1},
        ],
        "input_hashes": {
            "sanitized_context": sha256_bytes(context_json.encode("utf-8")),
            "prompt_bundle": prompt_hash,
            "model_policy": sha256_bytes(canonical(policy)),
            "planner_adapter": sha256_bytes((PROJECT_ROOT / "backend/app/agent_workspace/adapters/deepseek_planner.py").read_bytes()),
        },
        "idempotency_key": str(request_id),
        "request_run_id": run_id,
        "max_changes": 0,
        "preconditions": [
            "explicit approval must match this exact plan id and hash",
            "the runtime remains demo, DeepSeek model remains deepseek-v4-flash, timeout is at most 20 seconds, and max attempts is exactly one",
            "only the fixed anonymous guest Workspace context may be sent; no profile, identifier, resource ID, behavior, SQL, Cypher, prompt text or model raw response may be persisted",
            "the planner can return only directive candidates and every candidate must pass DirectiveValidator before evidence is written",
            "database writes, Neo4j writes, Chroma writes, business HTTP posts, files deleted and destructive actions must remain zero",
            "network budget is exactly one DeepSeek request; timeout, malformed output or provider failure must fail closed without retry",
        ],
        "safety_assertions": {
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "overwrite_existing": False,
            "destructive_capabilities_required": False,
            "counts_must_not_decrease": True,
        },
    }
    plan["plan_hash"] = sha256_bytes(canonical(plan))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan))
    if errors:
        raise ValueError("generated ChangePlan violates schema: " + "; ".join(error.message for error in errors))
    return plan


def validate_plan(path: Path, *, plan_id: str, plan_hash: str, run_id: str) -> dict[str, Any]:
    if not HASH_PATTERN.fullmatch(plan_hash):
        raise ValueError("approved plan hash is invalid")
    plan = json.loads(resolve_inside_root(path, label="ChangePlan").read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash:
        raise ValueError("approved plan identity does not match")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if sha256_bytes(canonical(unsigned)) != plan_hash:
        raise ValueError("ChangePlan canonical hash does not match")
    if plan.get("classification") != "S0_READ_ONLY" or plan.get("mode") != "DRY_RUN" or plan.get("max_changes") != 0:
        raise ValueError("ChangePlan is not the bounded background-planning shape")
    if plan.get("request_run_id") != run_id or plan.get("idempotency_key") != str(uuid5(NAMESPACE_URL, f"background-planning-request:{run_id}")):
        raise ValueError("ChangePlan run identity does not match")
    ensure_clean_worktree()
    if plan.get("git_commit") != git_commit():
        raise ValueError("runtime code changed after the reviewed plan")
    adapter_hash = sha256_bytes((PROJECT_ROOT / "backend/app/agent_workspace/adapters/deepseek_planner.py").read_bytes())
    if plan.get("input_hashes", {}).get("planner_adapter") != adapter_hash:
        raise ValueError("background planner adapter differs from the approved plan")
    return plan


async def apply_plan(*, plan: Mapping[str, Any], run_id: str, llm_env_file: Path) -> dict[str, Any]:
    settings = load_settings(llm_env_file)
    context, context_json = fixed_context(run_id)
    policy = model_policy(settings)
    if sha256_bytes(context_json.encode("utf-8")) != plan["input_hashes"]["sanitized_context"]:
        raise ValueError("fixed sanitized context differs from the approved plan")
    if sha256_bytes(canonical(policy)) != plan["input_hashes"]["model_policy"]:
        raise ValueError("DeepSeek policy differs from the approved plan")
    prompt_hash = sha256_bytes(PROMPT_PATH.read_bytes())
    if prompt_hash != plan["input_hashes"]["prompt_bundle"]:
        raise ValueError("prompt bundle differs from the approved plan")
    bundle = load_prompt_bundle(PROMPT_PATH, expected_sha256=prompt_hash, expected_version="prompt-v3")
    provider = DeepSeekLLMProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=min(settings.llm_max_output_tokens, 256),
        max_attempts=1,
        prompt_version=bundle.bundle_version,
        prompt_bundle=bundle,
    )
    result = await DeepSeekBackgroundPlanner(provider).plan(PlanningContextSanitizer().sanitize(context))
    directives = DirectiveValidator().validate(result.directives)
    return {
        "provider": result.provider,
        "model": result.model,
        "model_requests": result.model_requests,
        "directive_count": len(directives),
        "directives": [
            {"type": item.directive_type, "behavior": item.behavior, "reason_code": item.reason_code, "confidence": item.confidence}
            for item in directives
        ],
    }


def artifact_path(run_id: str) -> Path:
    return PROJECT_ROOT / "artifacts" / "verification" / "background-planning" / run_id / "apply.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--run-id", required=True)
    build.add_argument("--llm-env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    apply = subparsers.add_parser("apply")
    apply.add_argument("--apply", action="store_true", required=True)
    apply.add_argument("--run-id", required=True)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--plan-id", required=True)
    apply.add_argument("--approved-plan-hash", required=True)
    apply.add_argument("--confirm-external-llm", required=True)
    apply.add_argument("--llm-env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            plan = build_plan(run_id=args.run_id, llm_env_file=args.llm_env_file)
            output = artifact_path(args.run_id).with_name("change-plan.json")
            output.parent.mkdir(parents=True, exist_ok=False)
            output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({"status": "PLAN_PENDING_APPROVAL", "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "path": str(output)}, ensure_ascii=False))
            return 0
        if args.confirm_external_llm != CONFIRMATION:
            raise ValueError("exact external LLM confirmation is required")
        plan = validate_plan(args.plan, plan_id=args.plan_id, plan_hash=args.approved_plan_hash, run_id=args.run_id)
        output = artifact_path(args.run_id)
        if output.exists():
            raise FileExistsError("apply artifact already exists")
        # ``build`` already creates this run directory for ``change-plan.json``.
        # The receipt itself remains single-write protected by ``output.exists``
        # above; allowing the existing parent prevents a successful model call
        # from losing its evidence solely because the reviewed plan is present.
        output.parent.mkdir(parents=True, exist_ok=True)
        outcome = asyncio.run(apply_plan(plan=plan, run_id=args.run_id, llm_env_file=args.llm_env_file))
        evidence = {
            "schema_version": "background-planning-deepseek-apply-v1",
            "status": "PASS",
            "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "run_id": args.run_id,
            "git_commit": plan["git_commit"], "outcome": outcome,
            "database_writes": 0, "neo4j_writes": 0, "chroma_writes": 0,
            "business_posts": 0, "external_llm_requests": 1,
            "files_deleted": 0, "database_physical_deletions": 0,
        }
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
