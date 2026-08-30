#!/usr/bin/env python3
"""Build a zero-write successor plan for the six browser scenarios.

This builder freezes identities and budgets but never opens a database, sends a
business request, calls DeepSeek, or starts/stops a service.  Applying any
scenario requires a new exact ChangePlan because the current document is only
the approval boundary for a later controlled run.
"""

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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
COMPOSE_PROJECT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
SCENARIOS = (
    ("demo_cold", "cold_exploration", "READ_ONLY", ("overview", "graph", "resource")),
    ("demo_clear", "clear_recommendation", "BUSINESS_APPEND_REQUIRED", ("recommendation", "sse", "replay")),
    ("demo_topic", "topic_evidence", "BUSINESS_APPEND_REQUIRED", ("recommendation", "graph_path", "replay")),
    ("demo_path", "reading_path", "BUSINESS_APPEND_REQUIRED", ("recommendation", "reading_path", "replay")),
    ("demo_negative", "negative_feedback", "BUSINESS_APPEND_REQUIRED", ("impression", "feedback", "outbox")),
    ("demo_degraded", "dependency_degradation", "READ_ONLY_FAULT_INJECTION", ("readiness", "fault_injection", "replay")),
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("current Git commit is not a full SHA")
    return commit


def require_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        raise ValueError("working tree must be clean before freezing the successor plan")


def _scenario(run_id: str, fixture_user: str, scenario_id: str, mode: str, actions: tuple[str, ...]) -> dict[str, Any]:
    namespace = f"recpro:stage4:{run_id}:{scenario_id}"
    return {
        "scenario_id": scenario_id,
        "fixture_user": fixture_user,
        "execution_mode": mode,
        "request_uuid": str(uuid5(NAMESPACE_URL, namespace + ":request")),
        "session_uuid": str(uuid5(NAMESPACE_URL, namespace + ":session")),
        "workspace_uuid": str(uuid5(NAMESPACE_URL, namespace + ":workspace")),
        "actions": list(actions),
        "required_evidence": [
            "request_response_contract",
            "SSE_sequence_and_agent_states",
            "DOM_and_screenshot_assertions",
            "before_after_database_counts",
            "idempotent_replay_delta",
        ],
        "dry_run_budget": {
            "database_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "outbox_claims": 0,
            "external_llm_requests": 0,
            "network_requests": 0,
        },
        "apply_requires_new_plan": mode == "BUSINESS_APPEND_REQUIRED",
    }


def build_plan(*, run_id: str, compose_project: str, created_at: str, graph_version: str = "lib-books-v2-20260828") -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use lowercase letters, digits, and hyphens")
    if COMPOSE_PROJECT_PATTERN.fullmatch(compose_project) is None:
        raise ValueError("compose project must be lowercase and safe")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must contain a timezone")
    require_clean_worktree()
    commit = current_commit()
    matrix_path = PROJECT_ROOT / "docs" / "acceptance_matrix.md"
    plan: dict[str, Any] = {
        "schema_version": "recpro-stage4-browser-successor-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"recpro:stage4-browser-successor:{commit}:{run_id}")),
        "created_at": parsed.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S3_BROWSER_SCENARIO_SUCCESSOR",
        "mode": "DRY_RUN",
        "intent": "Freeze six browser scenarios and exact identities for a later approved run; perform no business write, model request, infrastructure change, or deletion.",
        "environment": {
            "compose_project": compose_project,
            "mysql_database": "recpro",
            "graph_version": graph_version,
            "vector_index_version": "lib-books-vector-v1-20260811",
            "llm_provider": "deepseek",
            "llm_model": "deepseek-v4-flash",
            "background_planning": "DISABLED",
        },
        "fixed_identities": {
            "guest_user_id": 9000001,
            "demo_profile_user_id": 1001,
            "real_account_ids": [],
            "new_account_ids": [],
        },
        "scenarios": [
            _scenario(run_id, fixture, scenario, mode, actions)
            for fixture, scenario, mode, actions in SCENARIOS
        ],
        "aggregate_budget": {
            "database_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "outbox_claims": 0,
            "external_llm_requests": 0,
            "network_requests": 0,
            "files_deleted": 0,
            "database_physical_deletions": 0,
            "container_deletions": 0,
            "volume_deletions": 0,
        },
        "input_hashes": {
            "docs/acceptance_matrix.md": sha256_file(matrix_path),
            "backend/app/agent_workspace/runtime.py": sha256_file(PROJECT_ROOT / "backend/app/agent_workspace/runtime.py"),
            "backend/app/api/recommendation.py": sha256_file(PROJECT_ROOT / "backend/app/api/recommendation.py"),
            "scripts/build_stage4_browser_successor_plan.py": sha256_file(PROJECT_ROOT / "scripts/build_stage4_browser_successor_plan.py"),
        },
        "preconditions": [
            "the user approves this exact plan_id and plan_hash before any business POST or model request",
            "current Git commit and all input hashes remain unchanged at execution",
            "six request/session/workspace UUID triples are unused and are checked read-only before each run",
            "each apply scenario gets a successor plan with exact MySQL append rows and DeepSeek budget",
            "background planning remains disabled during the browser run",
            "failure is forward-only; no compensating delete, truncate, drop, overwrite, container removal, or volume removal is allowed",
        ],
        "safety_assertions": {
            "business_writes_authorized": False,
            "deepseek_requests_authorized": False,
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "container_deletions": 0,
            "volume_deletions": 0,
            "artifact_overwrites": 0,
        },
        "status": "READY_FOR_EXPLICIT_APPROVAL",
    }
    plan["plan_hash"] = hashlib.sha256(canonical(plan)).hexdigest()
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--created-at", default="2026-08-30T00:00:00Z")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        plan = build_plan(run_id=args.run_id, compose_project=args.compose_project, created_at=args.created_at)
        output = args.output or PROJECT_ROOT / "plans" / f"stage4-browser-successor-{args.run_id}.json"
        output = (output if output.is_absolute() else PROJECT_ROOT / output).resolve(strict=False)
        try:
            output.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise ValueError("output must resolve inside the repository") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        print(json.dumps({"status": "PASS", "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "git_commit": plan["git_commit"], "path": output.relative_to(PROJECT_ROOT).as_posix(), "database_writes": 0, "external_llm_requests": 0, "files_deleted": 0, "database_physical_deletions": 0}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
