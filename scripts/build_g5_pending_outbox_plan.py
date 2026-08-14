#!/usr/bin/env python3
"""Build a zero-write plan for consuming an exact existing G5 Outbox set."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_g5_feedback_http_plan import canonical, load_pass_baseline
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g5_feedback_http_readonly import read_identity_and_grants, read_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
TARGET_PATTERN = re.compile(r"^recpro\.profile_update_outbox#([1-9][0-9]*(?:,[1-9][0-9]*)*)$")
MUTABLE_TABLES = frozenset(
    {
        "profile_update_outbox",
        "profile_replay_run",
        "profile_change_log",
        "domain_state_transition",
        "user_profile",
        "user_interest_tag",
        "user_negative_preference",
    }
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat(timespec="milliseconds") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, Decimal):
        return str(value)
    return value


def normalize_row(columns: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    return {name: json_value(value) for name, value in zip(columns, row, strict=True)}


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("Git HEAD is not a full commit hash")
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    if status.stdout.strip():
        raise ValueError("worktree must be clean before a plan is frozen")
    return commit


def parse_outbox_ids(value: str) -> tuple[int, ...]:
    ids = tuple(int(item) for item in value.split(","))
    if not ids or len(ids) > 100 or len(set(ids)) != len(ids) or any(item <= 0 for item in ids):
        raise ValueError("outbox ids must be 1-100 unique positive integers")
    return tuple(sorted(ids))


async def connect(values: Mapping[str, str], *, write_identity: bool = False) -> Any:
    suffix = "MIGRATION_" if write_identity else ""
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values[f"RECPRO_MYSQL_{suffix}USER"],
        password=values[f"RECPRO_MYSQL_{suffix}PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=60,
        charset="utf8mb4",
        autocommit=not write_identity,
    )


async def read_target_snapshot(values: Mapping[str, str], outbox_ids: tuple[int, ...]) -> dict[str, Any]:
    connection = await connect(values)
    placeholders = ",".join("%s" for _ in outbox_ids)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id,user_id,source_event_id,source_type,payload_json,status,attempts,"
                "next_retry_at,locked_at,locked_by,last_error,created_at,updated_at "
                f"FROM profile_update_outbox WHERE id IN ({placeholders}) ORDER BY id",
                outbox_ids,
            )
            outbox_columns = tuple(item[0] for item in cursor.description)
            outbox = tuple(normalize_row(outbox_columns, row) for row in await cursor.fetchall())
            await cursor.execute(
                "SELECT id,event_uuid,user_id,session_id,task_id,event_type,resource_id,"
                "recommendation_item_id,impression_uuid,query_text,rating,dwell_ms,visible_ratio,"
                "position,reason_code,tag_evidence_json,occurred_at,created_at FROM user_behavior_event "
                f"WHERE id IN (SELECT source_event_id FROM profile_update_outbox WHERE id IN ({placeholders})) ORDER BY id",
                outbox_ids,
            )
            event_columns = tuple(item[0] for item in cursor.description)
            events = tuple(normalize_row(event_columns, row) for row in await cursor.fetchall())
            await cursor.execute(
                "SELECT id,status,attempts,next_retry_at,locked_at,locked_by,last_error,updated_at "
                "FROM profile_update_outbox ORDER BY id"
            )
            all_columns = tuple(item[0] for item in cursor.description)
            all_outbox = tuple(normalize_row(all_columns, row) for row in await cursor.fetchall())
            user_ids = tuple(sorted({int(row["user_id"]) for row in outbox}))
            if len(user_ids) != 1:
                raise ValueError("target Outbox rows must belong to exactly one user")
            await cursor.execute(
                "SELECT user_id,profile_version,profile_confidence,recent_focus_tag_id,"
                "topic_focus_strength,reading_stage,reading_stage_confidence,updated_at "
                "FROM user_profile WHERE user_id = %s",
                (user_ids[0],),
            )
            profile_columns = tuple(item[0] for item in cursor.description)
            profile_row = await cursor.fetchone()
        return {
            "outbox": outbox,
            "source_events": events,
            "non_target_outbox_hash": sha256_bytes(
                canonical(tuple(row for row in all_outbox if int(row["id"]) not in outbox_ids))
            ),
            "user_profile": normalize_row(profile_columns, profile_row) if profile_row else None,
        }
    finally:
        connection.close()


def validate_target_snapshot(snapshot: Mapping[str, Any], outbox_ids: tuple[int, ...]) -> None:
    outbox = tuple(snapshot["outbox"])
    if tuple(int(row["id"]) for row in outbox) != outbox_ids:
        raise ValueError("not every exact Outbox target exists")
    if any(row["status"] != "PENDING" or int(row["attempts"]) >= 3 for row in outbox):
        raise ValueError("every exact Outbox target must be PENDING below max attempts")
    if len(snapshot["source_events"]) != len(outbox_ids):
        raise ValueError("every exact Outbox target must reference one behavior event")


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    outbox_ids = parse_outbox_ids(args.outbox_ids)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / args.run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    baseline, baseline_raw = load_pass_baseline(args.baseline)
    compose = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    values = {**compose, **read_env(args.secrets_file.resolve(strict=True))}
    before_names, before_counts = await read_snapshot(values)
    if before_counts != baseline["before_counts"]:
        raise ValueError("live table counts drifted from the selected baseline")
    identity = await read_identity_and_grants(values)
    snapshot = await read_target_snapshot(values, outbox_ids)
    validate_target_snapshot(snapshot, outbox_ids)
    git_commit = current_git_commit()
    created_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    target_id = "recpro.profile_update_outbox#" + ",".join(str(item) for item in outbox_ids)
    targets = []
    for table in sorted(MUTABLE_TABLES):
        operation = "UPDATE_STATUS" if table in {"profile_update_outbox", "user_profile", "user_interest_tag", "user_negative_preference"} else "APPEND"
        identifier = target_id if table == "profile_update_outbox" else f"recpro.{table}"
        targets.append(
            {
                "kind": "MYSQL",
                "identifier": identifier,
                "operation": operation,
                "expected_before_count": int(before_counts[table]),
                "expected_after_min_count": int(before_counts[table]),
            }
        )
    plan = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"g5-existing-outbox-plan:{args.run_id}")),
        "created_at": created_at,
        "git_commit": git_commit,
        "classification": "S2_CONTROLLED_UPDATE",
        "mode": "DRY_RUN",
        "intent": f"Consume only existing profile Outbox ids {outbox_ids}; project their immutable behavior facts and retain every row.",
        "environment": {
            "environment_id": values["COMPOSE_PROJECT_NAME"],
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": f"mysql@127.0.0.1:{values['RECPRO_MYSQL_HOST_PORT']}",
            "database_identity": values["RECPRO_MYSQL_DATABASE"],
            "index_namespace": None,
        },
        "targets": targets,
        "input_hashes": {
            "readonly_baseline_sha256": sha256_bytes(baseline_raw),
            "target_snapshot_sha256": sha256_bytes(canonical(snapshot)),
        },
        "idempotency_key": f"g5-existing-outbox-{outbox_ids[0]}-{outbox_ids[-1]}-{git_commit[:12]}",
        "request_run_id": args.run_id,
        "max_changes": 24,
        "preconditions": [
            f"only Outbox ids {outbox_ids} may be claimed or status-updated and worker limit equals {len(outbox_ids)}",
            "every target row is PENDING, below max attempts, belongs to one user, and references one immutable behavior event",
            "the complete non-target Outbox mutable-state hash must remain unchanged",
            "Git commit, Compose identity, database identity, full table counts, baseline hash, and target snapshot hash must match",
            "only the seven declared profile projection tables may change; all table counts must remain non-decreasing",
            "no file deletion, database physical deletion, migration, seed, Neo4j write, Chroma write, external HTTP request, or LLM request is permitted",
            "apply requires explicit approval of this unchanged plan_id and plan_hash and executes at most once",
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
        raise ValueError("generated ChangePlan violates schema: " + "; ".join(error.message for error in errors))
    after_names, after_counts = await read_snapshot(values)
    if before_names != after_names or before_counts != after_counts:
        raise ValueError("plan generation changed database state")
    evidence_dir.mkdir(parents=True, exist_ok=False)
    plan_path = evidence_dir / "g5-existing-outbox-change-plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "PLAN_READY",
        "path": plan_path.relative_to(PROJECT_ROOT).as_posix(),
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "git_commit": git_commit,
        "outbox_ids": outbox_ids,
        "user_id": snapshot["outbox"][0]["user_id"],
        "database_writes": 0,
        "outbox_claims": 0,
        "files_deleted": 0,
        "database_physical_deletions": 0,
        "identity": identity,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--outbox-ids", default="47,48")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] exact existing Outbox plan was not generated: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
