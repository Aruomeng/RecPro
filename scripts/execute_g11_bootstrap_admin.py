#!/usr/bin/env python3
"""Create the first local human administrator through one plan-bound transaction.

The bootstrap is deliberately separate from the normal librarian provisioning
flow because the first actor does not exist yet.  It appends seven rows and
never deletes, replaces, or mutates an existing identity fact.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

from backend.app.identity.domain import IdentifierType
from backend.app.identity.security import HMACIdentifierService, HMACSecretTokenService
from scripts.execute_g11_identity_migration import canonical, file_sha256
from scripts.validate_runtime_env import read_env


SCHEMA = PROJECT_ROOT / "contracts/safety/change-plan.schema.json"
DEFAULT_PLAN = PROJECT_ROOT / "plans/g11-bootstrap-admin.json"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.host"
DEFAULT_MATERIAL_FILE = PROJECT_ROOT / ".env.bootstrap.local"
BOOTSTRAP_USER_ID = 10_000
DISPLAY_NAME = "LibraMAS 研究管理员"
IDENTIFIER_TYPE = IdentifierType.READER_NUMBER
ROLE_IDS = {"user": 1, "librarian": 2, "research_admin": 3}
MAXIMUM_ROWS = 7
ACTIVATION_TTL_HOURS = 24
_NAMESPACE = UUID("39518036-d24d-566c-aa3d-21c9b6732925")
_HASH = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_INPUT_PATHS = frozenset({
    "backend/app/identity/security.py",
    "infra/mysql/migrations/009_g11_identity_access.sql",
    "scripts/build_g11_bootstrap_admin_plan.py",
    "scripts/execute_g11_bootstrap_admin.py",
})


@dataclass(frozen=True, slots=True)
class BootstrapMaterial:
    identifier_hash: bytes
    token_hash: bytes
    display_suffix: str
    account_uuid: UUID
    token_uuid: UUID
    event_uuid: UUID
    role_fact_uuids: dict[str, UUID]


def build_material(
    *, identifier: str, activation_code: str,
    identifier_pepper: str, token_pepper: str,
) -> BootstrapMaterial:
    identifiers = HMACIdentifierService(identifier_pepper.encode())
    tokens = HMACSecretTokenService(token_pepper.encode())
    normalized = identifiers.normalize(IDENTIFIER_TYPE, identifier)
    identifier_hash = identifiers.digest(normalized)
    token_hash = tokens.digest(activation_code)
    account_uuid = uuid5(
        _NAMESPACE, f"bootstrap-account:{BOOTSTRAP_USER_ID}:{identifier_hash.hex()}",
    )
    token_uuid = uuid5(
        _NAMESPACE, f"bootstrap-activation:{account_uuid}:{token_hash.hex()}",
    )
    event_uuid = uuid5(_NAMESPACE, f"bootstrap-event:{account_uuid}")
    role_fact_uuids = {
        role: uuid5(_NAMESPACE, f"bootstrap-role:{account_uuid}:{role}:{version}")
        for version, role in enumerate(ROLE_IDS, start=1)
    }
    return BootstrapMaterial(
        identifier_hash=identifier_hash, token_hash=token_hash,
        display_suffix=normalized[-8:], account_uuid=account_uuid,
        token_uuid=token_uuid, event_uuid=event_uuid,
        role_fact_uuids=role_fact_uuids,
    )


def material_from_files(env_file: Path, material_file: Path) -> tuple[dict[str, str], BootstrapMaterial]:
    values = read_env(env_file.resolve(strict=True))
    local = read_env(material_file.resolve(strict=True))
    required = {
        "RECPRO_AUTH_IDENTIFIER_PEPPER", "RECPRO_AUTH_TOKEN_PEPPER",
        "RECPRO_IDENTITY_MYSQL_USER", "RECPRO_IDENTITY_MYSQL_PASSWORD",
    }
    if any(not values.get(key) for key in required):
        raise ValueError("identity runtime secrets are incomplete")
    identifier = local.get("RECPRO_BOOTSTRAP_ADMIN_IDENTIFIER", "")
    activation_code = local.get("RECPRO_BOOTSTRAP_ADMIN_ACTIVATION_CODE", "")
    if not identifier or not activation_code:
        raise ValueError("protected bootstrap material is incomplete")
    return values, build_material(
        identifier=identifier, activation_code=activation_code,
        identifier_pepper=values["RECPRO_AUTH_IDENTIFIER_PEPPER"],
        token_pepper=values["RECPRO_AUTH_TOKEN_PEPPER"],
    )


def initialize_material(path: Path) -> dict[str, object]:
    """Create protected one-time local material without printing either value."""
    path = path.resolve()
    if path.exists():
        raise ValueError("bootstrap material already exists; refusing to overwrite it")
    identifier = "LIBRAMAS-ADMIN-2026-001"
    activation_code = secrets.token_urlsafe(32)
    payload = (
        f"RECPRO_BOOTSTRAP_ADMIN_IDENTIFIER={identifier}\n"
        f"RECPRO_BOOTSTRAP_ADMIN_ACTIVATION_CODE={activation_code}\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    return {
        "status": "PASS", "mode": "LOCAL_MATERIAL_INITIALIZED",
        "path": str(path), "permissions": "0600",
        "plaintext_values_printed": 0, "database_connections": 0,
        "database_writes": 0,
    }


def expected_targets(material: BootstrapMaterial) -> set[str]:
    targets = {
        f"recpro.iam_user_account:user_id={BOOTSTRAP_USER_ID}:account={material.account_uuid}",
        f"recpro.iam_login_identifier:hmac-sha256={material.identifier_hash.hex()}",
        f"recpro.iam_action_token:token={material.token_uuid}",
        f"recpro.iam_security_event:event={material.event_uuid}",
    }
    targets.update(
        f"recpro.iam_user_role_fact:role={role}:fact={material.role_fact_uuids[role]}"
        for role in ROLE_IDS
    )
    return targets


def expected_fingerprint(
    database_identity: str, reviewed_commit: str, material: BootstrapMaterial,
) -> str:
    payload = (
        f"recpro_local_research_g11_bootstrap_admin:{database_identity}:{PROJECT_ROOT}:"
        f"{reviewed_commit}:{material.account_uuid}:{material.identifier_hash.hex()}:"
        f"{material.token_hash.hex()}"
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def reviewed_commit_is_ancestor(commit: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{40}", commit) is not None and subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=PROJECT_ROOT, capture_output=True,
    ).returncode == 0


def dry_run_report() -> dict[str, object]:
    return {
        "status": "PASS", "mode": "NO_WRITE_BOOTSTRAP_DRY_RUN",
        "display_name": DISPLAY_NAME, "user_id": BOOTSTRAP_USER_ID,
        "roles": list(ROLE_IDS), "maximum_rows": MAXIMUM_ROWS,
        "account_status": "PENDING_ACTIVATION",
        "activation_ttl_hours": ACTIVATION_TTL_HOURS,
        "database_connections": 0, "database_writes": 0,
        "deepseek_requests": 0, "file_deletions": 0,
        "database_physical_deletions": 0,
    }


def validate_plan(
    path: Path, *, plan_id: str, approved_hash: str,
    material: BootstrapMaterial, database_identity: str,
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
        raise ValueError("approved bootstrap plan identity does not match")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("bootstrap plan canonical hash does not match")
    commit = str(plan.get("git_commit", ""))
    if not reviewed_commit_is_ancestor(commit):
        raise ValueError("reviewed bootstrap commit is not an ancestor")
    if (
        plan.get("classification") != "S1_APPEND" or plan.get("mode") != "APPLY"
        or plan.get("max_changes") != MAXIMUM_ROWS
    ):
        raise ValueError("bootstrap operation budget is invalid")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != REQUIRED_INPUT_PATHS:
        raise ValueError("bootstrap input hash set is invalid")
    for relative in REQUIRED_INPUT_PATHS:
        if inputs.get(relative) != file_sha256(PROJECT_ROOT / relative):
            raise ValueError(f"bootstrap input hash mismatch: {relative}")
    targets = plan.get("targets")
    if not isinstance(targets, list) or len(targets) != MAXIMUM_ROWS:
        raise ValueError("bootstrap target count is invalid")
    if any(
        not isinstance(item, dict) or item.get("operation") != "APPEND"
        or item.get("expected_before_count") != 0
        or item.get("expected_after_min_count") != 1
        for item in targets
    ):
        raise ValueError("bootstrap target operation boundary is invalid")
    actual_targets = {
        str(item.get("identifier")) for item in targets if isinstance(item, dict)
    }
    if actual_targets != expected_targets(material):
        raise ValueError("bootstrap target set does not match protected material")
    environment = plan.get("environment")
    if (
        not isinstance(environment, dict)
        or environment.get("database_identity") != database_identity
        or environment.get("host_fingerprint")
        != expected_fingerprint(database_identity, commit, material)
    ):
        raise ValueError("bootstrap environment does not match approved plan")
    return plan


async def _scalar(connection: object, statement: str, parameters: tuple[object, ...] = ()) -> int:
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(statement, parameters)
        row = await cursor.fetchone()
    return int(row[0])


async def _target_counts(connection: object, material: BootstrapMaterial) -> dict[str, int]:
    counts = {
        "account": await _scalar(
            connection,
            "SELECT COUNT(*) FROM iam_user_account WHERE user_id=%s AND account_uuid=%s "
            "AND display_name=%s AND account_kind='HUMAN' AND status='PENDING_ACTIVATION' "
            "AND auth_version=1 AND role_version=3 AND must_change_password=TRUE "
            "AND failed_login_count=0 AND created_by_user_id IS NULL",
            (BOOTSTRAP_USER_ID, str(material.account_uuid), DISPLAY_NAME),
        ),
        "identifier": await _scalar(
            connection,
            "SELECT COUNT(*) FROM iam_login_identifier WHERE user_id=%s "
            "AND identifier_type='READER_NUMBER' AND identifier_hash=%s AND display_suffix=%s "
            "AND normalization_version='reader-id-nfkc-upper-v1' AND status='ACTIVE' "
            "AND disabled_at IS NULL",
            (BOOTSTRAP_USER_ID, material.identifier_hash, material.display_suffix),
        ),
        "token": await _scalar(
            connection,
            "SELECT COUNT(*) FROM iam_action_token WHERE token_uuid=%s AND user_id=%s "
            "AND purpose='ACTIVATE_ACCOUNT' AND token_hash=%s AND issued_by_user_id=%s "
            "AND consumed_at IS NULL AND revoked_at IS NULL",
            (
                str(material.token_uuid), BOOTSTRAP_USER_ID, material.token_hash,
                BOOTSTRAP_USER_ID,
            ),
        ),
        "event": await _scalar(
            connection,
            "SELECT COUNT(*) FROM iam_security_event WHERE event_uuid=%s "
            "AND event_type='ACCOUNT_PROVISIONED' AND outcome='SUCCESS' "
            "AND user_id=%s AND actor_user_id=%s AND identifier_hash=%s "
            "AND reason_code='INITIAL_ADMIN_BOOTSTRAP'",
            (
                str(material.event_uuid), BOOTSTRAP_USER_ID, BOOTSTRAP_USER_ID,
                material.identifier_hash,
            ),
        ),
    }
    for role, fact_uuid in material.role_fact_uuids.items():
        counts[f"role:{role}"] = await _scalar(
            connection,
            "SELECT COUNT(*) FROM iam_user_role_fact WHERE fact_uuid=%s AND user_id=%s "
            "AND role_id=%s AND role_version=%s AND action='GRANT' AND actor_user_id=%s "
            "AND reason_code='G11_INITIAL_ADMIN_BOOTSTRAP' AND idempotency_key=%s",
            (
                str(fact_uuid), BOOTSTRAP_USER_ID, ROLE_IDS[role],
                list(ROLE_IDS).index(role) + 1, BOOTSTRAP_USER_ID,
                f"g11-bootstrap-admin-role-{role}",
            ),
        )
    return counts


async def _assert_reference_seeds(connection: object) -> None:
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(
            "SELECT role_id, role_code FROM iam_role WHERE role_id IN (1,2,3) ORDER BY role_id",
        )
        roles = tuple((int(row[0]), str(row[1])) for row in await cursor.fetchall())
    if roles != ((1, "user"), (2, "librarian"), (3, "research_admin")):
        raise ValueError("required fixed role seeds are missing or changed")


async def apply_plan(args: argparse.Namespace) -> dict[str, object]:
    values, material = material_from_files(args.env_file, args.material_file)
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
        await _assert_reference_seeds(connection)
        counts = await _target_counts(connection, material)
        total_accounts = await _scalar(connection, "SELECT COUNT(*) FROM iam_user_account")
        if all(value == 1 for value in counts.values()) and total_accounts == 1:
            await connection.rollback()
            return {
                "status": "PASS", "mode": "IDEMPOTENT_REPLAY",
                "rows_written": 0, "user_id": BOOTSTRAP_USER_ID,
                "activation_material_path": str(args.material_file.resolve()),
                "plaintext_values_printed": 0, "deletions": 0,
            }
        if any(counts.values()) or total_accounts != 0:
            raise ValueError("identity database is not in the exact empty bootstrap state")
        now = datetime.now(UTC).replace(tzinfo=None)
        expires_at = now + timedelta(hours=ACTIVATION_TTL_HOURS)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO iam_user_account "
                "(user_id,account_uuid,display_name,account_kind,status,auth_version,role_version,"
                "must_change_password,failed_login_count,created_by_user_id,created_at,updated_at) "
                "VALUES (%s,%s,%s,'HUMAN','PENDING_ACTIVATION',1,3,TRUE,0,NULL,%s,%s)",
                (BOOTSTRAP_USER_ID, str(material.account_uuid), DISPLAY_NAME, now, now),
            )
            await cursor.execute(
                "INSERT INTO iam_login_identifier "
                "(user_id,identifier_type,identifier_hash,display_suffix,normalization_version,status,created_at) "
                "VALUES (%s,'READER_NUMBER',%s,%s,'reader-id-nfkc-upper-v1','ACTIVE',%s)",
                (BOOTSTRAP_USER_ID, material.identifier_hash, material.display_suffix, now),
            )
            for version, (role, role_id) in enumerate(ROLE_IDS.items(), start=1):
                await cursor.execute(
                    "INSERT INTO iam_user_role_fact "
                    "(fact_uuid,user_id,role_id,role_version,action,actor_user_id,reason_code,"
                    "idempotency_key,occurred_at,created_at) "
                    "VALUES (%s,%s,%s,%s,'GRANT',%s,'G11_INITIAL_ADMIN_BOOTSTRAP',%s,%s,%s)",
                    (
                        str(material.role_fact_uuids[role]), BOOTSTRAP_USER_ID, role_id,
                        version, BOOTSTRAP_USER_ID, f"g11-bootstrap-admin-role-{role}", now, now,
                    ),
                )
            await cursor.execute(
                "INSERT INTO iam_action_token "
                "(token_uuid,user_id,purpose,token_hash,issued_by_user_id,expires_at,created_at) "
                "VALUES (%s,%s,'ACTIVATE_ACCOUNT',%s,%s,%s,%s)",
                (
                    str(material.token_uuid), BOOTSTRAP_USER_ID, material.token_hash,
                    BOOTSTRAP_USER_ID, expires_at, now,
                ),
            )
            metadata = json.dumps(
                {"bootstrap_version": "g11-bootstrap-v1", "roles": list(ROLE_IDS)},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
            await cursor.execute(
                "INSERT INTO iam_security_event "
                "(event_uuid,event_type,outcome,user_id,actor_user_id,identifier_hash,reason_code,"
                "metadata_json,occurred_at,created_at) "
                "VALUES (%s,'ACCOUNT_PROVISIONED','SUCCESS',%s,%s,%s,'INITIAL_ADMIN_BOOTSTRAP',%s,%s,%s)",
                (
                    str(material.event_uuid), BOOTSTRAP_USER_ID, BOOTSTRAP_USER_ID,
                    material.identifier_hash, metadata, now, now,
                ),
            )
        after = await _target_counts(connection, material)
        if not all(value == 1 for value in after.values()):
            raise RuntimeError("bootstrap postflight reconciliation failed")
        await connection.commit()
        return {
            "status": "PASS", "mode": "APPLY", "rows_written": MAXIMUM_ROWS,
            "user_id": BOOTSTRAP_USER_ID, "account_status": "PENDING_ACTIVATION",
            "roles": list(ROLE_IDS), "activation_expires_at": expires_at.isoformat() + "Z",
            "activation_material_path": str(args.material_file.resolve()),
            "plaintext_values_printed": 0, "deletions": 0,
            "deepseek_requests": 0,
        }
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--initialize-local-material", action="store_true")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--approved-plan-hash", default="")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--material-file", type=Path, default=DEFAULT_MATERIAL_FILE)
    args = parser.parse_args(argv)
    if args.apply and args.initialize_local_material:
        raise ValueError("material initialization and database apply are separate operations")
    if args.initialize_local_material:
        report = initialize_material(args.material_file)
    elif args.apply:
        report = asyncio.run(apply_plan(args))
    else:
        report = dry_run_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
