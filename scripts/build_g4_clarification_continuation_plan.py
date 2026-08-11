#!/usr/bin/env python3
"""Build a DRY_RUN ChangePlan for one approved G4 clarification continuation."""

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
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


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


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("current Git HEAD is not a full commit hash")
    return value


def load_evidence(path: Path) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label="continuation read-only evidence")
    raw = resolved.read_bytes()
    evidence = json.loads(raw.decode("utf-8"))
    if not isinstance(evidence, dict) or evidence.get("status") != "PASS":
        raise ValueError("continuation evidence must be a PASS object")
    if evidence.get("schema_version") != "g4-clarification-continuation-readonly-evidence-v1":
        raise ValueError("continuation evidence schema is not supported")
    if evidence.get("orchestration_status") not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise ValueError("continuation evidence did not complete the task")
    if int(evidence.get("previous_context_version", -1)) != 1 or int(
        evidence.get("next_context_version", -1)
    ) != 2:
        raise ValueError("continuation evidence must advance context version 1 to 2")
    if evidence.get("before_counts") != evidence.get("after_counts"):
        raise ValueError("continuation evidence counts changed during read-only execution")
    safety = evidence.get("safety")
    if not isinstance(safety, dict) or any(
        int(safety.get(key, -1)) != 0
        for key in (
            "mysql_writes",
            "neo4j_writes",
            "chroma_writes",
            "external_requests",
            "actual_delete_count",
            "files_deleted",
            "overwritten_inputs",
        )
    ):
        raise ValueError("continuation evidence is not zero-side-effect")
    before = evidence.get("before_counts")
    deltas = evidence.get("expected_deltas")
    if not isinstance(before, dict) or not isinstance(deltas, dict) or not deltas:
        raise ValueError("continuation evidence is missing counts or deltas")
    for table, delta in deltas.items():
        if table not in before or int(delta) < 1:
            raise ValueError(f"continuation evidence has an invalid target delta: {table}")
    if int(evidence.get("candidate_count", 0)) < 1 or int(evidence.get("item_count", 0)) < 1:
        raise ValueError("continuation evidence did not produce recommendation items")
    return evidence, raw


def build_plan(*, run_id: str, evidence_path: Path) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    evidence, evidence_raw = load_evidence(evidence_path)
    commit = current_git_commit()
    project = str(evidence.get("compose_project") or "recpro-isolated")
    database = "recpro"
    answer_payload = {
        "task_id": str(evidence["task_id"]),
        "trace_id": str(evidence["trace_id"]),
        "user_id": int(evidence["user_id"]),
        "previous_context_version": int(evidence["previous_context_version"]),
        "next_context_version": int(evidence["next_context_version"]),
        "answers": dict(evidence["answers"]),
        "idempotency_key": str(evidence["proposed_idempotency_key"]),
    }
    config_hash = sha256_bytes(CONFIG_PATH.read_bytes())
    request_hash = sha256_bytes(canonical(answer_payload))
    host_fingerprint = "sha256:" + sha256_bytes(
        f"{project}:{database}:{PROJECT_ROOT}:{commit}".encode("utf-8")
    )
    before_counts = {str(key): int(value) for key, value in evidence["before_counts"].items()}
    targets: list[dict[str, object]] = []
    max_changes = 0
    for table, raw_delta in sorted(evidence["expected_deltas"].items()):
        delta = int(raw_delta)
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
    if max_changes != 44:
        raise ValueError(f"continuation plan must be exactly 44 rows, got {max_changes}")
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"g4-clarification-continuation-plan:{run_id}")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S1_APPEND",
        "mode": "DRY_RUN",
        "intent": (
            "Prepare one bounded G4 clarification continuation from task "
            f"{evidence['task_id']} context 1 to context 2; no apply is authorized by this plan."
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
            "clarification_continuation_readonly_evidence": sha256_bytes(evidence_raw),
            "config_bundle": config_hash,
            "answer_payload": request_hash,
        },
        "idempotency_key": str(evidence["proposed_idempotency_key"]),
        "max_changes": max_changes,
        "preconditions": [
            "the target task belongs to the requested user and its latest context is exactly WAITING_CLARIFICATION version 1",
            "the exact answer payload and idempotency key are absent from recommendation_task_context before apply",
            "all expected_before_count values and the runtime identity are re-read immediately before apply",
            "the G4 orchestrator must use the original task/trace identity and advance exactly to context_version 2",
            "the writer must append all continuation facts and the answered context in one caller-owned transaction",
            "no task root update, resource mutation, migration, seed, UPDATE, DELETE, graph/vector write, or external LLM call is part of this plan",
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
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan)
    )
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
    args = parser.parse_args(argv)
    try:
        plan = build_plan(run_id=args.run_id, evidence_path=args.evidence)
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / args.run_id
        if output_dir.exists():
            raise FileExistsError(f"plan output directory already exists: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "g4-clarification-continuation-change-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(
            "[FAIL] G4 clarification continuation ChangePlan did not complete: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
