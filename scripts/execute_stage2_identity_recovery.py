#!/usr/bin/env python3
"""Apply the approved forward-only Stage 2 identity recovery.

The recovery is intentionally narrower than the original closure.  It accepts
only the observed partial state, reads the password material created by that
run, appends the missing declared profile and a fresh bounded verification
session pair, then leaves all prior facts untouched.  A failure after the
first business request is reported as an unknown partial write and requires a
new successor plan; this command never retries, deletes, or compensates.
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
from typing import Any, Sequence

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.identity.domain import ConsentScope
from scripts.build_stage2_identity_closure_plan import (
    PROJECT_ROOT,
    SCHEMA,
    canonical,
    file_sha256,
)
from scripts.build_stage2_identity_recovery_plan import (
    APPEND_ROWS,
    CONTROLLED_UPDATE_OPERATIONS,
    DATABASE_IDENTITY_PATTERN,
    EXPECTED_DELTAS,
    MAXIMUM_CHANGES,
    PARTIAL_BASELINE,
    RUN_ID_PATTERN,
    TEST_READER_ID,
    TEST_READER_IDENTIFIER,
    TEST_READER_PROFILE,
    INPUT_PATHS,
    expected_fingerprint,
    targets_for,
)
from scripts.execute_stage2_identity_closure import (
    BASE_URL,
    _HTTPClient,
    _read_only_state,
    _write_evidence,
)
from scripts.validate_runtime_env import read_env


DEFAULT_PLAN = PROJECT_ROOT / "plans/stage2-identity-recovery-successor-20260831.json"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.host"
DEFAULT_ADMIN_FILE = PROJECT_ROOT / ".env.admin-login.local"
DEFAULT_READER_FILE = PROJECT_ROOT / ".env.stage2-reader-login.local"
BASELINE_CONSENTS = sorted([
    [ConsentScope.BEHAVIOR_LEARNING.value, "WITHDRAW"],
    [ConsentScope.DECLARED_PROFILE.value, "GRANT"],
    [ConsentScope.PERSONALIZED_RECOMMENDATION.value, "GRANT"],
    [ConsentScope.RESEARCH_ANALYTICS.value, "GRANT"],
])
_HASH = re.compile(r"^[0-9a-f]{64}$")


class RecoveryExecutionError(RuntimeError):
    """Sanitized failure marker that records whether a business write began."""

    def __init__(self, message: str, *, writes_started: bool) -> None:
        super().__init__(message)
        self.writes_started = writes_started


def reviewed_commit_is_ancestor(commit: str) -> bool:
    return bool(
        re.fullmatch(r"[0-9a-f]{40}", commit)
        and subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True,
        ).returncode
        == 0
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Stage 2 recovery plan must be a JSON object")
    return value


def validate_plan(path: Path, *, plan_id: str, approved_hash: str) -> dict[str, Any]:
    plan = _read_json(path.resolve(strict=True))
    Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    ).validate(plan)
    if (
        plan.get("plan_id") != plan_id
        or plan.get("plan_hash") != approved_hash
        or _HASH.fullmatch(approved_hash) is None
    ):
        raise ValueError("approved Stage 2 recovery plan identity does not match")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("Stage 2 recovery plan canonical hash does not match")
    commit = str(plan.get("git_commit", ""))
    if not reviewed_commit_is_ancestor(commit):
        raise ValueError("reviewed Stage 2 recovery commit is not an ancestor")
    if (
        plan.get("classification") != "S2_CONTROLLED_UPDATE"
        or plan.get("mode") != "APPLY"
        or plan.get("max_changes") != MAXIMUM_CHANGES
    ):
        raise ValueError("Stage 2 recovery operation budget is invalid")
    run_id = str(plan.get("request_run_id", ""))
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("Stage 2 recovery run identity is invalid")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != set(INPUT_PATHS):
        raise ValueError("Stage 2 recovery input hash set is incomplete")
    for relative in INPUT_PATHS:
        if inputs.get(relative) != file_sha256(PROJECT_ROOT / relative):
            raise ValueError(f"Stage 2 recovery input hash mismatch: {relative}")
    if plan.get("targets") != targets_for(run_id):
        raise ValueError("Stage 2 recovery target set is not the fixed allowlist")
    environment = plan.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("Stage 2 recovery environment is missing")
    database_identity = str(environment.get("database_identity", ""))
    if DATABASE_IDENTITY_PATTERN.fullmatch(database_identity) is None:
        raise ValueError("Stage 2 recovery database identity is outside the fixed target")
    if environment.get("host_fingerprint") != expected_fingerprint(
        database_identity, commit, run_id,
    ):
        raise ValueError("Stage 2 recovery environment fingerprint does not match")
    if plan.get("idempotency_key") != f"stage2-identity-recovery-{run_id}":
        raise ValueError("Stage 2 recovery idempotency key does not match run identity")
    return plan


def dry_run_report() -> dict[str, object]:
    return {
        "status": "PASS",
        "mode": "NO_WRITE_STAGE2_IDENTITY_RECOVERY_DRY_RUN",
        "observed_reader_user_id": TEST_READER_ID,
        "observed_reader_identifier": TEST_READER_IDENTIFIER,
        "append_rows": APPEND_ROWS,
        "controlled_update_operations": CONTROLLED_UPDATE_OPERATIONS,
        "maximum_changes": MAXIMUM_CHANGES,
        "database_connections": 0,
        "database_writes": 0,
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "container_deletions": 0,
        "volume_deletions": 0,
    }


def _read_protected_values(path: Path, required: tuple[str, ...]) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"protected credential path is not a regular file: {path.name}")
    if resolved.stat().st_mode & 0o777 != 0o600:
        raise ValueError(f"protected credential path must have mode 0600: {path.name}")
    values = read_env(resolved)
    if any(not values.get(key, "") for key in required):
        raise ValueError(f"protected credential material is incomplete: {path.name}")
    return values


async def _profile_projection(env: dict[str, str]) -> tuple[object, ...] | None:
    port = env.get("RECPRO_MYSQL_HOST_PORT") or env.get("RECPRO_MYSQL_PORT")
    user = env.get("RECPRO_MYSQL_USER", "")
    password = env.get("RECPRO_MYSQL_PASSWORD", "")
    database = env.get("RECPRO_MYSQL_DATABASE", "")
    if not port or not user or not password or not database:
        raise ValueError("runtime MySQL read-only credentials are incomplete")
    connection = await asyncmy.connect(
        host="127.0.0.1", port=int(port), user=user, password=password,
        db=database, autocommit=True, connect_timeout=3,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT major, grade, research_direction, preferred_language, "
                "personalization_enabled, declared_version "
                "FROM user_declared_profile WHERE user_id=%s",
                (TEST_READER_ID,),
            )
            row = await cursor.fetchone()
        return tuple(row) if row is not None else None
    finally:
        connection.close()


def _require_status(status: int, expected: int, step: str) -> None:
    if status != expected:
        raise RuntimeError(f"Stage 2 recovery API step {step} returned HTTP {status}")


def _expected_after(before: dict[str, Any]) -> dict[str, int]:
    expected = dict(before["counts"])
    for table, delta in EXPECTED_DELTAS.items():
        expected[table] = expected.get(table, 0) + delta
    return expected


async def apply_plan(
    *, plan_path: Path, plan_id: str, approved_hash: str,
    env_path: Path, admin_path: Path, reader_path: Path,
) -> dict[str, object]:
    plan = validate_plan(plan_path, plan_id=plan_id, approved_hash=approved_hash)
    run_id = str(plan["request_run_id"])
    env = read_env(env_path.resolve(strict=True))
    database_identity = str(plan["environment"]["database_identity"])
    port = env.get("RECPRO_MYSQL_HOST_PORT") or env.get("RECPRO_MYSQL_PORT")
    if f"mysql://127.0.0.1:{port}/{env.get('RECPRO_MYSQL_DATABASE', '')}" != database_identity:
        raise ValueError("Stage 2 recovery MySQL environment does not match approved plan")
    if not env.get("RECPRO_AUTH_IDENTIFIER_PEPPER"):
        raise ValueError("Stage 2 recovery identifier pepper is missing")

    before = await _read_only_state(env)
    evidence_path = PROJECT_ROOT / "artifacts/verification/stage2-identity-recovery" / run_id / "acceptance.json"
    if before["complete"]:
        if not reader_path.resolve().exists():
            raise ValueError("Stage 2 recovery is complete but protected reader credential is missing")
        evidence = {
            "status": "PASS",
            "mode": "IDEMPOTENT_REPLAY",
            "run_id": run_id,
            "plan_id": plan_id,
            "plan_hash": approved_hash,
            "verified_at": datetime.now(UTC).isoformat(),
            "database_writes": 0,
            "deepseek_requests": 0,
            "database_physical_deletions": 0,
            "file_deletions": 0,
            "credential_values_printed": 0,
            "read_only_state": before,
        }
        if evidence_path.exists():
            evidence["evidence_path"] = str(evidence_path.relative_to(PROJECT_ROOT))
        else:
            path = _write_evidence(run_id, evidence)
            evidence["evidence_path"] = str(path.relative_to(PROJECT_ROOT))
        return evidence

    if before["counts"] != PARTIAL_BASELINE:
        raise ValueError("Stage 2 recovery baseline table counts do not match the observed partial state")
    if (
        before["next_user_id"] != TEST_READER_ID
        or before["reader_user_id"] != TEST_READER_ID
        or before["account"] != ["ACTIVE", 2, 1, 0]
        or before["credential_count"] != 1
        or before["activation_token_count"] != 1
        or before["effective_consents"] != BASELINE_CONSENTS
        or before["profile_count"] != 0
    ):
        raise ValueError("Stage 2 recovery reader state is not the observed partial state")
    if evidence_path.exists():
        raise ValueError("Stage 2 recovery evidence path exists; refusing overwrite")

    # File reads and readiness are deliberately completed before any business
    # request.  Password and one-time material never enters logs or evidence.
    admin_values = _read_protected_values(
        admin_path, ("RECPRO_ADMIN_LOGIN_IDENTIFIER", "RECPRO_ADMIN_LOGIN_PASSWORD"),
    )
    reader_values = _read_protected_values(
        reader_path, (
            "RECPRO_STAGE2_READER_IDENTIFIER", "RECPRO_STAGE2_READER_PASSWORD",
        ),
    )
    if reader_values["RECPRO_STAGE2_READER_IDENTIFIER"] != TEST_READER_IDENTIFIER:
        raise ValueError("protected reader identifier does not match recovery target")
    readiness = _HTTPClient(BASE_URL)
    status, ready_payload = readiness.request("GET", "/api/v1/health/ready")
    _require_status(status, 200, "readiness")
    if not isinstance(ready_payload, dict) or str(ready_payload.get("status", "")).upper() not in {"READY", "UP"}:
        raise ValueError("Stage 2 recovery API readiness is not confirmed")

    client = _HTTPClient(BASE_URL)
    statuses: dict[str, int] = {}
    writes_started = False
    try:
        writes_started = True
        status, payload = client.request(
            "POST", "/api/v1/auth/login",
            payload={
                "identifier_type": "READER_NUMBER",
                "identifier": admin_values["RECPRO_ADMIN_LOGIN_IDENTIFIER"],
                "password": admin_values["RECPRO_ADMIN_LOGIN_PASSWORD"],
                "device_type": "BROWSER",
            },
        )
        statuses["admin_login"] = status
        _require_status(status, 200, "admin_login")
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RuntimeError("admin login response omitted access token")
        admin_access = str(payload["access_token"])

        status, payload = client.request(
            "POST", "/api/v1/auth/login",
            payload={
                "identifier_type": "READER_NUMBER",
                "identifier": reader_values["RECPRO_STAGE2_READER_IDENTIFIER"],
                "password": reader_values["RECPRO_STAGE2_READER_PASSWORD"],
                "device_type": "BROWSER",
            },
        )
        statuses["reader_login"] = status
        _require_status(status, 200, "reader_login")
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RuntimeError("reader login response omitted access token")
        if not isinstance(payload.get("user"), dict) or payload["user"].get("user_id") != TEST_READER_ID:
            raise RuntimeError("reader login response did not reconcile to user 10001")
        reader_access = str(payload["access_token"])

        status, payload = client.request(
            "PUT", "/api/v1/me/declared-profile", payload=TEST_READER_PROFILE,
            headers={"Authorization": f"Bearer {reader_access}"},
        )
        statuses["declared_profile_update"] = status
        _require_status(status, 200, "declared_profile_update")
        if not isinstance(payload, dict) or not isinstance(payload.get("profile"), dict):
            raise RuntimeError("declared profile response omitted profile")
        profile = payload["profile"]
        if any(profile.get(key) != value for key, value in TEST_READER_PROFILE.items()):
            raise RuntimeError("declared profile response did not reconcile to the fixed profile")
        if profile.get("declared_version") != 1 or profile.get("personalization_enabled") is not True:
            raise RuntimeError("declared profile version or compatibility projection is invalid")

        csrf = client.cookies().get("recpro_csrf")
        if not csrf:
            raise RuntimeError("reader login did not issue a CSRF cookie")
        status, payload = client.request(
            "POST", "/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf},
        )
        statuses["reader_refresh_rotation"] = status
        _require_status(status, 200, "reader_refresh_rotation")
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RuntimeError("reader refresh response omitted access token")
        refreshed_reader_access = str(payload["access_token"])

        status, _ = client.request(
            "POST", "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {refreshed_reader_access}"},
        )
        statuses["reader_logout"] = status
        _require_status(status, 204, "reader_logout")
        status, _ = client.request(
            "POST", "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {admin_access}"},
        )
        statuses["admin_logout"] = status
        _require_status(status, 204, "admin_logout")
    except (RuntimeError, OSError) as exc:
        raise RecoveryExecutionError(str(exc), writes_started=writes_started) from exc

    after = await _read_only_state(env)
    if after["counts"] != _expected_after(before):
        raise RecoveryExecutionError(
            "Stage 2 recovery postflight counts do not match the fixed append budget",
            writes_started=True,
        )
    projection = await _profile_projection(env)
    expected_projection = (
        TEST_READER_PROFILE["major"], TEST_READER_PROFILE["grade"],
        TEST_READER_PROFILE["research_direction"], TEST_READER_PROFILE["preferred_language"],
        1, 1,
    )
    if projection != expected_projection or not after["complete"]:
        raise RecoveryExecutionError(
            "Stage 2 recovery did not reconcile the fixed profile and account state",
            writes_started=True,
        )
    evidence = {
        "status": "PASS",
        "mode": "APPLY",
        "run_id": run_id,
        "plan_id": plan_id,
        "plan_hash": approved_hash,
        "verified_at": datetime.now(UTC).isoformat(),
        "fixed_reader": {
            "user_id": TEST_READER_ID,
            "identifier": TEST_READER_IDENTIFIER,
            "credential_path": str(reader_path.resolve()),
            "credential_permissions": "0600",
            "plaintext_values_printed": 0,
        },
        "http_statuses": statuses,
        "before": before,
        "after": after,
        "profile_projection_verified": True,
        "original_partial_sessions_retained": True,
        "append_rows": APPEND_ROWS,
        "controlled_update_operations": CONTROLLED_UPDATE_OPERATIONS,
        "database_writes": MAXIMUM_CHANGES,
        "business_writes": 0,
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "container_deletions": 0,
        "volume_deletions": 0,
    }
    path = _write_evidence(run_id, evidence)
    evidence["evidence_path"] = str(path.relative_to(PROJECT_ROOT))
    return evidence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--approved-plan-hash", default="")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--admin-file", type=Path, default=DEFAULT_ADMIN_FILE)
    parser.add_argument("--reader-file", type=Path, default=DEFAULT_READER_FILE)
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps(dry_run_report(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    try:
        report = asyncio.run(apply_plan(
            plan_path=args.plan, plan_id=args.plan_id,
            approved_hash=args.approved_plan_hash,
            env_path=args.env_file, admin_path=args.admin_file,
            reader_path=args.reader_file,
        ))
    except RecoveryExecutionError as exc:
        print(json.dumps({
            "status": "FAIL",
            "error": type(exc).__name__,
            "message": str(exc),
            "database_writes": "UNKNOWN_AFTER_PARTIAL_FAILURE" if exc.writes_started else 0,
            "partial_failure_requires_new_plan": exc.writes_started,
            "deepseek_requests": 0,
            "file_deletions": 0,
            "database_physical_deletions": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({
            "status": "FAIL",
            "error": type(exc).__name__,
            "message": str(exc),
            "database_writes": 0,
            "partial_failure_requires_new_plan": False,
            "deepseek_requests": 0,
            "file_deletions": 0,
            "database_physical_deletions": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
