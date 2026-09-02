#!/usr/bin/env python3
"""Build the exact append-only plan for the G8 cold guided scenario.

The aggregate browser plan is only a frozen budget and never authorizes
business writes.  This builder narrows that budget to one verified request,
one stable idempotency key, and the 19 rows proven by the read-only rehearsal.
It performs no database connection and cannot apply the plan.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
CONFIG_PATH = PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SCENARIO_ID = "cold_user_guided"
EXPECTED_STATUS = "WAITING_CLARIFICATION"
EXPECTED_DISPATCH_COUNT = 4
EXPECTED_TRANSITION_COUNT = 4
EXPECTED_DELTAS = {
    "recommendation_task": 1,
    "recommendation_task_transition": 4,
    "recommendation_policy_decision": 1,
    "recommendation_trace": 1,
    "recommendation_task_context": 1,
    "recommendation_clarification": 1,
    "recommendation_agent_message": 4,
    "recommendation_agent_result": 4,
    "recommendation_agent_artifact": 1,
    "recommendation_orchestration_result": 1,
}


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def resolve_inside_project(path: Path, *, label: str) -> Path:
    resolved = (path if path.is_absolute() else PROJECT_ROOT / path).resolve(strict=True)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("git HEAD is not a full commit hash")
    return commit


def require_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise ValueError("working tree must be clean before freezing a cold guided plan")


def load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes, Path]:
    resolved = resolve_inside_project(path, label=label)
    raw = resolved.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value, raw, resolved


def load_evidence(path: Path) -> tuple[dict[str, Any], bytes, Path]:
    evidence, raw, resolved = load_json(path, label="cold guided read-only evidence")
    if evidence.get("schema_version") != "g8-cold-user-guided-readonly-evidence-v1":
        raise ValueError("unsupported cold guided evidence schema")
    if evidence.get("status") != "PASS" or evidence.get("scenario_id") != SCENARIO_ID:
        raise ValueError("cold guided evidence must be a PASS cold_user_guided object")
    if evidence.get("orchestration_status") != EXPECTED_STATUS:
        raise ValueError("cold guided evidence did not reach WAITING_CLARIFICATION")
    if evidence.get("dispatch_count") != EXPECTED_DISPATCH_COUNT:
        raise ValueError("cold guided evidence does not prove four Agent dispatches")
    if evidence.get("transition_count") != EXPECTED_TRANSITION_COUNT:
        raise ValueError("cold guided evidence does not prove four state transitions")
    before = evidence.get("before_counts")
    after = evidence.get("after_counts")
    if not isinstance(before, dict) or before != after:
        raise ValueError("cold guided evidence counts are not stable")
    for table, delta in EXPECTED_DELTAS.items():
        if table not in before:
            raise ValueError(f"cold guided evidence is missing {table}")
        if isinstance(before[table], bool) or not isinstance(before[table], int) or before[table] < 0:
            raise ValueError(f"cold guided evidence count is invalid for {table}")
    safety = evidence.get("safety")
    if not isinstance(safety, dict):
        raise ValueError("cold guided evidence is missing safety counters")
    zero_keys = (
        "mysql_writes",
        "neo4j_writes",
        "chroma_writes",
        "external_llm_requests",
        "external_requests",
        "outbox_claims",
        "actual_delete_count",
        "files_deleted",
        "overwritten_inputs",
    )
    if any(int(safety.get(key, -1)) != 0 for key in zero_keys):
        raise ValueError("cold guided evidence is not zero-side-effect")
    request = evidence.get("request_payload")
    if not isinstance(request, dict) or not HASH_PATTERN.fullmatch(str(evidence.get("request_payload_sha256", ""))):
        raise ValueError("cold guided evidence has no request payload hash")
    if sha256_bytes(canonical(request)) != str(evidence["request_payload_sha256"]):
        raise ValueError("cold guided request payload hash is invalid")
    return evidence, raw, resolved


def load_browser_plan(path: Path, *, current_commit: str, evidence: Mapping[str, Any]) -> tuple[dict[str, Any], bytes, Path]:
    plan, raw, resolved = load_json(path, label="aggregate browser scenario plan")
    if plan.get("schema_version") != "g8-browser-scenario-plan-v1":
        raise ValueError("unsupported aggregate browser plan schema")
    if plan.get("mode") != "DRY_RUN" or plan.get("executor_status") != "READY_FOR_EXPLICIT_APPROVAL":
        raise ValueError("aggregate browser plan is not a review-only freeze")
    if plan.get("git_commit") != current_commit:
        raise ValueError("aggregate browser plan is bound to a different Git commit")
    if plan.get("environment", {}).get("compose_project") != evidence.get("compose_project"):
        raise ValueError("aggregate browser plan Compose project differs from evidence")
    scenarios = plan.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("aggregate browser plan has no scenarios")
    matches = [item for item in scenarios if isinstance(item, dict) and item.get("scenario_id") == SCENARIO_ID]
    if len(matches) != 1:
        raise ValueError("aggregate browser plan must contain exactly one cold_user_guided scenario")
    scenario = matches[0]
    expected = scenario.get("expected", {})
    if expected.get("status") != EXPECTED_STATUS or int(expected.get("minimum_items", -1)) != 0:
        raise ValueError("aggregate cold scenario expected contract is not guided")
    request = scenario.get("request")
    evidence_request = evidence.get("request_payload")
    if not isinstance(request, dict) or not isinstance(evidence_request, Mapping):
        raise ValueError("aggregate/evidence request payloads are missing")
    for key in ("scene", "input_text", "requested_resource_types", "requested_output_type", "limit"):
        if request.get(key) != evidence_request.get(key):
            raise ValueError(f"aggregate cold request differs from evidence at {key}")
    return plan, raw, resolved


def build_plan(*, run_id: str, evidence_path: Path, browser_plan_path: Path) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use lowercase letters, digits, and hyphens")
    require_clean_worktree()
    evidence, evidence_raw, resolved_evidence = load_evidence(evidence_path)
    commit = current_git_commit()
    browser_plan, browser_raw, resolved_browser_plan = load_browser_plan(
        browser_plan_path, current_commit=commit, evidence=evidence
    )
    project = str(evidence["compose_project"])
    database = "recpro"
    before_counts = {str(key): int(value) for key, value in evidence["before_counts"].items()}
    targets = [
        {
            "kind": "MYSQL",
            "identifier": f"{project}.{database}.{table}",
            "operation": "APPEND",
            "expected_before_count": before_counts[table],
            "expected_after_min_count": before_counts[table] + delta,
        }
        for table, delta in EXPECTED_DELTAS.items()
    ]
    request_payload = dict(evidence["request_payload"])
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"g8-cold-user-guided-plan:{run_id}")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S1_APPEND",
        "mode": "DRY_RUN",
        "intent": (
            "Prepare one explicitly approved G8 cold_user_guided browser task. "
            "The exact SEARCH_AFTER request is already proven to stop at the "
            "four-Agent WAITING_CLARIFICATION boundary; no recommendation result "
            "or external model call is included."
        ),
        "environment": {
            "environment_id": project,
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": "sha256:" + sha256_bytes(
                f"{project}:{database}:{PROJECT_ROOT}:{commit}".encode("utf-8")
            ),
            "database_identity": f"mysql://{project}/{database}",
            "index_namespace": "lib-books-v1-20260810",
        },
        "targets": targets,
        "input_hashes": {
            "cold_guided_readonly_evidence": sha256_bytes(evidence_raw),
            "aggregate_browser_plan": sha256_bytes(browser_raw),
            "config_bundle": sha256_bytes(CONFIG_PATH.read_bytes()),
            "request_payload": sha256_bytes(canonical(request_payload)),
        },
        "idempotency_key": str(request_payload["request_id"]),
        "request_run_id": run_id,
        "max_changes": sum(EXPECTED_DELTAS.values()),
        "preconditions": [
            "the Compose project, database identity, host fingerprint and current Git commit match immediately before apply",
            "the supplied aggregate G8 browser plan and cold read-only evidence hashes match immediately before apply",
            "all expected_before_count values and table names are re-read immediately before apply",
            "the exact SEARCH_AFTER request payload and idempotency key are absent before apply",
            "the deterministic orchestrator must dispatch exactly four Agents and return WAITING_CLARIFICATION with two questions",
            "the writer must append the 19 listed task, transition, policy, trace, context, clarification and Agent facts in one transaction or roll back all",
            "no candidate, record, item, explanation, trace revision, feedback, behavior, outbox, migration, UPDATE, DELETE, graph/vector write or external LLM call is part of this plan",
            "apply requires a separate explicit approval of this unchanged plan id and plan hash",
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
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan),
        key=lambda error: tuple(error.absolute_path),
    )
    if errors:
        raise ValueError("generated cold guided ChangePlan violates schema: " + "; ".join(error.message for error in errors))
    # Keep these paths in the local variable namespace so reviewers can see
    # that the hashes above refer to the exact, in-repository inputs.
    _ = (resolved_evidence, resolved_browser_plan)
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--browser-plan", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_plan(
            run_id=args.run_id,
            evidence_path=args.evidence,
            browser_plan_path=args.browser_plan,
        )
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / args.run_id
        if output_dir.exists():
            raise FileExistsError(f"plan output directory already exists: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=False)
        output = output_dir / "cold-user-guided-change-plan.json"
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "PASS", "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "path": output.relative_to(PROJECT_ROOT).as_posix(), "max_changes": plan["max_changes"], "database_writes": 0, "external_llm_requests": 0, "files_deleted": 0, "database_physical_deletions": 0}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[FAIL] G8 cold guided ChangePlan did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
