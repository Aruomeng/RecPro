#!/usr/bin/env python3
"""Build a dry-run ChangePlan for one bounded G4 MySQL projection batch.

The command only reads previously recorded PASS evidence and repository
inputs.  It creates a new plan artifact; it never connects to a database and
never authorizes an apply operation.
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

from scripts.g4_projection_contract import validate_g4_projection_query_spec


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
BASE_COUNT_TARGETS = (
    ("recommendation_task", 1),
    ("recommendation_task_transition", 8),
    ("recommendation_record", 1),
    ("recommendation_item", 8),
    ("recommendation_item_explanation", 8),
    ("recommendation_policy_decision", 1),
    ("recommendation_trace", 1),
    ("recommendation_agent_message", 7),
    ("recommendation_agent_result", 7),
    ("recommendation_agent_artifact", 1),
    ("recommendation_orchestration_result", 1),
)
SHARED_TABLES = (
    "resource_catalog",
    "resource_book_detail",
    "resource_index_state",
    "resource_tag",
    "tag_dictionary",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


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


def load_pass_evidence(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label=label)
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "PASS":
        raise ValueError(f"{label} must be a PASS object")
    counts = payload.get("before_counts")
    if not isinstance(counts, dict):
        raise ValueError(f"{label} must contain before_counts")
    return payload, raw


def count_targets(*, candidate_rows: int) -> tuple[tuple[str, int], ...]:
    if isinstance(candidate_rows, bool) or not 1 <= candidate_rows <= 60:
        raise ValueError("candidate persistence rows must be between 1 and 60")
    return (
        ("recommendation_task", 1),
        ("recommendation_task_transition", 8),
        ("recommendation_candidate", candidate_rows),
        *BASE_COUNT_TARGETS[2:],
    )


def build_plan(
    *,
    run_id: str,
    mysql_baseline_path: Path,
    g4_baseline_path: Path,
    user_id: int,
) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    if isinstance(user_id, bool) or user_id < 1:
        raise ValueError("user id must be positive")
    mysql_baseline, mysql_raw = load_pass_evidence(
        mysql_baseline_path, label="MySQL baseline evidence"
    )
    g4_baseline, g4_raw = load_pass_evidence(
        g4_baseline_path, label="G4 baseline evidence"
    )
    mysql_counts = {
        str(key): int(value) for key, value in mysql_baseline["before_counts"].items()
    }
    g4_counts = {
        str(key): int(value) for key, value in g4_baseline["before_counts"].items()
    }
    candidate_rows = g4_baseline.get("candidate_persistence_rows")
    if isinstance(candidate_rows, bool) or not isinstance(candidate_rows, int):
        raise ValueError("G4 baseline must record candidate_persistence_rows")
    count_targets_value = count_targets(candidate_rows=candidate_rows)
    missing = [
        table
        for table, _delta in count_targets_value
        if table not in mysql_counts and table not in g4_counts
    ]
    if missing:
        raise ValueError(f"baselines are missing projection tables: {missing}")
    for table in SHARED_TABLES:
        if table not in mysql_counts or table not in g4_counts:
            raise ValueError(f"both baselines must contain shared table {table}")
        if mysql_counts[table] != g4_counts[table]:
            raise ValueError(f"shared table {table} differs between baselines")
    enrichment = g4_baseline.get("candidate_enrichment")
    if enrichment != {
        "channel_scores": True,
        "channel_ranks": True,
        "primary_channel": True,
        "evidence_confidence": True,
    }:
        raise ValueError("G4 baseline does not prove the writer candidate enrichment")
    validate_g4_projection_query_spec(g4_baseline.get("query_spec"))
    channel_counts = g4_baseline.get("candidate_channel_counts")
    if (
        not isinstance(channel_counts, dict)
        or sum(int(value) for value in channel_counts.values()) != candidate_rows
    ):
        raise ValueError("G4 baseline candidate channel counts are inconsistent")
    commit = git_commit()
    project = str(mysql_baseline.get("compose_project") or "recpro-isolated")
    database = "recpro"
    request_id = uuid5(NAMESPACE_URL, f"g4-recommendation-projection-request:{run_id}")
    session_id = uuid5(NAMESPACE_URL, f"g4-recommendation-projection-session:{run_id}")
    request_payload = {
        "request_id": str(request_id),
        "session_id": str(session_id),
        "user_id": user_id,
        "scene": "SEARCH_AFTER",
        "input_text": "多智能体系统与智慧图书馆",
        "requested_resource_types": ["BOOK"],
        "requested_output_type": "TOPIC_RESOURCES",
        "limit": 8,
        "g4_channels": ["MYSQL", "GRAPH", "VECTOR"],
    }
    config_path = PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
    config_hash = sha256_bytes(config_path.read_bytes())
    request_hash = sha256_bytes(canonical(request_payload))
    workspace = str(PROJECT_ROOT)
    host_fingerprint = "sha256:" + sha256_bytes(
        f"{project}:{database}:{workspace}:{commit}".encode("utf-8")
    )
    merged_counts = {**g4_counts, **mysql_counts}
    targets: list[dict[str, object]] = []
    max_changes = 0
    for table, delta in count_targets_value:
        before = merged_counts[table]
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
        "plan_id": str(uuid5(NAMESPACE_URL, f"g4-plan:{run_id}")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S1_APPEND",
        "mode": "DRY_RUN",
        "intent": (
            "Prepare one bounded G4 RecommendationTaskService projection for explicit review; "
            "no apply is authorized by this plan."
        ),
        "environment": {
            "environment_id": project,
            "workspace": workspace,
            "host_fingerprint": host_fingerprint,
            "database_identity": f"mysql://{project}/{database}",
            "index_namespace": "library_resources__hash_char_ngram_v1",
        },
        "targets": targets,
        "input_hashes": {
            "mysql_baseline_readonly_evidence": sha256_bytes(mysql_raw),
            "g4_baseline_readonly_evidence": sha256_bytes(g4_raw),
            "config_bundle": config_hash,
            "request_payload": request_hash,
        },
        "idempotency_key": str(request_id),
        "max_changes": max_changes,
        "preconditions": [
            "target Compose project/database identity and both PASS baselines match immediately before apply",
            "all expected_before_count values are re-read immediately before apply",
            "G4 graph/vector versions, exact query_spec and candidate enrichment remain unchanged",
            "request_id and idempotency key are absent or replay-identical before apply",
            "writer transaction must commit all G3 and G4 rows together or rollback all of them",
            "no migration, seed, UPDATE, DELETE, graph write, vector write, or external LLM call is part of this plan",
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
    parser.add_argument("--mysql-baseline", type=Path, required=True)
    parser.add_argument("--g4-baseline", type=Path, required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(
            run_id=args.run_id,
            mysql_baseline_path=args.mysql_baseline,
            g4_baseline_path=args.g4_baseline,
            user_id=args.user_id,
        )
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / args.run_id
        if output_dir.exists():
            raise FileExistsError(f"plan output directory already exists: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "g4-recommendation-projection-change-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[FAIL] G4 projection ChangePlan did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
