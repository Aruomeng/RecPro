#!/usr/bin/env python3
"""Apply one approved plan against an exact existing G5 Outbox id set."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.composition import build_profile_outbox_worker
from scripts.build_g5_feedback_http_plan import canonical, load_pass_baseline
from scripts.build_g5_pending_outbox_plan import (
    MUTABLE_TABLES,
    PROJECT_ROOT,
    SCHEMA_PATH,
    TARGET_PATTERN,
    connect,
    read_target_snapshot,
    sha256_bytes,
    validate_target_snapshot,
)
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g5_feedback_http_readonly import read_identity_and_grants, read_snapshot
from scripts.verify_g7_mysql_http_readonly import build_settings


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def resolve_inside_root(value: Path, *, label: str) -> Path:
    resolved = (value if value.is_absolute() else PROJECT_ROOT / value).resolve(strict=True)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def extract_outbox_ids(plan: Mapping[str, Any]) -> tuple[int, ...]:
    identifiers = [
        str(target["identifier"])
        for target in plan.get("targets", ())
        if str(target.get("identifier", "")).startswith("recpro.profile_update_outbox#")
    ]
    if len(identifiers) != 1:
        raise ValueError("plan must contain exactly one exact Outbox target")
    match = TARGET_PATTERN.fullmatch(identifiers[0])
    if match is None:
        raise ValueError("exact Outbox target identifier is invalid")
    ids = tuple(int(item) for item in match.group(1).split(","))
    if tuple(sorted(set(ids))) != ids:
        raise ValueError("exact Outbox ids must be sorted and unique")
    return ids


def validate_plan(path: Path, *, approved_plan_id: str, approved_plan_hash: str) -> tuple[dict[str, Any], bytes]:
    raw = resolve_inside_root(path, label="G5 exact Outbox plan").read_bytes()
    plan = json.loads(raw.decode("utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan))
    if errors:
        raise ValueError("ChangePlan violates schema")
    if plan.get("classification") != "S2_CONTROLLED_UPDATE" or plan.get("mode") != "DRY_RUN":
        raise ValueError("only an S2_CONTROLLED_UPDATE DRY_RUN plan may be applied")
    if str(plan.get("plan_id")) != approved_plan_id:
        raise ValueError("approved plan id does not match the ChangePlan")
    if HASH_PATTERN.fullmatch(approved_plan_hash) is None or plan.get("plan_hash") != approved_plan_hash:
        raise ValueError("approved plan hash does not match the ChangePlan")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if sha256_bytes(canonical(unsigned)) != approved_plan_hash:
        raise ValueError("ChangePlan canonical hash does not match plan_hash")
    if plan.get("safety_assertions") != {
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "overwrite_existing": False,
        "destructive_capabilities_required": False,
        "counts_must_not_decrease": True,
    }:
        raise ValueError("ChangePlan safety assertions are not fail-closed")
    expected_identifiers = {f"recpro.{table}" for table in MUTABLE_TABLES - {"profile_update_outbox"}}
    observed_identifiers = {
        str(target["identifier"])
        for target in plan["targets"]
        if not str(target["identifier"]).startswith("recpro.profile_update_outbox#")
    }
    if observed_identifiers != expected_identifiers or len(plan["targets"]) != len(MUTABLE_TABLES):
        raise ValueError("ChangePlan target table set is not the exact profile projection boundary")
    expected_operations = {
        table: (
            "UPDATE_STATUS"
            if table in {"profile_update_outbox", "user_profile", "user_interest_tag", "user_negative_preference"}
            else "APPEND"
        )
        for table in MUTABLE_TABLES
    }
    for target in plan["targets"]:
        identifier = str(target["identifier"])
        table = "profile_update_outbox" if identifier.startswith("recpro.profile_update_outbox#") else identifier.rsplit(".", 1)[-1]
        if target["kind"] != "MYSQL" or target["operation"] != expected_operations[table]:
            raise ValueError(f"ChangePlan operation is invalid for {table}")
    extract_outbox_ids(plan)
    return plan, raw


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / args.run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    plan, _plan_raw = validate_plan(
        args.plan, approved_plan_id=args.plan_id, approved_plan_hash=args.approved_plan_hash
    )
    baseline, baseline_raw = load_pass_baseline(args.baseline)
    if sha256_bytes(baseline_raw) != plan["input_hashes"]["readonly_baseline_sha256"]:
        raise ValueError("selected baseline hash does not match the ChangePlan")
    if current_git_commit() != plan["git_commit"]:
        raise ValueError("current Git commit does not match the reviewed ChangePlan")
    compose = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    values = {**compose, **read_env(args.secrets_file.resolve(strict=True))}
    if values["COMPOSE_PROJECT_NAME"] != plan["environment"]["environment_id"]:
        raise ValueError("Compose identity does not match the ChangePlan")
    if values["RECPRO_MYSQL_DATABASE"] != plan["environment"]["database_identity"]:
        raise ValueError("database identity does not match the ChangePlan")
    identity = await read_identity_and_grants(values)
    before_names, before_counts = await read_snapshot(values)
    if before_counts != baseline["before_counts"]:
        raise ValueError("live table counts drifted from the selected baseline")
    outbox_ids = extract_outbox_ids(plan)
    before_target = await read_target_snapshot(values, outbox_ids)
    validate_target_snapshot(before_target, outbox_ids)
    if sha256_bytes(canonical(before_target)) != plan["input_hashes"]["target_snapshot_sha256"]:
        raise ValueError("exact Outbox/source/profile target snapshot drifted from the ChangePlan")

    async def worker_connection_factory() -> Any:
        return await connect(values, write_identity=True)

    worker = build_profile_outbox_worker(
        build_settings(dict(values)),
        connection_factory=worker_connection_factory,
        worker_id=f"g5-exact-{outbox_ids[0]}-{outbox_ids[-1]}",
        formula_version="profile-g2-v1",
        max_attempts=3,
        allowed_outbox_ids=outbox_ids,
    )
    receipts = await worker.run_once(limit=len(outbox_ids))
    replay_receipts = await worker.run_once(limit=len(outbox_ids))
    if len(receipts) != len(outbox_ids) or replay_receipts:
        raise ValueError("exact Worker run did not consume every target exactly once")
    if tuple(sorted(int(receipt.outbox_id) for receipt in receipts)) != outbox_ids:
        raise ValueError("Worker returned a receipt outside the exact Outbox allowlist")

    after_names, after_counts = await read_snapshot(values)
    if before_names != after_names:
        raise ValueError("Worker changed the database table set")
    for table in before_counts:
        if after_counts[table] < before_counts[table]:
            raise ValueError(f"table count decreased: {table}")
        if table not in MUTABLE_TABLES and after_counts[table] != before_counts[table]:
            raise ValueError(f"Worker changed a non-target table: {table}")
    row_increase = sum(after_counts[table] - before_counts[table] for table in MUTABLE_TABLES)
    if row_increase > int(plan["max_changes"]):
        raise ValueError("profile projection exceeded the approved bounded row-increase budget")
    after_target = await read_target_snapshot(values, outbox_ids)
    if any(row["status"] != "DONE" for row in after_target["outbox"]):
        raise ValueError("not every exact Outbox target reached DONE")
    if after_target["non_target_outbox_hash"] != before_target["non_target_outbox_hash"]:
        raise ValueError("a non-target Outbox row changed")
    if after_target["source_events"] != before_target["source_events"]:
        raise ValueError("an immutable source behavior event changed")
    before_profile = before_target["user_profile"]
    after_profile = after_target["user_profile"]
    if before_profile is None or after_profile is None:
        raise ValueError("target user profile must exist before and after projection")
    if int(after_profile["profile_version"]) <= int(before_profile["profile_version"]):
        raise ValueError("profile version did not advance after exact Outbox consumption")

    evidence = {
        "schema_version": "g5-existing-outbox-apply-evidence-v1",
        "status": "PASS",
        "run_id": args.run_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "git_commit": plan["git_commit"],
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_database": values["RECPRO_MYSQL_DATABASE"],
        "outbox_ids": outbox_ids,
        "receipt_count": len(receipts),
        "replay_receipt_count": len(replay_receipts),
        "source_event_ids": sorted(int(receipt.source_event_id) for receipt in receipts),
        "profile_version_before": int(before_profile["profile_version"]),
        "profile_version_after": int(after_profile["profile_version"]),
        "before_counts": before_counts,
        "after_counts": after_counts,
        "observed_target_row_increase": row_increase,
        "outbox_claims": len(outbox_ids),
        "business_posts": 0,
        "external_requests": 0,
        "external_llm_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "database_physical_deletions": 0,
        "files_deleted": 0,
        "identity": identity,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence_path = evidence_dir / "g5-existing-outbox-apply.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] exact existing Outbox apply was not completed: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
