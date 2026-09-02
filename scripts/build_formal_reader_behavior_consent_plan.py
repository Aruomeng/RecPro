#!/usr/bin/env python3
"""Build a read-only ChangePlan for one explicit behavior-learning grant.

The formal reader feedback path is intentionally fail-closed until the reader
has granted ``BEHAVIOR_LEARNING``.  This builder freezes the exact current
identity state and the single consent action needed to unblock the already
prepared synthetic reader ``10001``.  It performs only SELECT queries and
never calls the identity API, writes MySQL, invokes DeepSeek, or reads a
database/graph write credential.

The resulting plan is a review artifact, not consent itself.  A later
executor requires the exact plan id/hash and performs one login, one consent
POST, and one logout.  If a consent response is ambiguous, the executor
reconciles by read-only inspection and never retries the POST.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5
from urllib.parse import urlsplit

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
READER_CREDENTIAL_FILE = PROJECT_ROOT / ".env.stage2-reader-login.local"

FORMAL_READER_ID = 10_001
CONSENT_SCOPE = "BEHAVIOR_LEARNING"
CONSENT_ACTION = "GRANT"
CONSENT_POLICY_VERSION = "privacy-v1"
CONSENT_SOURCE = "SETTINGS"
DEFAULT_API_BASE_URL = "http://127.0.0.1:18000"

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

INPUT_PATHS = (
    "backend/app/api/auth.py",
    "backend/app/api/identity.py",
    "backend/app/composition.py",
    "backend/app/identity/adapters/mysql.py",
    "backend/app/identity/application.py",
    "backend/app/identity/security.py",
    "contracts/safety/change-plan.schema.json",
    "frontend/src/api/identityClient.ts",
    "scripts/build_formal_reader_behavior_consent_plan.py",
    "scripts/execute_formal_reader_behavior_consent_plan.py",
    "scripts/validate_runtime_env.py",
)

APPEND_TABLES = (
    "iam_auth_session",
    "iam_refresh_token",
    "iam_security_event",
    "user_personalization_consent_fact",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if GIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("Git HEAD is not a full commit SHA")
    return commit


def require_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise ValueError("working tree must be clean before freezing the consent plan")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run_id must use 3-64 safe characters")
    return value


def parse_created_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created_at must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def database_identity(values: Mapping[str, str]) -> str:
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    database = values.get("RECPRO_MYSQL_DATABASE", "").strip()
    if not port or not database:
        raise ValueError("runtime MySQL host port and database are required")
    try:
        parsed_port = int(port)
    except ValueError as exc:
        raise ValueError("runtime MySQL port must be numeric") from exc
    if not 1 <= parsed_port <= 65535:
        raise ValueError("runtime MySQL port is outside the valid range")
    # The approved identity plan is intentionally local-only.  The adapter
    # connects to loopback even when a host-mode env file contains a hostname.
    return f"mysql://127.0.0.1:{parsed_port}/{database}"


def _safe_table_names(names: tuple[str, ...]) -> tuple[str, ...]:
    if any(TABLE_PATTERN.fullmatch(name) is None for name in names):
        raise ValueError("MySQL returned an unsafe table identifier")
    return names


async def connect_runtime(values: Mapping[str, str]) -> Any:
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    required = (port, values.get("RECPRO_MYSQL_DATABASE"), values.get("RECPRO_MYSQL_USER"), values.get("RECPRO_MYSQL_PASSWORD"))
    if any(not value for value in required):
        raise ValueError("runtime MySQL settings are incomplete")
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(port),
        user=str(values["RECPRO_MYSQL_USER"]),
        password=str(values["RECPRO_MYSQL_PASSWORD"]),
        db=str(values["RECPRO_MYSQL_DATABASE"]),
        connect_timeout=10,
        read_timeout=60,
        charset="utf8mb4",
        autocommit=True,
    )


async def read_full_counts(connection: Any) -> tuple[tuple[str, ...], dict[str, int]]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() ORDER BY table_name"
        )
        names = _safe_table_names(tuple(str(row[0]) for row in await cursor.fetchall()))
        counts: dict[str, int] = {}
        for name in names:
            await cursor.execute(f"SELECT COUNT(*) FROM `{name}`")
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"count query returned no row for {name}")
            counts[name] = int(row[0])
    return names, counts


async def read_identity_state(
    connection: Any,
    *,
    user_id: int = FORMAL_READER_ID,
) -> dict[str, Any]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT user_id, status, auth_version, role_version, "
            "must_change_password, account_kind FROM iam_user_account WHERE user_id=%s",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"formal reader account {user_id} does not exist")
        account = {
            "user_id": int(row[0]),
            "status": str(row[1]),
            "auth_version": int(row[2]),
            "role_version": int(row[3]),
            "must_change_password": bool(row[4]),
            "account_kind": str(row[5]),
        }
        await cursor.execute(
            "SELECT r.role_code FROM iam_effective_user_role_v f "
            "JOIN iam_role r ON r.role_id=f.role_id WHERE f.user_id=%s ORDER BY r.role_code",
            (user_id,),
        )
        roles = [str(item[0]) for item in await cursor.fetchall()]
        await cursor.execute(
            "SELECT scope, action FROM user_effective_personalization_consent_v "
            "WHERE user_id=%s ORDER BY scope",
            (user_id,),
        )
        consents = {str(scope): str(action) == CONSENT_ACTION for scope, action in await cursor.fetchall()}
    return {"account": account, "roles": roles, "consents": consents}


def read_protected_reader_file(path: Path = READER_CREDENTIAL_FILE) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    if resolved != READER_CREDENTIAL_FILE.resolve():
        raise ValueError("reader credential path is outside the fixed protected file")
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode != 0o600:
        raise ValueError("protected reader credential file must have mode 0600")
    values = read_env(resolved)
    try:
        user_id = int(values["RECPRO_STAGE2_READER_USER_ID"])
    except (KeyError, ValueError) as exc:
        raise ValueError("protected reader credential file has an invalid user id") from exc
    if user_id != FORMAL_READER_ID:
        raise ValueError("protected credential file does not identify formal reader 10001")
    if not values.get("RECPRO_STAGE2_READER_IDENTIFIER") or not values.get("RECPRO_STAGE2_READER_PASSWORD"):
        raise ValueError("protected reader credential file is incomplete")
    if not 10 <= len(values["RECPRO_STAGE2_READER_PASSWORD"]) <= 128:
        raise ValueError("protected reader password is outside the API length boundary")
    # Return only presence/shape facts.  The caller must not put these values
    # in plans, logs, or evidence.
    return {
        "user_id": str(user_id),
        "identifier_present": "true",
        "password_present": "true",
    }


def _target(
    identifier: str,
    operation: str,
    *,
    before: int,
    after: int,
    kind: str = "MYSQL",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "identifier": identifier,
        "operation": operation,
        "expected_before_count": int(before),
        "expected_after_min_count": int(after),
    }


def _baseline_payload(
    *,
    counts: Mapping[str, int],
    identity: Mapping[str, Any],
    database_id: str,
    api_base_url: str,
) -> dict[str, Any]:
    return {
        "database_identity": database_id,
        "api_base_url": api_base_url,
        "counts": {str(key): int(value) for key, value in sorted(counts.items())},
        "identity": identity,
    }


def build_plan(
    *,
    run_id: str,
    created_at: str,
    values: Mapping[str, str],
    counts: Mapping[str, int],
    identity: Mapping[str, Any],
    api_base_url: str = DEFAULT_API_BASE_URL,
    commit: str | None = None,
) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    created_at = parse_created_at(created_at)
    parsed_api = urlsplit(api_base_url)
    if (
        parsed_api.scheme != "http"
        or parsed_api.hostname != "127.0.0.1"
        or parsed_api.path not in ("", "/")
        or parsed_api.query
        or parsed_api.fragment
        or parsed_api.port is None
        or not 1 <= parsed_api.port <= 65535
    ):
        raise ValueError("API base URL must be a loopback origin without a path")
    if identity.get("account", {}).get("user_id") != FORMAL_READER_ID:
        raise ValueError("identity snapshot is not for formal reader 10001")
    account = identity.get("account", {})
    if account.get("status") != "ACTIVE" or account.get("account_kind") != "HUMAN":
        raise ValueError("formal reader account must be ACTIVE and HUMAN")
    roles = set(identity.get("roles", ()))
    if "user" not in roles or "service_worker" in roles:
        raise ValueError("formal reader must have interactive user role and no service_worker role")
    if bool(identity.get("consents", {}).get(CONSENT_SCOPE, False)):
        raise ValueError("formal reader already has BEHAVIOR_LEARNING consent; refuse duplicate grant")
    for table in APPEND_TABLES:
        if table not in counts:
            raise ValueError(f"live snapshot is missing {table}")

    reviewed_commit = commit or current_git_commit()
    if GIT_PATTERN.fullmatch(reviewed_commit) is None:
        raise ValueError("reviewed Git commit is invalid")
    database_id = database_identity(values)
    baseline = _baseline_payload(
        counts=counts,
        identity=identity,
        database_id=database_id,
        api_base_url=api_base_url,
    )
    consent_hash = hashlib.sha256(
        f"{CONSENT_POLICY_VERSION}:{CONSENT_SCOPE}:{CONSENT_ACTION}".encode("utf-8")
    ).hexdigest()
    fingerprint = sha256_bytes(
        f"formal-reader-behavior-consent:{database_id}:{PROJECT_ROOT}:{reviewed_commit}:{run_id}".encode()
    )
    targets = [
        _target(
            ".env.stage2-reader-login.local",
            "READ",
            before=1,
            after=1,
            kind="FILE",
        ),
        _target(
            f"recpro.iam_user_account:user_id={FORMAL_READER_ID}:security-state",
            "UPDATE_STATUS",
            before=1,
            after=1,
        ),
        _target(
            f"recpro.user_effective_personalization_consent_v:user_id={FORMAL_READER_ID}",
            "READ",
            before=len(identity.get("consents", {})),
            after=len(identity.get("consents", {})),
        ),
        _target(
            f"recpro.iam_auth_session:user_id={FORMAL_READER_ID}:new-login",
            "APPEND",
            before=int(counts["iam_auth_session"]),
            after=int(counts["iam_auth_session"]) + 1,
        ),
        _target(
            f"recpro.iam_refresh_token:user_id={FORMAL_READER_ID}:new-login",
            "APPEND",
            before=int(counts["iam_refresh_token"]),
            after=int(counts["iam_refresh_token"]) + 1,
        ),
        _target(
            f"recpro.iam_security_event:formal-reader-consent:{run_id}",
            "APPEND",
            before=int(counts["iam_security_event"]),
            after=int(counts["iam_security_event"]) + 2,
        ),
        _target(
            f"recpro.user_personalization_consent_fact:user_id={FORMAL_READER_ID}:scope={CONSENT_SCOPE}:grant",
            "APPEND",
            before=int(counts["user_personalization_consent_fact"]),
            after=int(counts["user_personalization_consent_fact"]) + 1,
        ),
        _target(
            f"artifacts/verification/iam/formal-reader-behavior-consent/{run_id}/acceptance.json",
            "CREATE",
            before=0,
            after=1,
            kind="FILE",
        ),
    ]
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"recpro:formal-reader-behavior-consent:{reviewed_commit}:{run_id}:{FORMAL_READER_ID}")),
        "created_at": created_at,
        "git_commit": reviewed_commit,
        "classification": "S2_CONTROLLED_UPDATE",
        "mode": "DRY_RUN",
        "intent": (
            "Grant BEHAVIOR_LEARNING only for the existing synthetic formal reader 10001 "
            "after explicit review, so one previously prepared feedback verification can "
            "use the normal authenticated behavior boundary. The approved executor performs "
            "one login, one consent grant, and one logout; it does not create an account, "
            "change profile data, submit feedback, consume Outbox, or call any model."
        ),
        "environment": {
            "environment_id": "recpro-local-formal-reader-behavior-consent",
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": f"sha256:{fingerprint}",
            "database_identity": database_id,
            "index_namespace": None,
        },
        "targets": targets,
        "input_hashes": {
            path: file_sha256(PROJECT_ROOT / path) for path in sorted(INPUT_PATHS)
        },
        "idempotency_key": f"formal-reader-behavior-consent-{run_id}",
        "request_run_id": run_id,
        "max_changes": 5,
        "preconditions": [
            "The user separately approves this exact plan_id and plan_hash before any database connection that can write or any identity POST.",
            "FORMAL_READER_BASELINE=" + json.dumps(baseline, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "CONSENT_ACTION=" + json.dumps({
                "scope": CONSENT_SCOPE,
                "action": CONSENT_ACTION,
                "policy_version": CONSENT_POLICY_VERSION,
                "source": CONSENT_SOURCE,
                "evidence_hash": consent_hash,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "The protected reader credential file exists with mode 0600 and identifies only synthetic user 10001; credential values are never planned, logged, or persisted in evidence.",
            "The account is ACTIVE/HUMAN, has the interactive user role, and the latest effective BEHAVIOR_LEARNING consent is false at plan and apply time.",
            f"Only one login, one GET /auth/me, one consent POST, and one logout are allowed against exactly {api_base_url}; the consent POST is never retried after an ambiguous response.",
            "The consent endpoint response must prove BEHAVIOR_LEARNING=true; if the response is ambiguous, the executor performs read-only reconciliation and either continues to logout or stops without another POST.",
            "The only append deltas are iam_auth_session +1, iam_refresh_token +1, iam_security_event +2, and user_personalization_consent_fact +1; account/session/token status updates are allowlisted and row counts remain unchanged.",
            "Recommendation, impression, feedback, behavior, profile, Outbox, Agent Workspace, Neo4j, Chroma, DeepSeek, container, volume, migration, deletion, and overwrite operations are outside this plan and must remain at zero.",
            "A partial failure retains any already-appended facts for inspection and requires a new forward-only plan; no compensating DELETE, rollback write, or retry of an ambiguous consent POST is permitted.",
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
    Draft202012Validator(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    ).validate(plan)
    return plan


async def build_from_live(args: argparse.Namespace) -> dict[str, Any]:
    validate_run_id(args.run_id)
    values = read_env((PROJECT_ROOT / args.env_file).resolve(strict=True))
    read_protected_reader_file()
    require_clean_worktree()
    connection = await connect_runtime(values)
    try:
        names_before, counts = await read_full_counts(connection)
        identity = await read_identity_state(connection)
        names_after, counts_after = await read_full_counts(connection)
    finally:
        connection.close()
    if names_before != names_after or counts != counts_after:
        raise RuntimeError("read-only plan build observed a changing MySQL snapshot")
    plan = build_plan(
        run_id=args.run_id,
        created_at=args.created_at,
        values=values,
        counts=counts,
        identity=identity,
        api_base_url=args.base_url,
    )
    output = (PROJECT_ROOT / args.output).resolve()
    if not output.is_relative_to(PROJECT_ROOT):
        raise ValueError("output must remain inside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return {
        "status": "PLAN_PENDING_APPROVAL",
        "mode": "READ_ONLY_PLAN_BUILD",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "git_commit": plan["git_commit"],
        "path": output.relative_to(PROJECT_ROOT).as_posix(),
        "target_user_id": FORMAL_READER_ID,
        "consent_scope": CONSENT_SCOPE,
        "expected_database_append_rows": {
            "iam_auth_session": 1,
            "iam_refresh_token": 1,
            "iam_security_event": 2,
            "user_personalization_consent_fact": 1,
        },
        "database_connections": 1,
        "database_writes": 0,
        "identity_posts": 0,
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--created-at", default=datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    parser.add_argument("--base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--env-file", default=".env.host")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = asyncio.run(build_from_live(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] formal reader consent plan was not generated: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
