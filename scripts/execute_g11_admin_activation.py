#!/usr/bin/env python3
"""Plan-bound activation of the initial administrator with a protected password."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from typing import Sequence
from uuid import UUID, uuid5

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.identity.security import (
    Argon2idPasswordService, HMACSecretTokenService,
)
from scripts.execute_g11_bootstrap_admin import (
    BOOTSTRAP_USER_ID, DEFAULT_ENV_FILE, DEFAULT_MATERIAL_FILE,
    BootstrapMaterial, material_from_files as bootstrap_material_from_files,
)
from scripts.execute_g11_identity_migration import canonical, file_sha256
from scripts.validate_runtime_env import read_env


SCHEMA = PROJECT_ROOT / "contracts/safety/change-plan.schema.json"
DEFAULT_PLAN = PROJECT_ROOT / "plans/g11-admin-activation.json"
DEFAULT_CREDENTIAL_FILE = PROJECT_ROOT / ".env.admin-login.local"
MAXIMUM_CHANGES = 4
_NAMESPACE = UUID("d98667ad-d008-594b-9c75-ae8f805cb3e2")
_HASH = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_INPUT_PATHS = frozenset({
    "backend/app/identity/adapters/mysql.py",
    "backend/app/identity/security.py",
    "infra/mysql/migrations/009_g11_identity_access.sql",
    "scripts/build_g11_admin_activation_plan.py",
    "scripts/execute_g11_admin_activation.py",
})


@dataclass(frozen=True, slots=True)
class ActivationMaterial:
    bootstrap: BootstrapMaterial
    password_hash: str
    password_material_digest: bytes
    event_uuid: UUID


def initialize_credentials(path: Path, bootstrap_file: Path) -> dict[str, object]:
    """Generate a strong password and frozen Argon2id hash without printing either."""
    destination = path.resolve()
    if destination.exists():
        raise ValueError("administrator credential file exists; refusing to overwrite it")
    local = read_env(bootstrap_file.resolve(strict=True))
    identifier = local.get("RECPRO_BOOTSTRAP_ADMIN_IDENTIFIER", "")
    if not identifier:
        raise ValueError("bootstrap identifier is missing")
    password = secrets.token_urlsafe(24)
    password_hash = Argon2idPasswordService().hash(password)
    payload = (
        f"RECPRO_ADMIN_LOGIN_IDENTIFIER={identifier}\n"
        f"RECPRO_ADMIN_LOGIN_PASSWORD={password}\n"
        f"RECPRO_ADMIN_PASSWORD_PHC={password_hash}\n"
    ).encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    os.chmod(destination, 0o600)
    return {
        "status": "PASS", "mode": "LOCAL_LOGIN_CREDENTIAL_INITIALIZED",
        "path": str(destination), "permissions": "0600",
        "password_length": len(password), "plaintext_values_printed": 0,
        "database_connections": 0, "database_writes": 0,
    }


def activation_material_from_files(
    env_file: Path, bootstrap_file: Path, credential_file: Path,
) -> tuple[dict[str, str], ActivationMaterial]:
    values, bootstrap = bootstrap_material_from_files(env_file, bootstrap_file)
    local = read_env(credential_file.resolve(strict=True))
    bootstrap_values = read_env(bootstrap_file.resolve(strict=True))
    identifier = local.get("RECPRO_ADMIN_LOGIN_IDENTIFIER", "")
    password = local.get("RECPRO_ADMIN_LOGIN_PASSWORD", "")
    password_hash = local.get("RECPRO_ADMIN_PASSWORD_PHC", "")
    if identifier != bootstrap_values.get("RECPRO_BOOTSTRAP_ADMIN_IDENTIFIER"):
        raise ValueError("login identifier does not match protected bootstrap material")
    passwords = Argon2idPasswordService()
    if not passwords.verify(password_hash, password):
        raise ValueError("protected password and Argon2id hash do not match")
    tokens = HMACSecretTokenService(values["RECPRO_AUTH_TOKEN_PEPPER"].encode())
    password_material_digest = tokens.digest(password)
    event_uuid = uuid5(
        _NAMESPACE,
        f"activate:{BOOTSTRAP_USER_ID}:{bootstrap.token_uuid}:{password_material_digest.hex()}",
    )
    return values, ActivationMaterial(
        bootstrap=bootstrap, password_hash=password_hash,
        password_material_digest=password_material_digest,
        event_uuid=event_uuid,
    )


def expected_targets(material: ActivationMaterial) -> dict[str, str]:
    credential_digest = hashlib.sha256(material.password_hash.encode()).hexdigest()
    return {
        f"recpro.iam_password_credential:user_id={BOOTSTRAP_USER_ID}:phc-sha256={credential_digest}": "APPEND",
        f"recpro.iam_action_token:token={material.bootstrap.token_uuid}:state=CONSUMED": "UPDATE_STATUS",
        f"recpro.iam_user_account:user_id={BOOTSTRAP_USER_ID}:state=ACTIVE:auth_version=2": "UPDATE_STATUS",
        f"recpro.iam_security_event:event={material.event_uuid}:type=ACCOUNT_ACTIVATED": "APPEND",
    }


def expected_fingerprint(
    database_identity: str, reviewed_commit: str, material: ActivationMaterial,
) -> str:
    payload = (
        f"recpro_local_research_g11_admin_activation:{database_identity}:{PROJECT_ROOT}:"
        f"{reviewed_commit}:{material.bootstrap.account_uuid}:{material.bootstrap.token_uuid}:"
        f"{material.password_material_digest.hex()}:"
        f"{hashlib.sha256(material.password_hash.encode()).hexdigest()}"
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def reviewed_commit_is_ancestor(commit: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{40}", commit) is not None and subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=PROJECT_ROOT, capture_output=True,
    ).returncode == 0


def dry_run_report() -> dict[str, object]:
    return {
        "status": "PASS", "mode": "NO_WRITE_ADMIN_ACTIVATION_DRY_RUN",
        "user_id": BOOTSTRAP_USER_ID, "maximum_changes": MAXIMUM_CHANGES,
        "changes": [
            "INSERT_PASSWORD_CREDENTIAL", "CONSUME_ACTION_TOKEN",
            "ACTIVATE_ACCOUNT", "APPEND_SECURITY_EVENT",
        ],
        "database_connections": 0, "database_writes": 0,
        "login_sessions": 0, "deepseek_requests": 0,
        "file_deletions": 0, "database_physical_deletions": 0,
    }


def validate_plan(
    path: Path, *, plan_id: str, approved_hash: str,
    material: ActivationMaterial, database_identity: str,
) -> dict[str, object]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    ).validate(plan)
    if (
        plan.get("plan_id") != plan_id or plan.get("plan_hash") != approved_hash
        or _HASH.fullmatch(approved_hash) is None
    ):
        raise ValueError("approved activation plan identity does not match")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("activation plan canonical hash does not match")
    commit = str(plan.get("git_commit", ""))
    if not reviewed_commit_is_ancestor(commit):
        raise ValueError("reviewed activation commit is not an ancestor")
    if (
        plan.get("classification") != "S2_CONTROLLED_UPDATE"
        or plan.get("mode") != "APPLY" or plan.get("max_changes") != MAXIMUM_CHANGES
    ):
        raise ValueError("activation operation budget is invalid")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != REQUIRED_INPUT_PATHS:
        raise ValueError("activation input hash set is invalid")
    for relative in REQUIRED_INPUT_PATHS:
        if inputs.get(relative) != file_sha256(PROJECT_ROOT / relative):
            raise ValueError(f"activation input hash mismatch: {relative}")
    expected = expected_targets(material)
    targets = plan.get("targets")
    if not isinstance(targets, list) or len(targets) != MAXIMUM_CHANGES:
        raise ValueError("activation target count is invalid")
    actual = {
        str(item.get("identifier")): str(item.get("operation"))
        for item in targets if isinstance(item, dict)
    }
    if actual != expected or any(
        item.get("expected_before_count") != 0
        or item.get("expected_after_min_count") != 1
        for item in targets if isinstance(item, dict)
    ):
        raise ValueError("activation target set is invalid")
    environment = plan.get("environment")
    if (
        not isinstance(environment, dict)
        or environment.get("database_identity") != database_identity
        or environment.get("host_fingerprint")
        != expected_fingerprint(database_identity, commit, material)
    ):
        raise ValueError("activation environment does not match approved plan")
    return plan


async def _scalar(connection: object, statement: str, parameters: tuple[object, ...] = ()) -> int:
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(statement, parameters)
        row = await cursor.fetchone()
    return int(row[0])


async def _fresh_state(connection: object, material: ActivationMaterial) -> bool:
    pending = await _scalar(
        connection,
        "SELECT COUNT(*) FROM iam_user_account WHERE user_id=%s AND account_uuid=%s "
        "AND status='PENDING_ACTIVATION' AND auth_version=1 AND role_version=3 "
        "AND must_change_password=TRUE",
        (BOOTSTRAP_USER_ID, str(material.bootstrap.account_uuid)),
    )
    identifier = await _scalar(
        connection,
        "SELECT COUNT(*) FROM iam_login_identifier WHERE user_id=%s "
        "AND identifier_hash=%s AND status='ACTIVE'",
        (BOOTSTRAP_USER_ID, material.bootstrap.identifier_hash),
    )
    token = await _scalar(
        connection,
        "SELECT COUNT(*) FROM iam_action_token WHERE token_uuid=%s AND user_id=%s "
        "AND token_hash=%s AND purpose='ACTIVATE_ACCOUNT' AND consumed_at IS NULL "
        "AND revoked_at IS NULL AND expires_at>UTC_TIMESTAMP(3)",
        (
            str(material.bootstrap.token_uuid), BOOTSTRAP_USER_ID,
            material.bootstrap.token_hash,
        ),
    )
    credential = await _scalar(
        connection, "SELECT COUNT(*) FROM iam_password_credential WHERE user_id=%s",
        (BOOTSTRAP_USER_ID,),
    )
    event = await _scalar(
        connection, "SELECT COUNT(*) FROM iam_security_event WHERE event_uuid=%s",
        (str(material.event_uuid),),
    )
    return (pending, identifier, token, credential, event) == (1, 1, 1, 0, 0)


async def _completed_state(connection: object, material: ActivationMaterial) -> bool:
    account = await _scalar(
        connection,
        "SELECT COUNT(*) FROM iam_user_account WHERE user_id=%s AND account_uuid=%s "
        "AND status='ACTIVE' AND auth_version=2 AND role_version=3 "
        "AND must_change_password=FALSE",
        (BOOTSTRAP_USER_ID, str(material.bootstrap.account_uuid)),
    )
    credential = await _scalar(
        connection,
        "SELECT COUNT(*) FROM iam_password_credential WHERE user_id=%s "
        "AND password_hash=%s AND algorithm='ARGON2ID' "
        "AND parameters_version='argon2id-v1' AND password_version=1",
        (BOOTSTRAP_USER_ID, material.password_hash),
    )
    token = await _scalar(
        connection,
        "SELECT COUNT(*) FROM iam_action_token WHERE token_uuid=%s AND token_hash=%s "
        "AND consumed_at IS NOT NULL AND revoked_at IS NULL",
        (str(material.bootstrap.token_uuid), material.bootstrap.token_hash),
    )
    event = await _scalar(
        connection,
        "SELECT COUNT(*) FROM iam_security_event WHERE event_uuid=%s "
        "AND event_type='ACCOUNT_ACTIVATED' AND outcome='SUCCESS' AND user_id=%s "
        "AND actor_user_id=%s AND reason_code='ONE_TIME_CODE_CONSUMED'",
        (str(material.event_uuid), BOOTSTRAP_USER_ID, BOOTSTRAP_USER_ID),
    )
    return (account, credential, token, event) == (1, 1, 1, 1)


async def apply_plan(args: argparse.Namespace) -> dict[str, object]:
    values, material = activation_material_from_files(
        args.env_file, args.bootstrap_file, args.credential_file,
    )
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    database = values.get("RECPRO_MYSQL_DATABASE", "")
    user = values.get("RECPRO_IDENTITY_MYSQL_USER", "")
    password = values.get("RECPRO_IDENTITY_MYSQL_PASSWORD", "")
    if not port or database != "recpro" or user != "recpro_identity" or len(password) < 20:
        raise ValueError("approved recpro_identity runtime connection is required")
    database_identity = f"mysql://127.0.0.1:{port}/{database}"
    validate_plan(
        args.plan.resolve(strict=True), plan_id=args.plan_id,
        approved_hash=args.approved_plan_hash, material=material,
        database_identity=database_identity,
    )
    connection = await asyncmy.connect(
        host="127.0.0.1", port=int(port), user=user, password=password,
        db=database, autocommit=False,
    )
    try:
        if await _completed_state(connection, material):
            await connection.rollback()
            return {
                "status": "PASS", "mode": "IDEMPOTENT_REPLAY",
                "changes": 0, "user_id": BOOTSTRAP_USER_ID,
                "account_status": "ACTIVE", "plaintext_values_printed": 0,
                "credential_path": str(args.credential_file.resolve()),
                "deletions": 0,
            }
        if not await _fresh_state(connection, material):
            raise ValueError("administrator is not in the exact approved pending state")
        now = datetime.now(UTC).replace(tzinfo=None)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT status,auth_version FROM iam_user_account WHERE user_id=%s FOR UPDATE",
                (BOOTSTRAP_USER_ID,),
            )
            account = await cursor.fetchone()
            await cursor.execute(
                "SELECT consumed_at,revoked_at,expires_at FROM iam_action_token "
                "WHERE token_uuid=%s AND token_hash=%s FOR UPDATE",
                (str(material.bootstrap.token_uuid), material.bootstrap.token_hash),
            )
            token = await cursor.fetchone()
            if (
                account != ("PENDING_ACTIVATION", 1) or token is None
                or token[0] is not None or token[1] is not None or token[2] <= now
            ):
                raise ValueError("locked activation state changed before apply")
            await cursor.execute(
                "INSERT INTO iam_password_credential "
                "(user_id,password_hash,algorithm,parameters_version,password_version,"
                "changed_at,expires_at,updated_at) "
                "VALUES (%s,%s,'ARGON2ID','argon2id-v1',1,%s,NULL,%s)",
                (BOOTSTRAP_USER_ID, material.password_hash, now, now),
            )
            await cursor.execute(
                "UPDATE iam_action_token SET consumed_at=%s WHERE token_uuid=%s "
                "AND consumed_at IS NULL AND revoked_at IS NULL",
                (now, str(material.bootstrap.token_uuid)),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("activation token consumption did not affect one row")
            await cursor.execute(
                "UPDATE iam_user_account SET status='ACTIVE',must_change_password=FALSE,"
                "auth_version=auth_version+1,updated_at=%s WHERE user_id=%s "
                "AND status='PENDING_ACTIVATION' AND auth_version=1",
                (now, BOOTSTRAP_USER_ID),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("account activation did not affect one row")
            metadata = json.dumps(
                {"activation_version": "g11-admin-activation-v1"},
                sort_keys=True, separators=(",", ":"),
            )
            await cursor.execute(
                "INSERT INTO iam_security_event "
                "(event_uuid,event_type,outcome,user_id,actor_user_id,identifier_hash,"
                "reason_code,metadata_json,occurred_at,created_at) "
                "VALUES (%s,'ACCOUNT_ACTIVATED','SUCCESS',%s,%s,%s,"
                "'ONE_TIME_CODE_CONSUMED',%s,%s,%s)",
                (
                    str(material.event_uuid), BOOTSTRAP_USER_ID, BOOTSTRAP_USER_ID,
                    material.bootstrap.identifier_hash, metadata, now, now,
                ),
            )
        if not await _completed_state(connection, material):
            raise RuntimeError("activation postflight reconciliation failed")
        await connection.commit()
        return {
            "status": "PASS", "mode": "APPLY", "changes": MAXIMUM_CHANGES,
            "user_id": BOOTSTRAP_USER_ID, "account_status": "ACTIVE",
            "auth_version": 2, "credential_path": str(args.credential_file.resolve()),
            "plaintext_values_printed": 0, "login_sessions": 0,
            "deepseek_requests": 0, "deletions": 0,
        }
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--initialize-local-credential", action="store_true")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--approved-plan-hash", default="")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--bootstrap-file", type=Path, default=DEFAULT_MATERIAL_FILE)
    parser.add_argument("--credential-file", type=Path, default=DEFAULT_CREDENTIAL_FILE)
    args = parser.parse_args(argv)
    if args.apply and args.initialize_local_credential:
        raise ValueError("credential initialization and activation apply are separate operations")
    if args.initialize_local_credential:
        report = initialize_credentials(args.credential_file, args.bootstrap_file)
    elif args.apply:
        report = asyncio.run(apply_plan(args))
    else:
        report = dry_run_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
