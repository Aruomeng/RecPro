#!/usr/bin/env python3
"""Build a zero-write DRY_RUN ChangePlan for G8 A07/A09/A10."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_g5_feedback_http_plan import (
    canonical,
    connect_runtime,
    load_pass_baseline,
    read_identity_and_grants,
    read_snapshot,
    read_target_facts,
    sha256_bytes,
    target_snapshot_from_facts,
)
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "verification" / "g8-boundary-change-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
EXPECTED_DELTAS = {
    "recommendation_impression": 3,
    "recommendation_feedback": 1,
    "user_behavior_event": 4,
    "profile_update_outbox": 1,
    "user_resource_state": 1,
    "profile_replay_run": 1,
    "profile_change_log": 4,
    "user_interest_tag": 0,
    "user_negative_preference": 0,
    "domain_state_transition": 5,
    "user_profile": 0,
}
OPERATIONS = {
    "recommendation_impression": "APPEND",
    "recommendation_feedback": "APPEND",
    "user_behavior_event": "APPEND",
    "profile_update_outbox": "APPEND_AND_STATUS_UPDATE",
    "user_resource_state": "CREATE",
    "profile_replay_run": "APPEND",
    "profile_change_log": "APPEND",
    "user_interest_tag": "CONTROLLED_PROJECTION_UPDATE",
    "user_negative_preference": "CONTROLLED_PROJECTION_UPDATE",
    "domain_state_transition": "APPEND",
    "user_profile": "CONTROLLED_PROJECTION_UPDATE",
}


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("Git HEAD is not a full commit")
    return commit


def _require_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise ValueError("working tree must be clean when freezing an approval plan")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("base-at must include a timezone")
    return parsed.astimezone(UTC)


def _resolve_inside_project(value: Path, *, label: str) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def _latest_behavior_at(*targets: Mapping[str, Any]) -> datetime | None:
    values: list[datetime] = []
    for target in targets:
        raw = target.get("latest_behavior_at")
        if raw is None:
            continue
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=UTC)
        values.append(parsed.astimezone(UTC))
    return max(values, default=None)


async def _uuid_counts(connection: Any, uuids: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for value in uuids:
            await cursor.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM recommendation_impression WHERE impression_uuid=%s) + "
                "(SELECT COUNT(*) FROM recommendation_feedback WHERE feedback_uuid=%s) + "
                "(SELECT COUNT(*) FROM user_behavior_event WHERE event_uuid=%s)",
                (value, value, value),
            )
            counts[value] = int((await cursor.fetchone())[0])
    return counts


def build_plan(
    *,
    run_id: str,
    baseline_path: Path,
    baseline: Mapping[str, Any],
    baseline_raw: bytes,
    current_counts: Mapping[str, int],
    identity: Mapping[str, Any],
    read_target: Mapping[str, Any],
    exposure_target: Mapping[str, Any],
    base_at: datetime,
    uuids: Mapping[str, str],
) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    if read_target["item"]["resource_id"] == exposure_target["item"]["resource_id"]:
        raise ValueError("ALREADY_READ and exposure cases require distinct resources")
    if any(read_target["uuid_absence"].values()) or any(exposure_target["uuid_absence"].values()):
        raise ValueError("one or more deterministic UUIDs already exist")
    if read_target["resource_states"] or exposure_target["resource_states"]:
        raise ValueError("G8 boundary targets must have no pre-existing resource state")
    if read_target["outbox_statuses"].get("PENDING", 0) or read_target["outbox_statuses"].get("PROCESSING", 0):
        raise ValueError("live Outbox work prevents a bounded plan")
    latest_behavior_at = _latest_behavior_at(read_target, exposure_target)
    if latest_behavior_at is not None and base_at <= latest_behavior_at:
        raise ValueError("base-at must be later than existing behavior for both target resources")

    commit = _git_commit()
    project = str(baseline["compose_project"])
    database = str(identity["database"])
    targets = [
        {
            "table": table,
            "operation": OPERATIONS[table],
            "expected_before_count": int(current_counts[table]),
            "expected_delta": delta,
            "expected_after_count": int(current_counts[table]) + delta,
        }
        for table, delta in EXPECTED_DELTAS.items()
    ]
    read_snapshot_hash = sha256_bytes(canonical(target_snapshot_from_facts(read_target)))
    exposure_snapshot_hash = sha256_bytes(canonical(target_snapshot_from_facts(exposure_target)))
    def identity_payload(target: Mapping[str, Any], snapshot_hash: str) -> dict[str, Any]:
        return {
            "task_id": str(target["task"]["id"]),
            "record_id": int(target["record"]["id"]),
            "item_id": int(target["item"]["id"]),
            "resource_id": int(target["item"]["resource_id"]),
            "user_id": int(target["task"]["user_id"]),
            "target_snapshot_sha256": snapshot_hash,
        }
    plan: dict[str, Any] = {
        "schema_version": "g8-boundary-change-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"g8-boundary-plan:{run_id}")),
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "classification": "S2_CONTROLLED_UPDATE",
        "mode": "DRY_RUN",
        "case_ids": ["A07", "A09", "A10"],
        "environment": {
            "environment_id": project,
            "workspace": str(PROJECT_ROOT),
            "database_identity": f"mysql://{project}/{database}",
            "host_fingerprint": "sha256:" + sha256_bytes(
                f"{project}:{database}:{PROJECT_ROOT}:{commit}".encode("utf-8")
            ),
        },
        "baseline": {
            "path": baseline_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": hashlib.sha256(baseline_raw).hexdigest(),
            "counts_sha256": sha256_bytes(canonical(dict(sorted(current_counts.items())))),
        },
        "targets": targets,
        "scenarios": {
            "duration_below_threshold": {
                "identity": identity_payload(exposure_target, exposure_snapshot_hash),
                "impression_uuid": uuids["duration_impression"],
                "rendered_at": _iso(base_at),
                "visible_ms": 999,
                "max_visible_ratio": 0.8,
                "expected_valid_exposure": False,
            },
            "ratio_below_threshold": {
                "identity": identity_payload(exposure_target, exposure_snapshot_hash),
                "impression_uuid": uuids["ratio_impression"],
                "rendered_at": _iso(base_at + timedelta(seconds=10)),
                "visible_ms": 1000,
                "max_visible_ratio": 0.49,
                "expected_valid_exposure": False,
            },
            "already_read": {
                "identity": identity_payload(read_target, read_snapshot_hash),
                "impression_uuid": uuids["read_impression"],
                "feedback_uuid": uuids["read_feedback"],
                "rendered_at": _iso(base_at + timedelta(seconds=20)),
                "feedback_at": _iso(base_at + timedelta(seconds=30)),
                "visible_ms": 1500,
                "max_visible_ratio": 0.8,
                "feedback_type": "NOT_INTERESTED",
                "reason_code": "ALREADY_READ",
                "expected_resource_state": "READ",
                "worker_id": f"g8-{run_id}"[:64],
                "worker_limit": 1,
                "formula_version": "profile-g2-v1",
            },
        },
        "max_changes": sum(EXPECTED_DELTAS.values()),
        "preconditions": [
            "the PASS G5 read-only baseline hash, full table set, and every expected_before_count remain unchanged",
            "the current Git commit, Compose project, database identity, runtime probe, and least-privilege grants remain unchanged",
            "all four deterministic UUIDs are absent from impression, feedback, and behavior fact tables",
            "the two reviewed recommendation items remain COMPLETED/context_version=1 BOOK items owned by user 1001",
            "the ALREADY_READ and exposure resources remain distinct and have no pre-existing user_resource_state",
            "profile_update_outbox has no PENDING or PROCESSING work before apply",
            "the 999ms and 0.49 exposure cases append facts with is_valid_exposure=false and enqueue no profile work",
            "ALREADY_READ creates only READ resource state; profile interest and negative-signal content hashes excluding profile_version remain unchanged",
            "a same-UUID replay changes no count; the single new Outbox row is consumed once and is not reclaimed",
            "apply is impossible until a bounded executor exists and the user approves this exact plan_id and plan_hash",
        ],
        "safety_assertions": {
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "artifact_overwrites": 0,
            "destructive_capabilities_required": False,
            "counts_must_not_decrease": True,
            "business_writes_authorized": False,
        },
        "executor_status": "READY_FOR_EXPLICIT_APPROVAL",
    }
    plan["plan_hash"] = sha256_bytes(canonical(plan))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan))
    if errors:
        raise ValueError("generated G8 boundary plan violates schema: " + "; ".join(error.message for error in errors))
    if plan["max_changes"] != 20:
        raise ValueError("G8 boundary plan change budget drifted")
    return plan


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / args.run_id
    if output_dir.exists():
        raise FileExistsError(f"plan directory already exists: {output_dir}")
    _require_clean_worktree()
    baseline_path = _resolve_inside_project(args.baseline, label="G5 read-only baseline")
    baseline, baseline_raw = load_pass_baseline(baseline_path)
    compose = read_env(_resolve_inside_project(args.env_file, label="runtime env file"))
    issues = validate_compose(compose)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    values = {
        **compose,
        **read_env(_resolve_inside_project(args.secrets_file, label="runtime secrets file")),
    }
    required = (
        "COMPOSE_PROJECT_NAME",
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_PERSISTENCE_PROBE_ID",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")
    connection = await connect_runtime(values, autocommit=False)
    try:
        _names, counts = await read_snapshot(connection)
        if counts != {str(key): int(value) for key, value in baseline["after_counts"].items()}:
            raise ValueError("live table counts differ from the approved baseline")
        uuid_values = {
            name: str(uuid5(NAMESPACE_URL, f"g8-boundary:{args.run_id}:{name}"))
            for name in ("duration_impression", "ratio_impression", "read_impression", "read_feedback")
        }
        absence = await _uuid_counts(connection, tuple(uuid_values.values()))
        if any(absence.values()):
            raise ValueError("one or more deterministic boundary UUIDs already exist")
        read_target = await read_target_facts(
            connection,
            task_id=args.task_id,
            record_id=args.record_id,
            item_id=args.read_item_id,
            user_id=args.user_id,
            resource_id=args.read_resource_id,
            uuids={
                "impression_uuid": UUID(uuid_values["read_impression"]),
                "feedback_uuid": UUID(uuid_values["read_feedback"]),
                "behavior_uuid": uuid5(NAMESPACE_URL, f"g8-boundary:{args.run_id}:read-placeholder"),
            },
        )
        exposure_target = await read_target_facts(
            connection,
            task_id=args.task_id,
            record_id=args.record_id,
            item_id=args.exposure_item_id,
            user_id=args.user_id,
            resource_id=args.exposure_resource_id,
            uuids={
                "impression_uuid": UUID(uuid_values["duration_impression"]),
                "feedback_uuid": uuid5(NAMESPACE_URL, f"g8-boundary:{args.run_id}:exposure-placeholder"),
                "behavior_uuid": UUID(uuid_values["ratio_impression"]),
            },
        )
        await connection.rollback()
    finally:
        connection.close()
    identity = await read_identity_and_grants(values)
    plan = build_plan(
        run_id=args.run_id,
        baseline_path=baseline_path,
        baseline=baseline,
        baseline_raw=baseline_raw,
        current_counts=counts,
        identity=identity,
        read_target=read_target,
        exposure_target=exposure_target,
        base_at=_parse_time(args.base_at),
        uuids=uuid_values,
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / "g8-boundary-change-plan.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return {
        "status": "PLAN_READY_FOR_EXPLICIT_APPROVAL",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "plan_path": output_path.relative_to(PROJECT_ROOT).as_posix(),
        "case_ids": plan["case_ids"],
        "max_changes": plan["max_changes"],
        "database_writes": 0,
        "outbox_claims": 0,
        "files_deleted": 0,
        "database_physical_deletions": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--task-id", default="b476b901-b78e-5c3e-afd9-6fc880f20623")
    parser.add_argument("--record-id", type=int, default=24)
    parser.add_argument("--read-item-id", type=int, default=131)
    parser.add_argument("--read-resource-id", type=int, default=6299)
    parser.add_argument("--exposure-item-id", type=int, default=132)
    parser.add_argument("--exposure-resource-id", type=int, default=7999)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--base-at", default="2026-08-12T09:30:00Z")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(execute(args))
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        asyncmy.errors.Error,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
