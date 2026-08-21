#!/usr/bin/env python3
"""Validate or exactly apply the forward-only G11 identity migration.

The default mode is a deterministic, zero-connection dry-run. Apply requires
an exact approved ChangePlan that is bound to every executable input. This
module never drops, deletes, truncates, replaces, renames, or cascades data.
"""

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

from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/009_g11_identity_access.sql"
DEFAULT_PLAN = PROJECT_ROOT / "plans/g11-identity-access.json"
MIGRATION_ID = "g11-identity-access-v1"
IAM_TABLES = (
    "iam_user_account",
    "iam_login_identifier",
    "iam_password_credential",
    "iam_role",
    "iam_permission",
    "iam_role_permission_fact",
    "iam_user_role_fact",
    "iam_auth_session",
    "iam_refresh_token",
    "iam_action_token",
    "iam_security_event",
    "user_personalization_consent_fact",
)
IAM_VIEWS = (
    "iam_effective_role_permission_v",
    "iam_effective_user_role_v",
    "user_effective_personalization_consent_v",
)
SEED_ROWS = {
    "iam_role": 4,
    "iam_permission": 15,
    "iam_role_permission_fact": 17,
    "recpro_schema_migration": 1,
}
MAXIMUM_ROWS = sum(SEED_ROWS.values())
REQUIRED_INPUT_PATHS = frozenset({
    "backend/app/identity/adapters/mysql.py",
    "backend/app/identity/application.py",
    "backend/app/identity/domain.py",
    "backend/app/identity/ports.py",
    "backend/app/identity/security.py",
    "infra/mysql/migrations/009_g11_identity_access.sql",
    "scripts/execute_g11_identity_migration.py",
})
_HASH = re.compile(r"^[0-9a-f]{64}$")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def reviewed_commit_is_ancestor(reviewed_commit: str) -> bool:
    if re.fullmatch(r"[0-9a-f]{40}", reviewed_commit) is None:
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", reviewed_commit, "HEAD"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    return result.returncode == 0


def validate_migration_statements(source: str) -> tuple[str, ...]:
    statements = tuple(item.strip() for item in source.split(";") if item.strip())
    if len(statements) != 19:
        raise ValueError("G11 identity migration must contain exactly 19 statements")
    table_index = 0
    view_index = 0
    inserts: list[str] = []
    for statement in statements:
        compact = re.sub(r"--[^\n]*", " ", statement).strip()
        upper = re.sub(r"\s+", " ", compact).upper()
        if table_index < len(IAM_TABLES) and upper.startswith(
            f"CREATE TABLE IF NOT EXISTS {IAM_TABLES[table_index].upper()} "
        ):
            table_index += 1
        elif table_index == len(IAM_TABLES) and view_index < len(IAM_VIEWS) and upper.startswith(
            f"CREATE VIEW {IAM_VIEWS[view_index].upper()} AS "
        ):
            view_index += 1
        elif upper.startswith("INSERT IGNORE INTO "):
            match = re.match(r"INSERT IGNORE INTO ([A-Z0-9_]+)", upper)
            target = match.group(1).lower() if match else ""
            if target not in SEED_ROWS:
                raise ValueError("migration insert target is outside the fixed seed allowlist")
            inserts.append(target)
        else:
            raise ValueError("migration statement order or operation is outside the G11 allowlist")
        if re.search(
            r"\b(DROP|TRUNCATE|ALTER|RENAME|REPLACE)\b|\bDELETE\s+FROM\b|^UPDATE\b|CREATE\s+OR\s+REPLACE",
            upper,
        ):
            raise ValueError("migration contains a destructive or mutable-schema operation")
        if "ON DELETE CASCADE" in upper or "ON UPDATE CASCADE" in upper:
            raise ValueError("migration contains a cascading foreign key")
    if table_index != len(IAM_TABLES) or view_index != len(IAM_VIEWS):
        raise ValueError("migration schema object set is incomplete")
    if inserts != ["iam_role", "iam_permission", "iam_role_permission_fact", "recpro_schema_migration"]:
        raise ValueError("migration fixed seed order is invalid")
    return statements


def dry_run_report() -> dict[str, object]:
    statements = validate_migration_statements(MIGRATION.read_text(encoding="utf-8"))
    return {
        "schema_version": "g11-identity-migration-dry-run-v1",
        "status": "PASS",
        "mode": "NO_WRITE_DRY_RUN",
        "migration_sha256": file_sha256(MIGRATION),
        "migration_statement_count": len(statements),
        "new_tables": list(IAM_TABLES),
        "new_views": list(IAM_VIEWS),
        "seed_rows": dict(SEED_ROWS),
        "maximum_rows": MAXIMUM_ROWS,
        "bootstrap_account_rows": 0,
        "real_reader_account_rows": 0,
        "database_connections": 0,
        "database_writes": 0,
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
    }


