#!/usr/bin/env python3
"""Freeze a bounded plan for the authenticated reader UI login smoke run.

The plan is deliberately narrower than a recommendation or consent plan. It
uses the existing synthetic reader only to prove that the browser-facing login
dialog can establish a Bearer session, render the already-granted consent and
profile state, and log out. The browser must not toggle consent, edit profile,
start a recommendation, submit feedback, or call the model.

This module performs SELECT-only inspection and writes a review artifact. It
does not call the identity API, create a session, or persist any business fact.
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
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_reader_auth_session_plan import READER_CREDENTIAL_FILE
from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts/safety/change-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
GIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

INPUT_PATHS = (
    "frontend/src/App.vue",
    "frontend/src/api/identityClient.ts",
    "frontend/src/components/LoginDialog.vue",
    "frontend/src/main.ts",
    "frontend/src/stores/auth.ts",
    "scripts/build_authenticated_ui_login_plan.py",
)
APPEND_TABLES = ("iam_auth_session", "iam_refresh_token", "iam_security_event")
NO_CHANGE_TABLES = (
    "recommendation_task",
    "user_behavior_event",
    "user_declared_profile",
    "user_personalization_consent_fact",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_commit() -> str:
    value = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if GIT_PATTERN.fullmatch(value) is None:
        raise ValueError("Git HEAD is invalid")
    return value


def require_clean_worktree() -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if status:
        raise ValueError("worktree must be clean before freezing the UI login plan")


def database_identity(values: dict[str, str]) -> str:
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    database = values.get("RECPRO_MYSQL_DATABASE", "")
    if not port or not database:
        raise ValueError("MySQL runtime identity is incomplete")
    return f"mysql://127.0.0.1:{int(port)}/{database}"


async def read_baseline(values: dict[str, str], user_id: int) -> tuple[str, dict[str, Any]]:
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    required = (port, values.get("RECPRO_MYSQL_DATABASE"), values.get("RECPRO_MYSQL_USER"), values.get("RECPRO_MYSQL_PASSWORD"))
    if any(not item for item in required):
        raise ValueError("MySQL runtime settings are incomplete")
    connection = await asyncmy.connect(
        host="127.0.0.1", port=int(str(port)), user=str(values["RECPRO_MYSQL_USER"]),
        password=str(values["RECPRO_MYSQL_PASSWORD"]), db=str(values["RECPRO_MYSQL_DATABASE"]),
        autocommit=True, connect_timeout=3,
    )
    try:
        async with connection.cursor() as cursor:
            counts: dict[str, int] = {}
            for table in (*APPEND_TABLES, *NO_CHANGE_TABLES):
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError(f"count query returned no row for {table}")
                counts[table] = int(row[0])
            await cursor.execute(
                "SELECT user_id, account_uuid, status, auth_version, role_version, "
                "must_change_password, account_kind FROM iam_user_account WHERE user_id=%s",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("approved reader account does not exist")
            account = {
                "user_id": int(row[0]), "account_uuid": str(row[1]), "status": str(row[2]),
                "auth_version": int(row[3]), "role_version": int(row[4]),
                "must_change_password": bool(row[5]), "account_kind": str(row[6]),
            }
            await cursor.execute(
                "SELECT role_code FROM iam_effective_user_role_v f "
                "JOIN iam_role r ON r.role_id=f.role_id WHERE f.user_id=%s ORDER BY role_code",
                (user_id,),
            )
            roles = [str(item[0]) for item in await cursor.fetchall()]
            await cursor.execute(
                "SELECT scope, action FROM user_effective_personalization_consent_v "
                "WHERE user_id=%s ORDER BY scope", (user_id,),
            )
            consents = {str(scope): str(action) == "GRANT" for scope, action in await cursor.fetchall()}
        return database_identity(values), {"counts": counts, "account": account, "roles": roles, "consents": consents}
    finally:
        connection.close()


def build_plan(*, run_id: str, created_at: str, identity: str, baseline: dict[str, Any]) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run_id must contain only lowercase letters, digits, and hyphens")
    require_clean_worktree()
    head = current_commit()
    counts = baseline["counts"]
    deltas = {"iam_auth_session": 1, "iam_refresh_token": 1, "iam_security_event": 2}
    targets = [
        {
            "kind": "MYSQL", "identifier": f"recpro.{table}:user_id=10001",
            "operation": "APPEND", "expected_before_count": int(counts[table]),
            "expected_after_min_count": int(counts[table]) + delta,
        }
        for table, delta in deltas.items()
    ]
    targets.extend([
        {"kind": "MYSQL", "identifier": "recpro.iam_user_account:user_id=10001:last-login", "operation": "UPDATE_STATUS", "expected_before_count": 1, "expected_after_min_count": 1},
        {"kind": "MYSQL", "identifier": "recpro.iam_auth_session:user_id=10001:logout-revoke", "operation": "UPDATE_STATUS", "expected_before_count": 1, "expected_after_min_count": 1},
        {"kind": "FILE", "identifier": f"artifacts/verification/authenticated-ui-login/{run_id}/acceptance.json", "operation": "CREATE", "expected_before_count": 0, "expected_after_min_count": 1},
    ])
    fingerprint = hashlib.sha256(f"authenticated-ui-login:{identity}:{head}:{run_id}".encode()).hexdigest()
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"recpro:authenticated-ui-login:{head}:{run_id}")),
        "created_at": datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": head,
        "classification": "S2_CONTROLLED_UPDATE",
        "mode": "APPLY",
        "intent": "Use the browser-facing LibraMAS login dialog with synthetic reader user 10001, verify the Bearer account chip, open the read-only personalization panel, confirm its four existing grants and declared profile, then log out. No consent toggle, profile edit, recommendation, feedback, behavior, workspace audit, Neo4j, Chroma, DeepSeek, or other business write is allowed.",
        "environment": {
            "environment_id": "recpro-local-authenticated-ui-login",
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": f"sha256:{fingerprint}",
            "database_identity": identity,
            "index_namespace": None,
        },
        "targets": targets,
        "input_hashes": {path: sha256(PROJECT_ROOT / path) for path in sorted(INPUT_PATHS)},
        "idempotency_key": f"authenticated-ui-login-{run_id}",
        "request_run_id": run_id,
        "max_changes": sum(deltas.values()) + 3,
        "preconditions": [
            "The user approves this exact plan_id and canonical plan_hash before the browser submits the login form.",
            "The protected .env.stage2-reader-login.local file exists with mode 0600; its identifier and password are never printed, planned, or written to evidence.",
            "UI_LOGIN_BASELINE=" + json.dumps(baseline, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "The local frontend and identity API are ready on the approved loopback URLs; the browser uses the formal Bearer flow and never sends X-Demo-User-Id.",
            "The only POST endpoints allowed are /api/v1/auth/login and /api/v1/auth/logout. GET /api/v1/auth/me and GET /api/v1/me/profile may be read; the consent panel is opened but no consent action is submitted.",
            "Expected MySQL append deltas are iam_auth_session +1, iam_refresh_token +1, iam_security_event +2. Only last-login and the created session logout revocation may update current security state.",
            "The no-change tables in UI_LOGIN_BASELINE must remain unchanged: recommendation_task, user_behavior_event, user_declared_profile, and user_personalization_consent_fact.",
            "DeepSeek requests, Neo4j writes, Chroma writes, recommendation facts, feedback facts, behavior facts, workspace audit facts, schema changes, containers, volumes, overwrites, and deletions are forbidden.",
            "If the browser or API fails after login, retain any appended facts for inspection and do not retry the login or compensate with deletion.",
        ],
        "safety_assertions": {
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "overwrite_existing": False,
            "destructive_capabilities_required": False,
            "counts_must_not_decrease": True,
        },
    }
    plan["plan_hash"] = hashlib.sha256(canonical(plan)).hexdigest()
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text()), format_checker=FormatChecker()).validate(plan)
    return plan


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    credentials = read_env(READER_CREDENTIAL_FILE.resolve(strict=True))
    if READER_CREDENTIAL_FILE.stat().st_mode & 0o077:
        raise ValueError("protected reader credential file must have mode 0600")
    user_id = credentials.get("RECPRO_STAGE2_READER_USER_ID", "")
    if user_id != "10001" or not credentials.get("RECPRO_STAGE2_READER_IDENTIFIER") or not credentials.get("RECPRO_STAGE2_READER_PASSWORD"):
        raise ValueError("protected synthetic reader material is unavailable")
    values = read_env((PROJECT_ROOT / args.env_file).resolve(strict=True))
    identity, baseline = await read_baseline(values, 10001)
    plan = build_plan(run_id=args.run_id, created_at=args.created_at, identity=identity, baseline=baseline)
    output = (PROJECT_ROOT / args.output).resolve()
    if not output.is_relative_to(PROJECT_ROOT):
        raise ValueError("plan output must stay inside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return {
        "status": "PASS", "mode": "READ_ONLY_AUTHENTICATED_UI_LOGIN_PLAN",
        "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
        "git_commit": plan["git_commit"], "path": str(output.relative_to(PROJECT_ROOT)),
        "database_writes": 0, "deepseek_requests": 0,
        "file_deletions": 0, "database_physical_deletions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--created-at", default=datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    parser.add_argument("--env-file", default=".env.host")
    parser.add_argument("--output", required=True)
    print(json.dumps(asyncio.run(main_async(parser.parse_args())), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
