#!/usr/bin/env python3
"""Build a DRY_RUN plan for one initial G4 clarification task.

Only a PASS read-only clarification evidence file and the repository config
bundle are read.  The generated plan describes the bounded append for a new
HOME-empty task; it does not connect to MySQL and cannot apply itself.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
CONFIG_PATH = PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
REQUEST_SPEC = {
    "scene": "HOME",
    "input_text": None,
    "resource_types": [],
    "output_type": None,
    "limit": 5,
}
SHARED_TABLES = (
    "resource_catalog",
    "resource_book_detail",
    "tag_dictionary",
    "resource_tag",
    "resource_index_state",
)
WAITING_DELTAS = (
    ("recommendation_task", 1),
    ("recommendation_task_transition", 4),
    ("recommendation_policy_decision", 1),
    ("recommendation_trace", 1),
    ("recommendation_task_context", 1),
    ("recommendation_clarification", 1),
    ("recommendation_agent_message", 4),
    ("recommendation_agent_result", 4),
    ("recommendation_agent_artifact", 1),
    ("recommendation_orchestration_result", 1),
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def resolve_inside_root(value: Path, *, label: str) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("git HEAD is not a full commit hash")
    return value


def load_evidence(path: Path) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label="clarification read-only evidence")
    raw = resolved.read_bytes()
    evidence = json.loads(raw.decode("utf-8"))
    if not isinstance(evidence, dict) or evidence.get("status") != "PASS":
        raise ValueError("clarification evidence must be a PASS object")
    if evidence.get("schema_version") != "g4-clarification-readonly-evidence-v1":
        raise ValueError("clarification evidence schema is not supported")
    if evidence.get("query_spec") != REQUEST_SPEC:
        raise ValueError("clarification evidence query_spec is not the HOME-empty shape")
    if evidence.get("orchestration_status") != "WAITING_CLARIFICATION":
        raise ValueError("clarification evidence did not reach WAITING_CLARIFICATION")
    if evidence.get("dispatch_count") != 4 or evidence.get("transition_count") != 4:
        raise ValueError("clarification evidence does not prove the four-Agent waiting path")
    safety = evidence.get("safety")
    if not isinstance(safety, dict) or any(int(safety.get(key, -1)) != 0 for key in (
        "mysql_writes", "neo4j_writes", "chroma_writes", "external_requests",
        "actual_delete_count", "files_deleted", "overwritten_inputs",
    )):
        raise ValueError("clarification evidence is not zero-side-effect")
    before = evidence.get("before_counts")
    after = evidence.get("after_counts")
    if not isinstance(before, dict) or before != after:
        raise ValueError("clarification evidence counts changed during read-only execution")
    missing = [table for table, _delta in WAITING_DELTAS if table not in before]
    if missing:
        raise ValueError(f"clarification evidence is missing target counts: {missing}")
    for table in SHARED_TABLES:
        if table not in before:
            raise ValueError(f"clarification evidence is missing shared table {table}")
    return evidence, raw


def request_payload(run_id: str, *, user_id: int) -> dict[str, object]:
    request_id = uuid5(NAMESPACE_URL, f"g4-clarification-waiting-request:{run_id}")
    session_id = uuid5(NAMESPACE_URL, f"g4-clarification-waiting-session:{run_id}")
    return {
        "request_id": str(request_id),
        "session_id": str(session_id),
        "user_id": user_id,
        **REQUEST_SPEC,
    }


def build_plan(
    *,
    run_id: str,
    evidence_path: Path,
    user_id: int,
) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    if isinstance(user_id, bool) or user_id < 1:
        raise ValueError("user id must be positive")
    evidence, evidence_raw = load_evidence(evidence_path)
    commit = git_commit()
    project = str(evidence.get("compose_project") or "recpro-isolated")
    database = "recpro"
    payload = request_payload(run_id, user_id=user_id)
    config_hash = sha256_bytes(CONFIG_PATH.read_bytes())
    request_hash = sha256_bytes(canonical(payload))
    host_fingerprint = "sha256:" + sha256_bytes(
        f"{project}:{database}:{PROJECT_ROOT}:{commit}".encode("utf-8")
    )
    before_counts = {str(key): int(value) for key, value in evidence["before_counts"].items()}
    targets: list[dict[str, object]] = []
    max_changes = 0
    for table, delta in WAITING_DELTAS:
        before = before_counts[table]
        targets.append(
            {
                "kind": "MYSQL",
                "identifier": f"{project}.{database}.{table}",
                "operation": "APPEND",
                "expected_before_count": before,
                "expected_after_min_count": before + delta,
            }
        )
        max_changes += delta
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"g4-clarification-plan:{run_id}")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S1_APPEND",
        "mode": "DRY_RUN",
        "intent": (
            "Prepare one bounded G4 HOME-empty clarification task for explicit review; "
            "no apply is authorized by this plan."
        ),
        "environment": {
            "environment_id": project,
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": host_fingerprint,
            "database_identity": f"mysql://{project}/{database}",
            "index_namespace": None,
        },
        "targets": targets,
        "input_hashes": {
            "clarification_readonly_evidence": sha256_bytes(evidence_raw),
            "config_bundle": config_hash,
            "request_payload": request_hash,
        },
        "idempotency_key": payload["request_id"],
        "max_changes": max_changes,
        "preconditions": [
            "target Compose project/database identity and the PASS read-only evidence match immediately before apply",
            "all expected_before_count values are re-read immediately before apply",
            "the exact HOME-empty request and idempotency key are absent before apply",
            "the G4 orchestrator must dispatch four Agents and return WAITING_CLARIFICATION",
            "writer transaction must append task, Agent facts, policy, trace, context and clarification together or rollback all",
            "no candidate, record, item, explanation, trace revision, migration, seed, UPDATE, DELETE, graph/vector write, or external LLM call is part of this plan",
            "apply requires a separate explicit approval of this unchanged plan hash",
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
        locations = ", ".join(
            ".".join(str(item) for item in error.absolute_path) for error in errors
        )
        raise ValueError(f"generated ChangePlan violates schema: {locations}")
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(run_id=args.run_id, evidence_path=args.evidence, user_id=args.user_id)
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / args.run_id
        if output_dir.exists():
            raise FileExistsError(f"plan output directory already exists: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "g4-clarification-waiting-change-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[FAIL] G4 clarification ChangePlan did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