def validate_plan(path: Path, *, plan_id: str, approved_hash: str) -> dict[str, object]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if str(plan.get("plan_id")) != plan_id or str(plan.get("plan_hash")) != approved_hash:
        raise ValueError("approved plan identity does not match the plan file")
    if _HASH.fullmatch(approved_hash) is None:
        raise ValueError("approved plan hash is malformed")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("ChangePlan canonical hash does not match")
    reviewed_commit = str(plan.get("git_commit", ""))
    if not reviewed_commit_is_ancestor(reviewed_commit):
        raise ValueError("ChangePlan commit is not an ancestor of the current revision")
    if plan.get("classification") != "S1_APPEND" or plan.get("mode") != "APPLY":
        raise ValueError("ChangePlan operation classification is invalid")
    if plan.get("max_changes") != MAXIMUM_ROWS:
        raise ValueError("ChangePlan row budget is invalid")
    if plan.get("new_tables") != list(IAM_TABLES) or plan.get("new_views") != list(IAM_VIEWS):
        raise ValueError("ChangePlan schema target set is invalid")
    input_hashes = plan.get("input_hashes")
    if not isinstance(input_hashes, dict) or set(input_hashes) != REQUIRED_INPUT_PATHS:
        raise ValueError("ChangePlan input hash set is incomplete")
    for relative in REQUIRED_INPUT_PATHS:
        candidate = (PROJECT_ROOT / relative).resolve(strict=True)
        if not candidate.is_relative_to(PROJECT_ROOT) or input_hashes.get(relative) != file_sha256(candidate):
            raise ValueError(f"ChangePlan input hash mismatch: {relative}")
    return plan


async def _object_count(connection: object, *, object_type: str, name: str) -> int:
    if object_type not in {"BASE TABLE", "VIEW"} or name not in set(IAM_TABLES) | set(IAM_VIEWS):
        raise ValueError("schema object lookup is outside allowlist")
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_type = %s AND table_name = %s",
            (object_type, name),
        )
        row = await cursor.fetchone()
    return int(row[0])


async def _seed_count(connection: object, target: str) -> int:
    statements = {
        "iam_role": "SELECT COUNT(*) FROM iam_role WHERE role_id BETWEEN 1 AND 4",
        "iam_permission": "SELECT COUNT(*) FROM iam_permission WHERE permission_id BETWEEN 1 AND 15",
        "iam_role_permission_fact": "SELECT COUNT(*) FROM iam_role_permission_fact WHERE reason_code = 'G11_FIXED_SEED'",
        "recpro_schema_migration": "SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id = 'g11-identity-access-v1'",
    }
    if target not in statements:
        raise ValueError("seed count target is outside allowlist")
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(statements[target])
        row = await cursor.fetchone()
    return int(row[0])


async def apply_approved_plan(args: argparse.Namespace) -> dict[str, object]:
    plan = validate_plan(
        args.plan.resolve(strict=True), plan_id=args.plan_id,
        approved_hash=args.approved_plan_hash,
    )
    statements = validate_migration_statements(MIGRATION.read_text(encoding="utf-8"))
    values = read_env(args.env_file.resolve(strict=True))
    user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    database = values.get("RECPRO_MYSQL_DATABASE", "")
    if not user or not password or not port or not database:
        raise ValueError("explicit migration connection settings are required")
    expected_identity = f"mysql://127.0.0.1:{port}/{database}"
    if plan.get("database_identity") != expected_identity:
        raise ValueError("runtime database identity does not match ChangePlan")
    connection = await asyncmy.connect(
        host="127.0.0.1", port=int(port), user=user, password=password,
        db=database, autocommit=False,
    )
    try:
        table_before = {
            name: await _object_count(connection, object_type="BASE TABLE", name=name)
            for name in IAM_TABLES
        }
        view_before = {
            name: await _object_count(connection, object_type="VIEW", name=name)
            for name in IAM_VIEWS
        }
        marker_exists = False
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id = %s",
                (MIGRATION_ID,),
            )
            marker_exists = int((await cursor.fetchone())[0]) == 1
        if marker_exists:
            if not all(table_before.values()) or not all(view_before.values()):
                raise ValueError("migration marker exists but schema object set is incomplete")
            counts = {target: await _seed_count(connection, target) for target in SEED_ROWS}
            if counts != SEED_ROWS:
                raise ValueError("migration marker exists but fixed seed counts differ")
            return {
                "status": "PASS", "mode": "IDEMPOTENT_REPLAY", "rows_written": 0,
                "tables_created": 0, "views_created": 0, "seed_counts": counts,
            }
        if any(table_before.values()) or any(view_before.values()):
            raise ValueError("partial G11 schema exists without migration marker; refusing to mutate")
        affected = 0
        async with connection.cursor() as cursor:
            for statement in statements:
                await cursor.execute(statement)
                if statement.lstrip().upper().startswith("INSERT IGNORE INTO"):
                    affected += max(0, int(cursor.rowcount))
                    if affected > MAXIMUM_ROWS:
                        raise ValueError("migration exceeded approved row budget")
        await connection.commit()
        table_after = {
            name: await _object_count(connection, object_type="BASE TABLE", name=name)
            for name in IAM_TABLES
        }
        view_after = {
            name: await _object_count(connection, object_type="VIEW", name=name)
            for name in IAM_VIEWS
        }
        counts = {target: await _seed_count(connection, target) for target in SEED_ROWS}
        if not all(table_after.values()) or not all(view_after.values()) or counts != SEED_ROWS:
            raise RuntimeError("post-migration reconciliation failed")
        if affected != MAXIMUM_ROWS:
            raise RuntimeError("migration did not append the exact fixed seed budget")
        return {
            "status": "PASS", "mode": "APPLY", "rows_written": affected,
            "tables_created": len(IAM_TABLES), "views_created": len(IAM_VIEWS),
            "seed_counts": counts,
        }
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--approved-plan-hash", default="")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = asyncio.run(apply_approved_plan(args)) if args.apply else dry_run_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
