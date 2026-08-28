#!/usr/bin/env python3
"""Dry-run or apply the exactly approved append-only G12 review migration."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence

import asyncmy

from backend.app.knowledge_review.loader import load_v2_review_proposals
from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/010_g12_knowledge_review.sql"
PROPOSALS = PROJECT_ROOT / "artifacts/verification/book-graph-v2/lib-books-v2-20260828/review-proposals.jsonl"
MIGRATION_ID = "g12-knowledge-review-v1"
TABLES = ("knowledge_review_proposal", "knowledge_review_action_fact")
VIEWS = ("knowledge_review_current_v",)
PROPOSAL_ROWS = 262
SEED_ROWS = 4
MAX_ROWS = PROPOSAL_ROWS + SEED_ROWS
REQUIRED_INPUTS = frozenset({
    "backend/app/identity/domain.py",
    "backend/app/knowledge_review/domain.py",
    "backend/app/knowledge_review/loader.py",
    "backend/app/knowledge_review/mysql.py",
    "backend/app/knowledge_review/service.py",
    "infra/mysql/migrations/010_g12_knowledge_review.sql",
    "scripts/build_g12_knowledge_review_change_plan.py",
    "scripts/execute_g12_knowledge_review_plan.py",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/review-proposals.jsonl",
})


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def statements() -> tuple[str, ...]:
    result = tuple(item.strip() for item in MIGRATION.read_text(encoding="utf-8").split(";") if item.strip())
    if len(result) != 6:
        raise ValueError("G12 migration must contain exactly six statements")
    prefixes = (
        "CREATE TABLE IF NOT EXISTS KNOWLEDGE_REVIEW_PROPOSAL ",
        "CREATE TABLE IF NOT EXISTS KNOWLEDGE_REVIEW_ACTION_FACT ",
        "CREATE VIEW KNOWLEDGE_REVIEW_CURRENT_V AS ",
        "INSERT IGNORE INTO IAM_PERMISSION ",
        "INSERT IGNORE INTO IAM_ROLE_PERMISSION_FACT ",
        "INSERT IGNORE INTO RECPRO_SCHEMA_MIGRATION ",
    )
    for statement, prefix in zip(result, prefixes, strict=True):
        compact = re.sub(r"--[^\n]*", " ", statement).strip()
        upper = re.sub(r"\s+", " ", compact).upper()
        if not upper.startswith(prefix):
            raise ValueError("G12 migration statement order is outside the allowlist")
        if re.search(r"\b(DROP|TRUNCATE|ALTER|RENAME|REPLACE)\b|\bDELETE\s+FROM\b|^UPDATE\b|CREATE\s+OR\s+REPLACE", upper):
            raise ValueError("G12 migration contains a destructive or mutable operation")
        if "ON DELETE CASCADE" in upper or "ON UPDATE CASCADE" in upper:
            raise ValueError("G12 migration contains a cascading foreign key")
    return result


def dry_run_report() -> dict[str, object]:
    proposals = load_v2_review_proposals(PROPOSALS)
    return {
        "schema_version": "g12-knowledge-review-dry-run-v1",
        "status": "PASS", "mode": "NO_WRITE_DRY_RUN",
        "migration_sha256": file_hash(MIGRATION),
        "statement_count": len(statements()),
        "new_tables": list(TABLES), "new_views": list(VIEWS),
        "permission_rows": 1, "role_permission_fact_rows": 2,
        "migration_marker_rows": 1, "proposal_rows": len(proposals),
        "action_fact_rows": 0, "maximum_rows": MAX_ROWS,
        "database_connections": 0, "database_writes": 0,
        "neo4j_writes": 0, "deepseek_requests": 0,
        "file_deletions": 0, "database_physical_deletions": 0,
    }


def validate_plan(path: Path, plan_id: str, approved_hash: str) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != approved_hash or re.fullmatch(r"[0-9a-f]{64}", approved_hash) is None:
        raise ValueError("approved G12 plan identity does not match")
    unsigned = dict(plan); unsigned.pop("plan_hash", None)
    if sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("G12 canonical plan hash does not match")
    commit = str(plan.get("git_commit", ""))
    if subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=PROJECT_ROOT).returncode != 0:
        raise ValueError("reviewed G12 commit is not an ancestor")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != REQUIRED_INPUTS:
        raise ValueError("G12 approved input set is incomplete")
    for relative, digest in inputs.items():
        candidate = (PROJECT_ROOT / relative).resolve(strict=True)
        if not candidate.is_relative_to(PROJECT_ROOT) or file_hash(candidate) != digest:
            raise ValueError("G12 approved input hash mismatch")
    if plan.get("max_changes") != MAX_ROWS:
        raise ValueError("G12 approved row budget does not match")
    return plan


async def _object_count(connection: Any, name: str, kind: str) -> int:
    if name not in set(TABLES) | set(VIEWS) or kind not in {"BASE TABLE", "VIEW"}:
        raise ValueError("G12 schema lookup is outside allowlist")
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s AND table_type=%s", (name, kind))
        return int((await cursor.fetchone())[0])


async def apply(args: argparse.Namespace) -> dict[str, object]:
    plan = validate_plan(args.plan.resolve(strict=True), args.plan_id, args.approved_plan_hash)
    approved_statements = statements()
    proposals = load_v2_review_proposals(PROPOSALS)
    if len(proposals) != PROPOSAL_ROWS:
        raise ValueError("G12 proposal artifact count differs from approved budget")
    values = read_env(args.env_file.resolve(strict=True))
    user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT", "")
    database = values.get("RECPRO_MYSQL_DATABASE", "")
    identity = f"mysql://127.0.0.1:{port}/{database}"
    if not all((user, password, port, database)) or plan.get("database_identity") != identity:
        raise ValueError("G12 runtime database identity is not approved")
    connection = await asyncmy.connect(host="127.0.0.1", port=int(port), user=user, password=password, db=database, autocommit=False)
    try:
        table_before = [await _object_count(connection, name, "BASE TABLE") for name in TABLES]
        view_before = [await _object_count(connection, name, "VIEW") for name in VIEWS]
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id=%s", (MIGRATION_ID,))
            marker = int((await cursor.fetchone())[0])
        if marker or any(table_before) or any(view_before):
            raise ValueError("G12 target is not an untouched pre-migration state")
        affected = 0
        async with connection.cursor() as cursor:
            for statement in approved_statements:
                await cursor.execute(statement)
                if re.sub(r"--[^\n]*", " ", statement).strip().upper().startswith("INSERT IGNORE"):
                    affected += max(0, int(cursor.rowcount))
            for proposal in proposals:
                await cursor.execute(
                    "INSERT IGNORE INTO knowledge_review_proposal (proposal_uuid,proposal_type,graph_version,subject_id,relation_type,object_id,source_refs_json,reason_codes_json,confidence,agent_name,task_id,workspace_id,idempotency_sha256,occurred_at,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (str(proposal.proposal_uuid), proposal.proposal_type, proposal.graph_version, proposal.subject_id, proposal.relation_type, proposal.object_id, json.dumps(proposal.source_refs, ensure_ascii=False), json.dumps(proposal.reason_codes, ensure_ascii=False), proposal.confidence, proposal.agent_name, None, None, proposal.idempotency_sha256, proposal.occurred_at.replace(tzinfo=None), proposal.occurred_at.replace(tzinfo=None)),
                )
                affected += max(0, int(cursor.rowcount))
                if affected > MAX_ROWS:
                    raise ValueError("G12 append budget exceeded")
        if affected != MAX_ROWS:
            raise RuntimeError("G12 did not append the exact approved row count")
        await connection.commit()
        return {"status": "PASS", "mode": "APPLY", "rows_written": affected, "neo4j_writes": 0, "deletions": 0}
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, default=PROJECT_ROOT / "plans/g12-knowledge-review.json")
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--approved-plan-hash", default="")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    args = parser.parse_args(argv)
    report = asyncio.run(apply(args)) if args.apply else dry_run_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
