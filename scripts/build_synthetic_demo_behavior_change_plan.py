#!/usr/bin/env python3
"""Build the exact append-only ChangePlan for the reconciled synthetic demo."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

from scripts.plan_synthetic_demo_behavior_import import build_import_intent
from scripts.verify_synthetic_demo_behavior_import import reconcile
from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "scripts/plan_synthetic_demo_behavior_import.py",
    "scripts/verify_synthetic_demo_behavior_import.py",
    "scripts/build_synthetic_demo_behavior_change_plan.py",
    "scripts/execute_synthetic_demo_behavior_change_plan.py",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


async def build(args: argparse.Namespace) -> dict[str, Any]:
    intent = build_import_intent(args.benchmark_dir, synthetic_user_id=args.synthetic_user_id, target_user_id=args.target_user_id)
    reconciliation = await reconcile(read_env(args.env_file.resolve(strict=True)), intent)
    if not reconciliation["ready_for_append_plan"]:
        raise ValueError("synthetic import reconciliation is not ready for an append plan")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    expected_rows = int(intent["expected_append_rows"]["user_behavior_event"])
    plan: dict[str, Any] = {
        "schema_version": "synthetic-demo-behavior-change-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"libramas:synthetic-import:{commit}:{intent['benchmark']['manifest_sha256']}")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S1_APPEND",
        "mode": "APPLY",
        "intent": "Append exactly 16 synthetic development-only behavior facts to research demo user 1001. Do not enqueue profile updates or modify any projection, account, recommendation, graph, vector, or existing fact.",
        "targets": [{"kind": "MYSQL", "identifier": "recpro.user_behavior_event:synthetic-demo-20260901", "operation": "APPEND", "rows": expected_rows}],
        "max_changes": expected_rows,
        "benchmark": intent["benchmark"],
        "target": intent["target"],
        "events": intent["events"],
        "reconciliation": reconciliation,
        "input_hashes": {relative: _sha(PROJECT_ROOT / relative) for relative in INPUTS},
        "safety": {"database_deletions": 0, "file_deletions": 0, "profile_outbox_rows": 0, "profile_updates": 0, "neo4j_writes": 0, "chroma_writes": 0, "deepseek_requests": 0},
        "preconditions": ["all 16 UUIDs absent", "8 resource mappings unchanged", "user 1001 remains outside iam_user_account", "user 1001 behavior count is unchanged from read-only baseline"],
    }
    plan["plan_hash"] = sha256(_canonical(plan)).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--synthetic-user-id", default="synthetic-u-0001")
    parser.add_argument("--target-user-id", type=int, default=1001)
    parser.add_argument("--output", type=Path, help="new JSON path; existing files are never overwritten")
    args = parser.parse_args(argv)
    import asyncio
    try:
        result = asyncio.run(build(args))
        if args.output is not None:
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] synthetic demo ChangePlan: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
