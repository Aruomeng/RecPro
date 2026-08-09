"""Apply the append-only G2 MySQL schema with an explicit operator action."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import asyncmy

from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/001_g2_core.sql"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
FORBIDDEN_SQL = re.compile(
    r"\b(?:"
    + "DE" + r"LETE\s+FROM|"
    + "TRUN" + r"CATE|"
    + "DR" + r"OP\s+(?:TABLE|DATABASE|SCHEMA|INDEX)|"
    + "ALTER\s+TABLE|"
    + "REPL" + r"ACE\s+INTO)\b",
    re.IGNORECASE,
)


def split_statements(source: str) -> tuple[str, ...]:
    """Split this deliberately simple migration format on statement terminators."""

    statements = tuple(item.strip() for item in source.split(";") if item.strip())
    if not statements:
        raise ValueError("migration file contains no SQL statements")
    for statement in statements:
        if FORBIDDEN_SQL.search(statement):
            raise ValueError("migration contains a forbidden destructive SQL statement")
        if not re.match(r"^(?:--[^\n]*\n\s*)*(?:CREATE TABLE|INSERT IGNORE)", statement, re.I):
            raise ValueError("G2 migration allows only CREATE TABLE and INSERT IGNORE")
    return statements


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_evidence(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def apply_statements(
    *,
    host_port: int,
    database: str,
    admin_user: str,
    admin_password: str,
    statements: tuple[str, ...],
) -> None:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=host_port,
        user=admin_user,
        password=admin_password,
        db=database,
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
        init_command="SET sql_notes=0",
    )
    try:
        async with connection.cursor() as cursor:
            for statement in statements:
                await cursor.execute(statement)
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--migration-file", type=Path, default=DEFAULT_MIGRATION)
    parser.add_argument("--apply", action="store_true", help="execute the validated forward migration")
    return parser


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    env_path = args.env_file.resolve()
    migration_path = args.migration_file.resolve()
    values = read_env(env_path)
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    admin_user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    admin_password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not admin_user or not admin_password:
        raise ValueError("G2 migration credentials are required")
    source = migration_path.read_text(encoding="utf-8")
    statements = split_statements(source)
    source_hash = file_sha256(migration_path)
    evidence_path = (
        PROJECT_ROOT / "artifacts" / "verification" / "g2" / run_id / "migration.json"
    )
    if not args.apply:
        write_evidence(
            evidence_path,
            {
                "schema_version": "g2-migration-evidence-v1",
                "run_id": run_id,
                "status": "DRY_RUN",
                "migration_file": str(migration_path.relative_to(PROJECT_ROOT)),
                "migration_sha256": source_hash,
                "statement_count": len(statements),
                "destructive_actions": 0,
                "applied": False,
            },
        )
        print(f"[PASS] G2 migration dry-run: {evidence_path}")
        return 0
    await apply_statements(
        host_port=int(values.get("RECPRO_MYSQL_HOST_PORT", "")),
        database=values["RECPRO_MYSQL_DATABASE"],
        admin_user=admin_user,
        admin_password=admin_password,
        statements=statements,
    )
    write_evidence(
        evidence_path,
        {
            "schema_version": "g2-migration-evidence-v1",
            "run_id": run_id,
            "status": "APPLIED",
            "migration_file": str(migration_path.relative_to(PROJECT_ROOT)),
            "migration_sha256": source_hash,
            "statement_count": len(statements),
            "database": values["RECPRO_MYSQL_DATABASE"],
            "applied_at": datetime.now(UTC).isoformat(),
            "destructive_actions": 0,
            "applied": True,
        },
    )
    print(f"[PASS] G2 migration applied: {evidence_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G2 migration did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
