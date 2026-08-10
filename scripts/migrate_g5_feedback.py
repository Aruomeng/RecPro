"""Apply the forward-only G5 feedback/state migration with operator evidence."""

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
from scripts.g5_runtime_permissions import grant_g5_runtime_projection
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/006_g5_feedback_state.sql"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_evidence(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    env_path = args.env_file.resolve()
    migration_path = args.migration_file.resolve()
    values = read_env(env_path)
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    migration_user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    migration_password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not migration_user or not migration_password:
        raise ValueError("G5 migration credentials are required")
    statements = split_statements(migration_path.read_text(encoding="utf-8"))
    evidence_path = PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id / "migration.json"
    evidence = {
        "schema_version": "g5-feedback-migration-evidence-v1",
        "run_id": run_id,
        "status": "DRY_RUN",
        "migration_file": str(migration_path.relative_to(PROJECT_ROOT)),
        "migration_sha256": file_sha256(migration_path),
        "statement_count": len(statements),
        "destructive_actions": 0,
        "applied": False,
    }
    if args.apply:
        await apply_statements(
            host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
            database=values["RECPRO_MYSQL_DATABASE"],
            admin_user=migration_user,
            admin_password=migration_password,
            statements=statements,
        )
        await grant_g5_runtime_projection(
            host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
            database=values["RECPRO_MYSQL_DATABASE"],
            root_password=values["RECPRO_MYSQL_ROOT_PASSWORD"],
            runtime_user=values["RECPRO_MYSQL_USER"],
        )
        evidence.update({"status": "APPLIED", "applied": True, "applied_at": datetime.now(UTC).isoformat()})
    write_evidence(evidence_path, evidence)
    print(f"[PASS] G5 feedback migration {'applied' if args.apply else 'validated'}: {evidence_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--migration-file", type=Path, default=MIGRATION)
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G5 feedback migration did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
