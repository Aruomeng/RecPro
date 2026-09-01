#!/usr/bin/env python3
"""Prepare a zero-write MySQL import intent for one synthetic demo reader.

The planner accepts only a frozen ``SYNTHETIC_DEVELOPMENT_ONLY`` benchmark and
produces deterministic event/session UUIDs for one of the two existing
research-demo users.  It never opens a database or resolves resource IDs;
that read-only reconciliation, then the actual append-only import, require a
separately approved ChangePlan.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

try:
    from scripts.evaluation_runtime import read_json, read_jsonl, validate_safe_id
except ModuleNotFoundError:  # direct ``python scripts/...`` invocation
    from evaluation_runtime import read_json, read_jsonl, validate_safe_id  # type: ignore[no-redef]


_DEMO_USERS = frozenset({1001, 1002})
_NAMESPACE = uuid5(NAMESPACE_URL, "libramas:synthetic-demo-import:v1")
_ALLOWED_EVENTS = frozenset({"VIEW_RESOURCE", "FAVORITE_RESOURCE", "BORROW_BOOK", "NOT_INTERESTED"})


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def build_import_intent(
    benchmark_dir: Path, *, synthetic_user_id: str, target_user_id: int,
) -> dict[str, Any]:
    if target_user_id not in _DEMO_USERS:
        raise ValueError("synthetic behavior may target only research-demo user 1001 or 1002")
    root = benchmark_dir.resolve(strict=True)
    manifest = read_json(root / "manifest.json")
    if (
        manifest.get("classification") != "SYNTHETIC_DEVELOPMENT_ONLY"
        or manifest.get("confirmation_eligible") is not False
        or manifest.get("frozen") is not True
    ):
        raise ValueError("benchmark is not a frozen synthetic development-only artifact")
    dataset_version = validate_safe_id(str(manifest.get("dataset_version", "")), label="dataset version")
    resources = read_jsonl(root / "resources.jsonl")
    events = read_jsonl(root / "synthetic_events.jsonl")
    resource_external = {int(row["resource_id"]): str(row["external_id"]) for row in resources}
    selected = [row for row in events if row.get("user_research_id") == synthetic_user_id]
    if not selected:
        raise ValueError("synthetic user has no frozen events in this benchmark")
    session_uuid = uuid5(_NAMESPACE, f"{dataset_version}:{target_user_id}:{synthetic_user_id}:session")
    planned_events: list[dict[str, Any]] = []
    seen_uuid: set[str] = set()
    for row in selected:
        event_type = str(row.get("event_type", ""))
        resource_id = int(row["resource_id"])
        if event_type not in _ALLOWED_EVENTS or resource_id not in resource_external:
            raise ValueError("synthetic event is outside the behavior import allowlist")
        event_uuid = str(uuid5(_NAMESPACE, f"{dataset_version}:{target_user_id}:{row['event_id']}"))
        if event_uuid in seen_uuid:
            raise ValueError("synthetic event UUID collision")
        seen_uuid.add(event_uuid)
        planned_events.append({
            "event_uuid": event_uuid,
            "target_user_id": target_user_id,
            "session_uuid": str(session_uuid),
            "event_type": event_type,
            "resource_external_id": resource_external[resource_id],
            "occurred_at": str(row["occurred_at"]),
            "reason_code": "SYNTHETIC_DEVELOPMENT_ONLY",
            "enqueue_profile_update": False,
        })
    planned_events.sort(key=lambda row: (str(row["occurred_at"]), str(row["event_uuid"])))
    return {
        "schema_version": "synthetic-demo-behavior-intent-v1",
        "status": "NO_WRITE_INTENT_READY",
        "classification": "SYNTHETIC_DEVELOPMENT_ONLY",
        "confirmation_eligible": False,
        "benchmark": {
            "dataset_version": dataset_version,
            "manifest_sha256": _sha256_file(root / "manifest.json"),
            "events_sha256": _sha256_file(root / "synthetic_events.jsonl"),
            "resources_sha256": _sha256_file(root / "resources.jsonl"),
        },
        "target": {"user_id": target_user_id, "synthetic_user_id": synthetic_user_id},
        "events": planned_events,
        "expected_append_rows": {"user_behavior_event": len(planned_events), "profile_update_outbox": 0},
        "required_readonly_reconciliation": {
            "resource_external_ids": sorted({str(row["resource_external_id"]) for row in planned_events}),
            "event_uuids": [str(row["event_uuid"]) for row in planned_events],
            "checks": [
                "every resource_external_id resolves to exactly one resource_catalog row",
                "every event_uuid is absent before apply",
                "target is an approved research-demo user and not an authenticated reader account",
            ],
        },
        "safety": {
            "database_connections": 0,
            "database_writes": 0,
            "profile_projection_updates": 0,
            "deepseek_requests": 0,
            "file_deletions": 0,
            "database_physical_deletions": 0,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--synthetic-user-id", default="synthetic-u-0001")
    parser.add_argument("--target-user-id", type=int, default=1001)
    args = parser.parse_args(argv)
    try:
        result = build_import_intent(
            args.benchmark_dir, synthetic_user_id=args.synthetic_user_id, target_user_id=args.target_user_id,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"[FAIL] synthetic demo behavior intent was not prepared: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
