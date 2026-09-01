#!/usr/bin/env python3
"""Prepare a zero-write, chronological synthetic profile-demo intent.

Unlike the historical demo import, this intent is reserved for user 1002 and
anchors all events after an explicitly supplied UTC timestamp.  It deliberately
does not open a database or enqueue a profile refresh; a separate read-only
reconciliation and approved ChangePlan are required before either operation.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

from scripts.plan_synthetic_demo_behavior_import import build_import_intent


_NAMESPACE = uuid5(NAMESPACE_URL, "libramas:current-synthetic-profile-demo:v1")
_TARGET_USER_ID = 1002
_SYNTHETIC_USER_ID = "synthetic-u-0001"


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("base occurred-at must include a UTC offset")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_current_profile_demo_intent(
    benchmark_dir: Path,
    *,
    base_occurred_at: str,
) -> dict[str, Any]:
    base = _parse_utc(base_occurred_at)
    frozen = build_import_intent(
        benchmark_dir,
        synthetic_user_id=_SYNTHETIC_USER_ID,
        target_user_id=_TARGET_USER_ID,
    )
    source_events = tuple(frozen["events"])
    if len(source_events) != 16:
        raise ValueError("current synthetic profile demo requires exactly 16 frozen source events")
    dataset_version = str(frozen["benchmark"]["dataset_version"])
    session_uuid = str(uuid5(_NAMESPACE, f"{dataset_version}:{_TARGET_USER_ID}:session:{_iso(base)}"))
    events: list[dict[str, Any]] = []
    for index, source in enumerate(source_events):
        event_uuid = str(uuid5(_NAMESPACE, f"{dataset_version}:{_TARGET_USER_ID}:{_iso(base)}:{index}"))
        events.append({
            **source,
            "event_uuid": event_uuid,
            "session_uuid": session_uuid,
            "target_user_id": _TARGET_USER_ID,
            "occurred_at": _iso(base + timedelta(minutes=index)),
            "reason_code": "SYNTHETIC_DEVELOPMENT_ONLY",
            "enqueue_profile_update": False,
        })
    payload = {
        "schema_version": "current-synthetic-profile-demo-intent-v1",
        "status": "NO_WRITE_INTENT_READY",
        "classification": "SYNTHETIC_DEVELOPMENT_ONLY",
        "confirmation_eligible": False,
        "benchmark": frozen["benchmark"],
        "target": {"user_id": _TARGET_USER_ID, "synthetic_user_id": _SYNTHETIC_USER_ID},
        "timeline": {
            "base_occurred_at": _iso(base),
            "final_occurred_at": events[-1]["occurred_at"],
            "must_follow_existing_target_behavior": True,
        },
        "events": events,
        "profile_refresh_batch": {
            "source_event_uuid": events[-1]["event_uuid"],
            "source_type": "SYNTHETIC_BATCH",
            "profile_outbox_rows": 1,
            "purpose": "One chronological snapshot after all 16 synthetic events; never one outbox per event.",
        },
        "expected_append_rows": {"user_behavior_event": 16, "profile_update_outbox": 1},
        "required_readonly_reconciliation": {
            "event_uuids": [str(item["event_uuid"]) for item in events],
            "resource_external_ids": sorted({str(item["resource_external_id"]) for item in events}),
            "resource_identities": frozen["required_readonly_reconciliation"]["resource_identities"],
            "checks": [
                "target user remains outside iam_user_account",
                "all 16 event UUIDs are absent",
                "base occurred-at is later than the target user's latest behavior",
                "target user has no PENDING or PROCESSING profile outbox row",
                "all resource external IDs resolve uniquely",
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
    payload["intent_hash"] = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--base-occurred-at", default="2026-09-01T12:00:00.000Z")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(
            build_current_profile_demo_intent(args.benchmark_dir, base_occurred_at=args.base_occurred_at),
            ensure_ascii=False, indent=2, sort_keys=True,
        ))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"[FAIL] current synthetic profile-demo intent: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
