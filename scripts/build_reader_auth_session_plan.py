#!/usr/bin/env python3
"""Freeze an exact, forward-only local reader-authentication verification plan.

This builder has a deliberately narrow responsibility: it performs read-only
MySQL inspection and creates a ChangePlan for one already-active synthetic
reader to complete ``login -> me -> refresh -> logout``.  It neither creates
an account nor changes consent, profile, recommendation, feedback, graph, or
model state.  Secrets are read only by the later executor and are never part
of the plan or its evidence.
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

from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = PROJECT_ROOT / "contracts/safety/change-plan.schema.json"
READER_CREDENTIAL_FILE = PROJECT_ROOT / ".env.stage2-reader-login.local"
INPUT_PATHS = (
    "backend/app/api/identity.py",
    "backend/app/composition.py",
    "backend/app/identity/adapters/mysql.py",
    "backend/app/identity/application.py",
    "backend/app/identity/security.py",
    "scripts/build_reader_auth_session_plan.py",
    "scripts/execute_reader_auth_session_plan.py",
)
COUNT_TABLES = (
    "iam_auth_session",
    "iam_refresh_token",
    "iam_security_event",
)
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    value = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("Git HEAD is not a full commit SHA")
    return value


def require_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        raise ValueError("working tree must be clean before freezing the auth plan")


async def read_baseline(env: dict[str, str], *, user_id: int) -> tuple[str, dict[str, Any]]:
    port = env.get("RECPRO_MYSQL_HOST_PORT") or env.get("RECPRO_MYSQL_PORT")
    database = env.get("RECPRO_MYSQL_DATABASE", "")
    user = env.get("RECPRO_MYSQL_USER", "")
    password = env.get("RECPRO_MYSQL_PASSWORD", "")
    if not port or not database or not user or not password:
        raise ValueError("MySQL runtime settings are incomplete")
    connection = await asyncmy.connect(
        host="127.0.0.1", port=int(port), user=user, password=password,
        db=database, autocommit=True, connect_timeout=3,
    )
    try:
        async with connection.cursor() as cursor:
            counts: dict[str, int] = {}
            for table in COUNT_TABLES:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                counts[table] = int((await cursor.fetchone())[0])
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
                "WHERE user_id=%s ORDER BY scope",
                (user_id,),
            )
            consents = {str(scope): str(action) == "GRANT" for scope, action in await cursor.fetchall()}
        return f"mysql://127.0.0.1:{port}/{database}", {
            "counts": counts, "account": account, "roles": roles, "consents": consents,
        }
    finally:
        connection.close()


def build_plan(*, run_id: str, created_at: str, database_identity: str, baseline: dict[str, Any]) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run_id must contain only lowercase letters, digits, and hyphens")
    require_clean_worktree()
    commit = current_commit()
    user_id = int(baseline["account"]["user_id"])
    fingerprint = hashlib.sha256(
        f"reader-auth-session:{database_identity}:{commit}:{run_id}:{user_id}".encode(),
    ).hexdigest()
    targets = [
        {"kind": "MYSQL", "identifier": f"recpro.iam_auth_session:user_id={user_id}", "operation": "APPEND", "expected_before_count": int(baseline["counts"]["iam_auth_session"]), "expected_after_min_count": int(baseline["counts"]["iam_auth_session"]) + 1},
        {"kind": "MYSQL", "identifier": f"recpro.iam_refresh_token:user_id={user_id}", "operation": "APPEND", "expected_before_count": int(baseline["counts"]["iam_refresh_token"]), "expected_after_min_count": int(baseline["counts"]["iam_refresh_token"]) + 2},
        {"kind": "MYSQL", "identifier": f"recpro.iam_security_event:reader-auth:{run_id}", "operation": "APPEND", "expected_before_count": int(baseline["counts"]["iam_security_event"]), "expected_after_min_count": int(baseline["counts"]["iam_security_event"]) + 2},
        {"kind": "MYSQL", "identifier": f"recpro.iam_user_account:user_id={user_id}:last-login", "operation": "UPDATE_STATUS", "expected_before_count": 1, "expected_after_min_count": 1},
        {"kind": "MYSQL", "identifier": f"recpro.iam_refresh_token:user_id={user_id}:initial-consume", "operation": "UPDATE_STATUS", "expected_before_count": 1, "expected_after_min_count": 1},
        {"kind": "MYSQL", "identifier": f"recpro.iam_auth_session:user_id={user_id}:last-seen-and-revoke", "operation": "UPDATE_STATUS", "expected_before_count": 1, "expected_after_min_count": 1},
        {"kind": "FILE", "identifier": f"artifacts/verification/reader-auth-session/{run_id}/acceptance.json", "operation": "CREATE", "expected_before_count": 0, "expected_after_min_count": 1},
    ]
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"recpro:reader-auth-session:{commit}:{run_id}")),
        "created_at": datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S2_CONTROLLED_UPDATE", "mode": "APPLY",
        "intent": "Verify one existing synthetic reader through the public local identity API: login, authenticated identity read, one refresh-token rotation, and logout. No account, consent, profile, recommendation, feedback, behavior, graph, vector, workspace audit, or model operation is allowed.",
        "environment": {"environment_id": "recpro-local-reader-auth-session", "workspace": str(PROJECT_ROOT), "host_fingerprint": f"sha256:{fingerprint}", "database_identity": database_identity, "index_namespace": None},
        "targets": targets,
        "input_hashes": {path: sha256(PROJECT_ROOT / path) for path in sorted(INPUT_PATHS)},
        "idempotency_key": f"reader-auth-session-{run_id}", "request_run_id": run_id,
        "max_changes": 9,
        "preconditions": [
            "The user approves this exact plan_id and plan_hash before the executor invokes any POST endpoint.",
            "The protected stage-2 reader credential file exists with mode 0600; its values are never logged, planned, or written to evidence.",
            "AUTH_SESSION_BASELINE=" + json.dumps(baseline, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "The local workbench identity API is ready at the approved loopback base URL.",
            "Only login, auth/me, refresh, and logout are called; refresh is exactly once and all authentication material stays in memory.",
            "MySQL append deltas are exactly session +1, refresh-token +2, security-event +2; only the allowlisted current session/token/account fields may be updated.",
            "No DeepSeek, Neo4j, Chroma, recommendation, profile, consent, behavior, feedback, workspace audit, deletion, container, or volume operation occurs.",
            "On partial failure facts are retained for inspection; no compensating deletion or overwrite is attempted.",
        ],
        "safety_assertions": {"file_deletions": 0, "database_physical_deletions": 0, "overwrite_existing": False, "destructive_capabilities_required": False, "counts_must_not_decrease": True},
    }
    plan["plan_hash"] = hashlib.sha256(canonical(plan)).hexdigest()
    Draft202012Validator(json.loads(SCHEMA.read_text()), format_checker=FormatChecker()).validate(plan)
    return plan


async def async_main(args: argparse.Namespace) -> dict[str, Any]:
    values = read_env((PROJECT_ROOT / args.env_file).resolve(strict=True))
    credentials = read_env(READER_CREDENTIAL_FILE.resolve(strict=True))
    user_text = credentials.get("RECPRO_STAGE2_READER_USER_ID", "")
    if not user_text.isdigit() or not credentials.get("RECPRO_STAGE2_READER_IDENTIFIER") or not credentials.get("RECPRO_STAGE2_READER_PASSWORD"):
        raise ValueError("protected reader credential file is incomplete")
    if READER_CREDENTIAL_FILE.stat().st_mode & 0o077:
        raise ValueError("protected reader credential file must have mode 0600")
    identity, baseline = await read_baseline(values, user_id=int(user_text))
    plan = build_plan(run_id=args.run_id, created_at=args.created_at, database_identity=identity, baseline=baseline)
    output = (PROJECT_ROOT / args.output).resolve()
    if not output.is_relative_to(PROJECT_ROOT):
        raise ValueError("plan output must stay inside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return {"status": "PASS", "mode": "READ_ONLY_PLAN_BUILD", "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "git_commit": plan["git_commit"], "path": output.relative_to(PROJECT_ROOT).as_posix(), "database_writes": 0, "deepseek_requests": 0, "file_deletions": 0, "database_physical_deletions": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--created-at", default=datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    parser.add_argument("--env-file", default=".env.host")
    parser.add_argument("--output", required=True)
    print(json.dumps(asyncio.run(async_main(parser.parse_args())), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
