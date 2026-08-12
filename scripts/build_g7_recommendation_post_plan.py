#!/usr/bin/env python3
"""Build a dry-run ChangePlan for one bounded G3 recommendation POST."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
COUNT_TARGETS = (
    ("recommendation_task", 1, 1),
    ("recommendation_task_transition", 8, 8),
    ("recommendation_candidate", 0, 15),
    ("recommendation_record", 1, 1),
    ("recommendation_item", 0, 5),
    ("recommendation_item_explanation", 0, 5),
    ("recommendation_policy_decision", 1, 1),
    ("recommendation_trace", 1, 1),
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def resolve_inside_root(value: Path, *, label: str) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=False)
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


def load_baseline(path: Path) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label="baseline evidence")
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "PASS":
        raise ValueError("baseline evidence must be a PASS object")
    counts = payload.get("before_counts")
    if not isinstance(counts, dict):
        raise ValueError("baseline evidence must contain before_counts")
    missing = sorted(
        table for table, _minimum, _maximum in COUNT_TARGETS if table not in counts
    )
    if missing:
        raise ValueError(f"baseline evidence is missing recommendation tables: {missing}")
    return payload, raw


def build_plan(*, run_id: str, baseline_path: Path, user_id: int) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    if isinstance(user_id, bool) or user_id < 1:
        raise ValueError("user id must be positive")
    baseline, baseline_raw = load_baseline(baseline_path)
    commit = git_commit()
    project = str(baseline["compose_project"])
    database = "recpro"
    request_id = uuid5(NAMESPACE_URL, f"g7-recommendation-request:{run_id}")
    session_id = uuid5(NAMESPACE_URL, f"g7-recommendation-session:{run_id}")
    request_payload = {
        "request_id": str(request_id),
        "session_id": str(session_id),
        "user_id": user_id,
        "scene": "SEARCH_AFTER",
        "input_text": "多智能体系统与智慧图书馆",
        "requested_resource_types": ["BOOK", "PAPER"],
        "limit": 5,
    }
    config_path = PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
    config_hash = sha256_bytes(config_path.read_bytes())
    request_hash = sha256_bytes(canonical(request_payload))
    workspace = str(PROJECT_ROOT)
    host_fingerprint = "sha256:" + sha256_bytes(
        f"{project}:{database}:{workspace}:{commit}".encode("utf-8")
    )
    counts = {str(key): int(value) for key, value in baseline["before_counts"].items()}
    targets: list[dict[str, object]] = []
    max_changes = 0
    for table, minimum_delta, maximum_delta in COUNT_TARGETS:
        before = counts[table]
        targets.append(
            {
                "kind": "MYSQL",
                "identifier": f"{project}.{database}.{table}",
                "operation": "APPEND",
                "expected_before_count": before,
                "expected_after_min_count": before + minimum_delta,
            }
        )
        max_changes += maximum_delta

    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S1_APPEND",
        "mode": "DRY_RUN",
        "intent": (
            "Prepare one bounded G3 MySQL recommendation task plus one exact same-request "
            "idempotency replay for explicit review; no apply is authorized by this plan."
        ),
        "environment": {
            "environment_id": project,
            "workspace": workspace,
            "host_fingerprint": host_fingerprint,
            "database_identity": f"mysql://{project}/{database}",
            "index_namespace": None,
        },
        "targets": targets,
        "input_hashes": {
            "baseline_readonly_evidence": sha256_bytes(baseline_raw),
            "config_bundle": config_hash,
            "request_payload": request_hash,
        },
        # The G3 HTTP adapter deliberately requires the idempotency header to
        # equal request_id; keeping that exact value in the plan makes the
        # dry-run executable without inventing a second request identity.
        "idempotency_key": str(request_id),
        "max_changes": max_changes,
        "preconditions": [
            "target Compose project and database identity match the reviewed baseline",
            "all expected_before_count values are re-read immediately before apply",
            "runtime grants still match the reviewed least-privilege read/append capability",
            "request_id and idempotency key are absent or replay-identical before apply",
            "the executor submits the exact request twice and requires 201/false then 200/true with one task identity",
            "no migration, seed, index switch, graph write, vector write, or external LLM call is part of this plan",
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
        locations = ", ".join(".".join(str(item) for item in error.absolute_path) for error in errors)
        raise ValueError(f"generated ChangePlan violates schema: {locations}")
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(
            run_id=args.run_id,
            baseline_path=args.baseline,
            user_id=args.user_id,
        )
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g7" / args.run_id
        if output_dir.exists():
            raise FileExistsError(f"plan output directory already exists: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "recommendation-post-change-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[FAIL] G7 recommendation ChangePlan did not complete: {type(exc).__name__}")
        return 1
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
