"""Apply the append-only G3 task transition audit migration."""

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

from scripts.migrate_g2 import apply_statements, split_statements
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/003_g3_task_transition.sql"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--migration-file", type=Path, default=DEFAULT_MIGRATION)
    parser.add_argument("--apply", action="store_true")
    return parser


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    migration_path = args.migration_file.resolve()
    statements = split_statements(migration_path.read_text(encoding="utf-8"))
    user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not user or not password:
        raise ValueError("G3 migration credentials are required")
    if args.apply:
        await apply_statements(
            host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
            database=values["RECPRO_MYSQL_DATABASE"],
            admin_user=user,
            admin_password=password,
            statements=statements,
        )
    evidence_path = PROJECT_ROOT / "artifacts" / "verification" / "g3" / run_id / "transition-migration.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=False)
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "g3-transition-migration-evidence-v1",
                "run_id": run_id,
                "status": "APPLIED" if args.apply else "DRY_RUN",
                "migration_file": str(migration_path.relative_to(PROJECT_ROOT)),
                "migration_sha256": hashlib.sha256(migration_path.read_bytes()).hexdigest(),
                "statement_count": len(statements),
                "database": values["RECPRO_MYSQL_DATABASE"],
                "applied_at": datetime.now(UTC).isoformat() if args.apply else None,
                "destructive_actions": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[PASS] G3 transition migration {'applied' if args.apply else 'validated'}: {evidence_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G3 transition migration did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
