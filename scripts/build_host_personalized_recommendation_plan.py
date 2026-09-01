#!/usr/bin/env python3
"""Build a bounded host-local MySQL personalized recommendation ChangePlan."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TARGETS = (
    ("recommendation_task", 1, 1), ("recommendation_task_transition", 8, 8),
    ("recommendation_candidate", 0, 15), ("recommendation_record", 1, 1),
    ("recommendation_item", 0, 5), ("recommendation_item_explanation", 0, 5),
    ("recommendation_policy_decision", 1, 1), ("recommendation_trace", 1, 1),
)
INPUTS = (
    "scripts/build_host_personalized_recommendation_plan.py",
    "scripts/execute_host_personalized_recommendation_plan.py",
    "backend/app/recommendation/adapters/mysql.py",
    "backend/app/recommendation/application/public.py",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def build(*, baseline_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.resolve(strict=True).read_text(encoding="utf-8"))
    if baseline.get("status") != "PASS" or baseline.get("can_recommend") is not True:
        raise ValueError("host recommendation baseline must be a PASS with can_recommend=true")
    if baseline.get("profile", {}).get("profile_version") != 4:
        raise ValueError("host recommendation baseline must bind user 1002 profile version 4")
    counts = {str(key): int(value) for key, value in baseline["before_counts"].items()}
    if any(table not in counts for table, _minimum, _maximum in _TARGETS):
        raise ValueError("host recommendation baseline lacks a target table count")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    request_id = str(uuid5(NAMESPACE_URL, f"libramas:host-personalized-recommendation:{commit}:user-1002:v4"))
    session_id = str(uuid5(NAMESPACE_URL, f"libramas:host-personalized-session:{commit}:user-1002:v4"))
    request = {"request_id": request_id, "session_id": session_id, "user_id": 1002, "scene": "SEARCH_AFTER", "input_text": "多智能体系统、智慧图书馆与知识图谱", "requested_resource_types": ["BOOK"], "limit": 5}
    plan: dict[str, Any] = {
        "schema_version": "host-personalized-recommendation-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"libramas:host-personalized-plan:{commit}:{request_id}")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S1_PERSONALIZED_RECOMMENDATION_APPEND",
        "mode": "APPLY",
        "baseline": {"path": str(baseline_path), "sha256": sha256(baseline_path.resolve(strict=True).read_bytes()).hexdigest(), "profile_version": 4, "counts": counts},
        "request": request,
        "targets": [{"kind": "MYSQL", "identifier": f"recpro.{table}", "min_rows": minimum, "max_rows": maximum} for table, minimum, maximum in _TARGETS],
        "max_row_increase": sum(maximum for _table, _minimum, maximum in _TARGETS),
        "input_hashes": {item: _sha(PROJECT_ROOT / item) for item in INPUTS},
        "safety": {"database_deletions": 0, "file_deletions": 0, "deepseek_requests": 0, "neo4j_writes": 0, "chroma_writes": 0, "profile_updates": 0, "behavior_writes": 0, "feedback_writes": 0},
        "preconditions": ["host readiness remains can_recommend=true", "user 1002 profile version remains 4", "all target counts equal the frozen baseline", "request UUID is absent before first POST", "first POST must be 201 and second exact replay must be 200 with no extra rows"],
    }
    plan["plan_hash"] = sha256(_canonical(plan)).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--baseline", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(baseline_path=args.baseline); output=args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle: json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"[FAIL] host personalized recommendation ChangePlan: {type(exc).__name__}: {exc}"); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
