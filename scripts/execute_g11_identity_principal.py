#!/usr/bin/env python3
"""Dry-run or provision the plan-bound least-privilege G11 MySQL principal."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Sequence

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = PROJECT_ROOT / "contracts/safety/change-plan.schema.json"
DEFAULT_PLAN = PROJECT_ROOT / "plans/g11-identity-principal.json"
IDENTITY_USER = "recpro_identity"
IDENTITY_HOST = "%"
TABLE_PRIVILEGES: dict[str, tuple[str, ...]] = {
    "iam_user_account": ("SELECT", "INSERT", "UPDATE"),
    "iam_login_identifier": ("SELECT", "INSERT"),
    "iam_password_credential": ("SELECT", "INSERT", "UPDATE"),
    "iam_role": ("SELECT",),
    "iam_permission": ("SELECT",),
    "iam_role_permission_fact": ("SELECT",),
    "iam_user_role_fact": ("SELECT", "INSERT"),
    "iam_auth_session": ("SELECT", "INSERT", "UPDATE"),
    "iam_refresh_token": ("SELECT", "INSERT", "UPDATE"),
    "iam_action_token": ("SELECT", "INSERT", "UPDATE"),
    "iam_security_event": ("SELECT", "INSERT"),
    "user_personalization_consent_fact": ("SELECT", "INSERT"),
    "iam_effective_role_permission_v": ("SELECT",),
    "iam_effective_user_role_v": ("SELECT",),
    "user_effective_personalization_consent_v": ("SELECT",),
}
PRIVILEGE_FACTS = sum(len(value) for value in TABLE_PRIVILEGES.values())
MAXIMUM_CHANGES = 1 + PRIVILEGE_FACTS
REQUIRED_INPUT_PATHS = frozenset({
    "backend/app/composition.py",
    "backend/app/config.py",
    "backend/app/identity/adapters/mysql.py",
    "scripts/build_g11_identity_principal_plan.py",
    "scripts/execute_g11_identity_principal.py",
})
_HASH = re.compile(r"^[0-9a-f]{64}$")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reviewed_commit_is_ancestor(commit: str) -> bool:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        return False
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=PROJECT_ROOT, capture_output=True,
    ).returncode == 0


def expected_fingerprint(database_identity: str, reviewed_commit: str) -> str:
    value = f"recpro_local_research_g11_identity_principal:{database_identity}:{PROJECT_ROOT}:{reviewed_commit}"
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def dry_run_report() -> dict[str, object]:
    return {
        "status": "PASS", "mode": "NO_WRITE_DRY_RUN",
        "principal": f"{IDENTITY_USER}@{IDENTITY_HOST}",
        "table_count": len(TABLE_PRIVILEGES),
        "privilege_fact_count": PRIVILEGE_FACTS,
        "maximum_changes": MAXIMUM_CHANGES,
        "allowed_privileges": sorted({item for values in TABLE_PRIVILEGES.values() for item in values}),
        "forbidden_privileges": ["DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT OPTION"],
        "database_connections": 0, "database_writes": 0,
        "business_row_writes": 0, "deepseek_requests": 0,
        "file_deletions": 0, "database_physical_deletions": 0,
    }


def validate_plan(path: Path, *, plan_id: str, approved_hash: str) -> dict[str, object]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker(),
    ).validate(plan)
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != approved_hash or _HASH.fullmatch(approved_hash) is None:
        raise ValueError("approved identity principal plan does not match")
    unsigned = dict(plan); unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("identity principal plan canonical hash does not match")
    commit = str(plan.get("git_commit", ""))
    if not reviewed_commit_is_ancestor(commit):
        raise ValueError("reviewed principal commit is not an ancestor")
    if plan.get("classification") != "S1_APPEND" or plan.get("mode") != "APPLY" or plan.get("max_changes") != MAXIMUM_CHANGES:
        raise ValueError("identity principal plan operation budget is invalid")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != REQUIRED_INPUT_PATHS:
        raise ValueError("identity principal input hash set is invalid")
    for relative in REQUIRED_INPUT_PATHS:
        if inputs.get(relative) != file_sha256(PROJECT_ROOT / relative):
            raise ValueError(f"identity principal input hash mismatch: {relative}")
    targets = plan.get("targets")
    expected = {f"mysql-principal:{IDENTITY_USER}@{IDENTITY_HOST}"} | {
        f"recpro.{table}:{privilege}" for table, privileges in TABLE_PRIVILEGES.items() for privilege in privileges
    }
    if not isinstance(targets, list) or {str(item.get("identifier")) for item in targets if isinstance(item, dict)} != expected:
        raise ValueError("identity principal target set is invalid")
    return plan


async def _principal_exists(connection: object) -> bool:
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute("SELECT COUNT(*) FROM mysql.user WHERE User = %s AND Host = %s", (IDENTITY_USER, IDENTITY_HOST))
        return int((await cursor.fetchone())[0]) == 1


async def _actual_privileges(connection: object, database: str) -> set[tuple[str, str]]:
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(
            "SELECT TABLE_NAME, PRIVILEGE_TYPE FROM information_schema.TABLE_PRIVILEGES "
            "WHERE GRANTEE = %s AND TABLE_SCHEMA = %s",
            (f"'{IDENTITY_USER}'@'{IDENTITY_HOST}'", database),
        )
        return {(str(row[0]), str(row[1]).upper()) for row in await cursor.fetchall()}


async def apply_plan(args: argparse.Namespace) -> dict[str, object]:
    plan = validate_plan(args.plan.resolve(strict=True), plan_id=args.plan_id, approved_hash=args.approved_plan_hash)
    values = read_env(args.env_file.resolve(strict=True))
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    database = values.get("RECPRO_MYSQL_DATABASE", "")
    root_password = values.get("RECPRO_MYSQL_ROOT_PASSWORD", "")
    identity_user = values.get("RECPRO_IDENTITY_MYSQL_USER", "")
    identity_password = values.get("RECPRO_IDENTITY_MYSQL_PASSWORD", "")
    if not port or not root_password or identity_user != IDENTITY_USER or len(identity_password) < 20:
        raise ValueError("root and 20+ character identity credentials are required")
    database_identity = f"mysql://127.0.0.1:{port}/{database}"
    environment = plan.get("environment")
    if not isinstance(environment, dict) or environment.get("database_identity") != database_identity or environment.get("host_fingerprint") != expected_fingerprint(database_identity, str(plan["git_commit"])):
        raise ValueError("identity principal environment does not match approved plan")
    expected = {(table, privilege) for table, privileges in TABLE_PRIVILEGES.items() for privilege in privileges}
    connection = await asyncmy.connect(host="127.0.0.1", port=int(port), user="root", password=root_password, db=database, autocommit=True)
    try:
        exists = await _principal_exists(connection)
        actual = await _actual_privileges(connection, database) if exists else set()
        if exists:
            if actual == expected:
                return {"status": "PASS", "mode": "IDEMPOTENT_REPLAY", "changes": 0, "business_row_writes": 0}
            raise ValueError("identity principal exists with a partial or different grant set")
        async with connection.cursor() as cursor:
            await cursor.execute(f"CREATE USER '{IDENTITY_USER}'@'{IDENTITY_HOST}' IDENTIFIED BY %s", (identity_password,))
            for table, privileges in TABLE_PRIVILEGES.items():
                privilege_sql = ", ".join(privileges)
                await cursor.execute(f"GRANT {privilege_sql} ON `{database}`.`{table}` TO '{IDENTITY_USER}'@'{IDENTITY_HOST}'")
        actual = await _actual_privileges(connection, database)
        if actual != expected:
            raise RuntimeError("identity principal grant reconciliation failed")
        return {"status": "PASS", "mode": "APPLY", "changes": MAXIMUM_CHANGES, "business_row_writes": 0}
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--approved-plan-hash", default="")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    args = parser.parse_args(argv)
    report = asyncio.run(apply_plan(args)) if args.apply else dry_run_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
