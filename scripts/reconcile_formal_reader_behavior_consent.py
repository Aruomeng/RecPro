#!/usr/bin/env python3
"""Reconcile an already-approved consent run without replaying any POST.

The first approved consent executor appended the identity facts successfully
but failed while creating its acceptance JSON because the plan directory had
already been created by the builder.  This command is a read-only reconciler:
it verifies the original plan hash, compares the live database with the
frozen baseline and expected deltas, and writes the missing acceptance
artifact.  It never calls the identity API and never retries the consent.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_formal_reader_behavior_consent_plan import (
    CONSENT_ACTION,
    CONSENT_POLICY_VERSION,
    CONSENT_SCOPE,
    CONSENT_SOURCE,
    FORMAL_READER_ID,
    PROJECT_ROOT,
    SCHEMA_PATH,
    canonical,
    connect_runtime,
    database_identity,
    read_full_counts,
    read_identity_state,
)
from scripts.execute_formal_reader_behavior_consent_plan import (
    EXPECTED_DELTAS,
    _validate_targets,
    approved_baseline,
    approved_consent,
)
from scripts.validate_runtime_env import read_env


HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if GIT_PATTERN.fullmatch(value) is None:
        raise ValueError("current Git commit is invalid")
    return value


def _load_plan(path: Path, plan_id: str, plan_hash: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(PROJECT_ROOT):
        raise ValueError("plan path must stay inside the repository")
    plan = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise ValueError("ChangePlan must be an object")
    Draft202012Validator(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    ).validate(plan)
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash:
        raise ValueError("approved plan id/hash does not match the ChangePlan")
    if HASH_PATTERN.fullmatch(plan_hash) is None:
        raise ValueError("approved plan hash is invalid")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != plan_hash:
        raise ValueError("ChangePlan canonical hash does not match plan_hash")
    if not GIT_PATTERN.fullmatch(str(plan.get("git_commit", ""))):
        raise ValueError("original plan Git commit is invalid")
    if plan.get("classification") != "S2_CONTROLLED_UPDATE" or plan.get("mode") != "DRY_RUN":
        raise ValueError("only the approved consent DRY_RUN plan can be reconciled")
    if int(plan.get("max_changes", -1)) != sum(EXPECTED_DELTAS.values()):
        raise ValueError("approved consent plan has an unexpected append budget")
    baseline = approved_baseline(plan)
    approved_consent(plan)
    _validate_targets(plan, baseline)
    return plan


async def _read_session_and_consent(
    values: Mapping[str, str],
) -> dict[str, Any]:
    connection = await connect_runtime(values)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT consent_version, action, policy_version, source "
                "FROM user_personalization_consent_fact "
                "WHERE user_id=%s AND scope=%s ORDER BY consent_version DESC LIMIT 1",
                (FORMAL_READER_ID, CONSENT_SCOPE),
            )
            consent = await cursor.fetchone()
            await cursor.execute(
                "SELECT user_id, revoked_at, revoke_reason FROM iam_auth_session "
                "WHERE user_id=%s ORDER BY issued_at DESC LIMIT 1",
                (FORMAL_READER_ID,),
            )
            session = await cursor.fetchone()
            await cursor.execute(
                "SELECT COUNT(*), SUM(revoked_at IS NOT NULL) FROM iam_refresh_token "
                "WHERE session_uuid=(SELECT session_uuid FROM iam_auth_session "
                "WHERE user_id=%s ORDER BY issued_at DESC LIMIT 1)",
                (FORMAL_READER_ID,),
            )
            token = await cursor.fetchone()
    finally:
        connection.close()
    return {
        "latest_consent": None if consent is None else {
            "consent_version": int(consent[0]),
            "action": str(consent[1]),
            "policy_version": str(consent[2]),
            "source": str(consent[3]),
        },
        "latest_session": None if session is None else {
            "user_id": int(session[0]),
            "revoked": session[1] is not None,
            "revoke_reason": str(session[2]) if session[2] is not None else None,
        },
        "latest_session_refresh_tokens": {
            "count": int(token[0] or 0) if token is not None else 0,
            "revoked_count": int(token[1] or 0) if token is not None else 0,
        },
    }


def _evidence_path(plan: Mapping[str, Any]) -> Path:
    return PROJECT_ROOT / "artifacts" / "verification" / "iam" / "formal-reader-behavior-consent" / str(plan["request_run_id"]) / "acceptance.json"


async def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    plan = _load_plan(args.plan, args.plan_id, args.plan_hash)
    baseline = approved_baseline(plan)
    values = read_env(args.env_file.resolve(strict=True))
    current_identity = database_identity(values)
    if current_identity != baseline.get("database_identity"):
        raise ValueError("live MySQL identity differs from the approved plan")
    path = _evidence_path(plan).resolve()
    if path.exists():
        raise FileExistsError("acceptance artifact already exists; refusing to overwrite it")
    connection = await connect_runtime(values)
    try:
        names, counts = await read_full_counts(connection)
        identity = await read_identity_state(connection)
    finally:
        connection.close()
    baseline_counts = {str(key): int(value) for key, value in baseline["counts"].items()}
    if names != tuple(sorted(baseline_counts)):
        raise ValueError("live MySQL table set differs from the approved baseline")
    expected_counts = dict(baseline_counts)
    for table, delta in EXPECTED_DELTAS.items():
        expected_counts[table] = int(expected_counts[table]) + delta
    if counts != expected_counts:
        raise ValueError("live MySQL count delta does not match the approved consent plan")
    if identity["account"] != baseline["identity"]["account"] or identity["roles"] != baseline["identity"]["roles"]:
        raise ValueError("consent run changed account authorization state")
    if not identity["consents"].get(CONSENT_SCOPE, False):
        raise ValueError("effective BEHAVIOR_LEARNING consent is not granted")
    session = await _read_session_and_consent(values)
    latest_consent = session["latest_consent"]
    if latest_consent != {
        "consent_version": int(latest_consent["consent_version"]) if latest_consent else -1,
        "action": CONSENT_ACTION,
        "policy_version": CONSENT_POLICY_VERSION,
        "source": CONSENT_SOURCE,
    }:
        raise ValueError("latest behavior-learning consent fact does not match the approved grant")
    latest_session = session["latest_session"]
    if latest_session is None or latest_session["user_id"] != FORMAL_READER_ID or not latest_session["revoked"] or latest_session["revoke_reason"] != "LOGOUT":
        raise ValueError("the latest planned login session is not revoked with LOGOUT")
    token_state = session["latest_session_refresh_tokens"]
    if token_state["count"] != 1 or token_state["revoked_count"] != 1:
        raise ValueError("the planned login refresh token was not revoked")

    evidence = {
        "schema_version": "formal-reader-behavior-consent-acceptance-v1",
        "status": "PASS",
        "mode": "APPROVED_PLAN_READ_ONLY_RECONCILIATION",
        "verified_at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "original_plan_git_commit": plan["git_commit"],
        "reconciliation_git_commit": _current_commit(),
        "run_id": plan["request_run_id"],
        "user_id": FORMAL_READER_ID,
        "consent_scope": CONSENT_SCOPE,
        "approved_plan_effective": True,
        "original_executor_replayed": False,
        "api_posts_replayed": 0,
        "before_counts": baseline_counts,
        "after_counts": counts,
        "append_deltas": {table: int(counts[table]) - int(baseline_counts[table]) for table in sorted(counts)},
        "approved_plan_database_append_rows": sum(EXPECTED_DELTAS.values()),
        "reconciliation_database_writes": 0,
        "effective_consents_after": identity["consents"],
        "latest_consent_fact": latest_consent,
        "latest_session_revoked": True,
        "latest_session_revoke_reason": "LOGOUT",
        "latest_session_refresh_token_count": token_state["count"],
        "latest_session_refresh_token_revoked_count": token_state["revoked_count"],
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "outbox_claims": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "overwritten_inputs": 0,
        "notes": [
            "The original executor completed the approved identity API sequence and failed only while creating this acceptance artifact because its pre-created run directory was treated as an error.",
            "This reconciliation performed SELECT-only verification and created the missing artifact; it did not retry login, consent, logout, or any business POST.",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return {
        "status": "PASS",
        "mode": evidence["mode"],
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "evidence_path": path.relative_to(PROJECT_ROOT).as_posix(),
        "api_posts_replayed": 0,
        "reconciliation_database_writes": 0,
        "approved_plan_database_append_rows": 5,
        "deepseek_requests": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    args = parser.parse_args()
    try:
        result = asyncio.run(reconcile(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] formal reader consent reconciliation did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
