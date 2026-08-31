#!/usr/bin/env python3
"""Apply the approved Stage 2 identity closure through the public API.

The default mode is a zero-write dry-run.  ``--apply`` is fail-closed: it
requires the exact ChangePlan identity, an unchanged code boundary, the
expected local MySQL baseline, and the explicit G4 identity API.  It never
deletes, overwrites, or compensates a partially appended fact.  Passwords,
tokens, and response bodies are kept in memory or in a chmod-0600 local
credential file and are never printed or written to evidence.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from http.cookiejar import CookieJar
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.identity.domain import ConsentScope, IdentifierType
from backend.app.identity.security import HMACIdentifierService
from scripts.build_stage2_identity_closure_plan import (
    APPEND_ROWS,
    CONTROLLED_UPDATE_OPERATIONS,
    DATABASE_IDENTITY_PATTERN,
    FIXED_BASELINE,
    INPUT_PATHS,
    MAXIMUM_CHANGES,
    PROJECT_ROOT,
    SCHEMA,
    TEST_READER_DISPLAY_NAME,
    TEST_READER_ID,
    TEST_READER_IDENTIFIER,
    TEST_READER_PROFILE,
    canonical,
    expected_fingerprint,
    file_sha256,
    targets_for,
)
from scripts.validate_runtime_env import read_env


DEFAULT_PLAN = PROJECT_ROOT / "plans/stage2-identity-closure-successor-20260831.json"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.host"
DEFAULT_ADMIN_FILE = PROJECT_ROOT / ".env.admin-login.local"
DEFAULT_READER_FILE = PROJECT_ROOT / ".env.stage2-reader-login.local"
BASE_URL = "http://127.0.0.1:8000"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ALLOWED_COUNT_TABLES = frozenset({
    *FIXED_BASELINE,
    "iam_login_identifier",
    "iam_user_role_fact",
    "iam_password_credential",
    "iam_role_permission_fact",
    "iam_permission",
    "iam_role",
    "recommendation_task",
    "user_behavior_event",
})
_EXPECTED_DELTAS = {
    "iam_user_account": 1,
    "iam_login_identifier": 1,
    "iam_password_credential": 1,
    "iam_user_role_fact": 1,
    "iam_auth_session": 2,
    "iam_refresh_token": 3,
    "iam_action_token": 1,
    "iam_security_event": 6,
    "user_personalization_consent_fact": 5,
    "user_declared_profile": 1,
    "user_declared_profile_history": 1,
}


def reviewed_commit_is_ancestor(commit: str) -> bool:
    return bool(
        re.fullmatch(r"[0-9a-f]{40}", commit)
        and subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
        ).returncode
        == 0
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("ChangePlan must be a JSON object")
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
        raise ValueError("approved Stage 2 plan identity does not match")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("Stage 2 plan canonical hash does not match")
    commit = str(plan.get("git_commit", ""))
    if not reviewed_commit_is_ancestor(commit):
        raise ValueError("reviewed Stage 2 commit is not an ancestor")
    if (
        plan.get("classification") != "S2_CONTROLLED_UPDATE"
        or plan.get("mode") != "APPLY"
        or plan.get("max_changes") != MAXIMUM_CHANGES
    ):
        raise ValueError("Stage 2 plan operation budget is invalid")
    run_id = str(plan.get("request_run_id", ""))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", run_id):
        raise ValueError("Stage 2 run identity is invalid")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != set(INPUT_PATHS):
        raise ValueError("Stage 2 input hash set is incomplete")
    for relative in INPUT_PATHS:
        if inputs.get(relative) != file_sha256(PROJECT_ROOT / relative):
            raise ValueError(f"Stage 2 input hash mismatch: {relative}")
    targets = plan.get("targets")
    expected = targets_for(run_id)
    if targets != expected:
        raise ValueError("Stage 2 target set is not the fixed allowlist")
    environment = plan.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("Stage 2 environment is missing")
    database_identity = str(environment.get("database_identity", ""))
    if DATABASE_IDENTITY_PATTERN.fullmatch(database_identity) is None:
        raise ValueError("Stage 2 database identity is outside the fixed local target")
    if environment.get("host_fingerprint") != expected_fingerprint(
        database_identity, commit, run_id,
    ):
        raise ValueError("Stage 2 environment fingerprint does not match")
    if plan.get("idempotency_key") != f"stage2-identity-closure-{run_id}":
        raise ValueError("Stage 2 idempotency key does not match run identity")
    return plan


def dry_run_report() -> dict[str, object]:
    return {
        "status": "PASS",
        "mode": "NO_WRITE_STAGE2_IDENTITY_CLOSURE_DRY_RUN",
        "fixed_reader_user_id": TEST_READER_ID,
        "fixed_reader_identifier": TEST_READER_IDENTIFIER,
        "append_rows": APPEND_ROWS,
        "controlled_update_operations": CONTROLLED_UPDATE_OPERATIONS,
        "maximum_changes": MAXIMUM_CHANGES,
        "database_connections": 0,
        "database_writes": 0,
        "business_writes": 0,
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "container_deletions": 0,
        "volume_deletions": 0,
    }


async def _table_counts(connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in sorted(_ALLOWED_COUNT_TABLES):
            await cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema=DATABASE() AND table_name=%s",
                (table,),
            )
            if int((await cursor.fetchone())[0]) != 1:
                continue
            await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            counts[table] = int((await cursor.fetchone())[0])
    return counts


async def _mysql_connection(env: dict[str, str]) -> Any:
    port = env.get("RECPRO_MYSQL_HOST_PORT") or env.get("RECPRO_MYSQL_PORT")
    user = env.get("RECPRO_MYSQL_USER", "")
    password = env.get("RECPRO_MYSQL_PASSWORD", "")
    database = env.get("RECPRO_MYSQL_DATABASE", "")
    if not port or not user or not password or not database:
        raise ValueError("runtime MySQL read-only credentials are incomplete")
    return await asyncmy.connect(
        host="127.0.0.1", port=int(port), user=user, password=password,
        db=database, autocommit=True, connect_timeout=3,
    )


async def _read_only_state(env: dict[str, str]) -> dict[str, Any]:
    connection = await _mysql_connection(env)
    try:
        counts = await _table_counts(connection)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT AUTO_INCREMENT FROM information_schema.tables "
                "WHERE table_schema=DATABASE() AND table_name='iam_user_account'",
            )
            next_user_id = int((await cursor.fetchone())[0])
            identifiers = HMACIdentifierService(
                env["RECPRO_AUTH_IDENTIFIER_PEPPER"].encode(),
            )
            identifier_hash = identifiers.digest(
                identifiers.normalize(IdentifierType.READER_NUMBER, TEST_READER_IDENTIFIER),
            )
            await cursor.execute(
                "SELECT user_id FROM iam_login_identifier WHERE identifier_type=%s "
                "AND identifier_hash=%s",
                (IdentifierType.READER_NUMBER.value, identifier_hash),
            )
            reader_row = await cursor.fetchone()
            reader_user_id = int(reader_row[0]) if reader_row is not None else None
            await cursor.execute(
                "SELECT status,auth_version,role_version,must_change_password "
                "FROM iam_user_account WHERE user_id=%s",
                (TEST_READER_ID,),
            )
            account_row = await cursor.fetchone()
            await cursor.execute(
                "SELECT COUNT(*) FROM iam_password_credential WHERE user_id=%s",
                (TEST_READER_ID,),
            )
            credential_count = int((await cursor.fetchone())[0])
            await cursor.execute(
                "SELECT scope,action FROM user_effective_personalization_consent_v "
                "WHERE user_id=%s ORDER BY scope",
                (TEST_READER_ID,),
            )
            effective_consents = [
                [str(row[0]), str(row[1])] for row in await cursor.fetchall()
            ]
            await cursor.execute(
                "SELECT COUNT(*) FROM user_declared_profile WHERE user_id=%s",
                (TEST_READER_ID,),
            )
            profile_count = int((await cursor.fetchone())[0])
            await cursor.execute(
                "SELECT COUNT(*) FROM iam_action_token WHERE user_id=%s "
                "AND purpose='ACTIVATE_ACCOUNT'",
                (TEST_READER_ID,),
            )
            activation_token_count = int((await cursor.fetchone())[0])
        complete = (
            reader_user_id == TEST_READER_ID
            and account_row is not None
            and tuple(account_row) == ("ACTIVE", 2, 1, 0)
            and credential_count == 1
            and activation_token_count == 1
            and effective_consents == sorted([
                [ConsentScope.BEHAVIOR_LEARNING.value, "WITHDRAW"],
                [ConsentScope.DECLARED_PROFILE.value, "GRANT"],
                [ConsentScope.PERSONALIZED_RECOMMENDATION.value, "GRANT"],
                [ConsentScope.RESEARCH_ANALYTICS.value, "GRANT"],
            ])
            and profile_count == 1
        )
        return {
            "counts": counts,
            "next_user_id": next_user_id,
            "reader_user_id": reader_user_id,
            "account": list(account_row) if account_row is not None else None,
            "credential_count": credential_count,
            "activation_token_count": activation_token_count,
            "effective_consents": effective_consents,
            "profile_count": profile_count,
            "complete": complete,
        }
    finally:
        connection.close()


class _HTTPClient:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._cookie_jar = CookieJar()
        # The identity executor is deliberately pinned to the local workbench.
        # Never route loopback authentication traffic through a workstation
        # HTTP proxy: a proxy can turn a healthy local readiness response into
        # a misleading 502 and leave a forward-only run half-complete.
        self._opener = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(self._cookie_jar),
        )

    def cookies(self) -> dict[str, str]:
        return {cookie.name: cookie.value for cookie in self._cookie_jar}

    def request(
        self, method: str, path: str, *, payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object] | None]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = {"Accept": "application/json"}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = Request(
            self._base_url + path, data=body, headers=request_headers, method=method,
        )
        try:
            with self._opener.open(request, timeout=10) as response:
                raw = response.read()
                status = int(response.status)
        except HTTPError as exc:
            # Do not include the response body: it could contain credentials or
            # implementation details that are outside the evidence contract.
            return int(exc.code), None
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"identity API unavailable ({type(exc).__name__})") from exc
        if not raw:
            return status, None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, None
        return status, value if isinstance(value, dict) else None


def _require_status(status: int, expected: int, step: str) -> None:
    if status != expected:
        raise RuntimeError(f"Stage 2 identity API step {step} returned HTTP {status}")


def _write_reader_credential(path: Path, *, password: str) -> None:
    destination = path.resolve()
    if destination.exists():
        raise ValueError("Stage 2 reader credential file exists; refusing to overwrite it")
    payload = (
        f"RECPRO_STAGE2_READER_USER_ID={TEST_READER_ID}\n"
        f"RECPRO_STAGE2_READER_IDENTIFIER={TEST_READER_IDENTIFIER}\n"
        f"RECPRO_STAGE2_READER_PASSWORD={password}\n"
    ).encode("utf-8")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    os.chmod(destination, 0o600)


def _evidence_path(run_id: str) -> Path:
    return PROJECT_ROOT / "artifacts/verification/stage2-identity-closure" / run_id / "acceptance.json"


def _write_evidence(run_id: str, evidence: dict[str, object]) -> Path:
    path = _evidence_path(run_id).resolve()
    if path.exists():
        raise ValueError("Stage 2 evidence path exists; refusing to overwrite it")
    path.parent.mkdir(parents=True, exist_ok=False)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return path


async def apply_plan(
    *, plan_path: Path, plan_id: str, approved_hash: str,
    env_path: Path, admin_path: Path, reader_path: Path,
) -> dict[str, object]:
    plan = validate_plan(plan_path, plan_id=plan_id, approved_hash=approved_hash)
    run_id = str(plan["request_run_id"])
    env = read_env(env_path.resolve(strict=True))
    db_identity = str(plan["environment"]["database_identity"])
    port = env.get("RECPRO_MYSQL_HOST_PORT") or env.get("RECPRO_MYSQL_PORT")
    if f"mysql://127.0.0.1:{port}/{env.get('RECPRO_MYSQL_DATABASE', '')}" != db_identity:
        raise ValueError("Stage 2 MySQL environment does not match approved plan")
    if not env.get("RECPRO_AUTH_IDENTIFIER_PEPPER"):
        raise ValueError("Stage 2 identifier pepper is missing")
    before = await _read_only_state(env)
    if before["complete"]:
        if not reader_path.resolve().exists():
            raise ValueError("Stage 2 database is complete but protected reader credential is missing")
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
        existing_path = _evidence_path(run_id).resolve()
        if existing_path.exists():
            evidence["evidence_path"] = str(existing_path.relative_to(PROJECT_ROOT))
        else:
            path = _write_evidence(run_id, evidence)
            evidence["evidence_path"] = str(path.relative_to(PROJECT_ROOT))
        return evidence
    if reader_path.resolve().exists():
        raise ValueError("Stage 2 reader credential path exists; refusing overwrite")
    if before["next_user_id"] != TEST_READER_ID or before["reader_user_id"] is not None:
        raise ValueError("Stage 2 database is not in the exact unused-reader state")
    if before["counts"] != FIXED_BASELINE | {
        "iam_login_identifier": FIXED_BASELINE["iam_login_identifier"],
        "iam_user_role_fact": 3,
        "iam_password_credential": FIXED_BASELINE["iam_password_credential"],
        "iam_role_permission_fact": 19,
        "iam_permission": 16,
        "iam_role": 4,
        "recommendation_task": 58,
        "user_behavior_event": 55,
    }:
        raise ValueError("Stage 2 baseline table counts do not match the approved snapshot")
    readiness = _HTTPClient()
    status, ready_payload = readiness.request("GET", "/api/v1/health/ready")
    _require_status(status, 200, "readiness")
    if not isinstance(ready_payload, dict) or str(ready_payload.get("status", "")).upper() not in {"READY", "UP"}:
        raise ValueError("Stage 2 identity API readiness is not confirmed")
    admin_values = read_env(admin_path.resolve(strict=True))
    admin_identifier = admin_values.get("RECPRO_ADMIN_LOGIN_IDENTIFIER", "")
    admin_password = admin_values.get("RECPRO_ADMIN_LOGIN_PASSWORD", "")
    if not admin_identifier or not admin_password:
        raise ValueError("protected administrator login material is incomplete")
    reader_password = secrets.token_urlsafe(24)
    _write_reader_credential(reader_path, password=reader_password)
    client = _HTTPClient()
    statuses: dict[str, int] = {}
    status, payload = client.request(
        "POST", "/api/v1/auth/login",
        payload={
            "identifier_type": "READER_NUMBER",
            "identifier": admin_identifier,
            "password": admin_password,
            "device_type": "BROWSER",
        },
    )
    statuses["admin_login"] = status
    _require_status(status, 200, "admin_login")
    if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
        raise RuntimeError("admin login response omitted access token")
    admin_access = str(payload["access_token"])
    status, payload = client.request(
        "POST", "/api/v1/admin/users",
        payload={
            "display_name": TEST_READER_DISPLAY_NAME,
            "identifier_type": "READER_NUMBER",
            "identifier": TEST_READER_IDENTIFIER,
        },
        headers={
            "Authorization": f"Bearer {admin_access}",
            "Idempotency-Key": f"stage2-reader-provision-{run_id}",
        },
    )
    statuses["reader_provision"] = status
    _require_status(status, 201, "reader_provision")
    if not isinstance(payload, dict) or not isinstance(payload.get("one_time_code"), str):
        raise RuntimeError("reader provisioning response omitted one-time code")
    if not isinstance(payload.get("user"), dict) or payload["user"].get("user_id") != TEST_READER_ID:
        raise RuntimeError("reader provisioning response did not reconcile to user 10001")
    activation_code = str(payload["one_time_code"])
    status, payload = client.request(
        "POST", "/api/v1/auth/activate",
        payload={
            "identifier_type": "READER_NUMBER",
            "identifier": TEST_READER_IDENTIFIER,
            "activation_code": activation_code,
            "new_password": reader_password,
        },
    )
    statuses["reader_activation"] = status
    _require_status(status, 200, "reader_activation")
    if not isinstance(payload, dict) or payload.get("user_id") != TEST_READER_ID:
        raise RuntimeError("reader activation response did not reconcile to user 10001")
    status, payload = client.request(
        "POST", "/api/v1/auth/login",
        payload={
            "identifier_type": "READER_NUMBER",
            "identifier": TEST_READER_IDENTIFIER,
            "password": reader_password,
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
    auth_header = {"Authorization": f"Bearer {reader_access}"}
    for scope in (
        "DECLARED_PROFILE", "BEHAVIOR_LEARNING",
        "PERSONALIZED_RECOMMENDATION", "RESEARCH_ANALYTICS",
    ):
        status, _ = client.request(
            "POST", "/api/v1/me/personalization-consents",
            payload={
                "scope": scope, "action": "GRANT",
                "policy_version": "libramas-privacy-v1",
                "source": "LOGIN_ONBOARDING",
            },
            headers=auth_header,
        )
        statuses[f"consent_grant_{scope}"] = status
        _require_status(status, 200, f"consent_grant_{scope}")
    status, _ = client.request(
        "POST", "/api/v1/me/personalization-consents",
        payload={
            "scope": "BEHAVIOR_LEARNING", "action": "WITHDRAW",
            "policy_version": "libramas-privacy-v1",
            "source": "SETTINGS",
        },
        headers=auth_header,
    )
    statuses["consent_withdraw_behavior_learning"] = status
    _require_status(status, 200, "consent_withdraw_behavior_learning")
    status, _ = client.request(
        "PUT", "/api/v1/me/declared-profile", payload=TEST_READER_PROFILE,
        headers=auth_header,
    )
    statuses["declared_profile_update"] = status
    _require_status(status, 200, "declared_profile_update")
    cookies = client.cookies()
    csrf = cookies.get("recpro_csrf")
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
    after = await _read_only_state(env)
    expected_counts = dict(before["counts"])
    for table, delta in _EXPECTED_DELTAS.items():
        expected_counts[table] = expected_counts.get(table, 0) + delta
    if after["counts"] != expected_counts:
        raise RuntimeError("Stage 2 postflight counts do not match the fixed append budget")
    if not after["complete"]:
        raise RuntimeError("Stage 2 identity closure did not reconcile to its expected state")
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
    except (OSError, ValueError, RuntimeError, HTTPError, URLError) as exc:
        print(json.dumps({
            "status": "FAIL",
            "error": type(exc).__name__,
            "message": str(exc),
            # An apply failure may occur after an HTTP transaction has
            # committed one or more append-only facts.  Never claim zero
            # writes without a postflight reconciliation; the caller must
            # inspect the database and create a forward-only successor plan.
            "database_writes": "UNKNOWN_AFTER_PARTIAL_FAILURE" if args.apply else 0,
            "partial_failure_requires_new_plan": bool(args.apply),
            "deepseek_requests": 0,
            "file_deletions": 0,
            "database_physical_deletions": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
