#!/usr/bin/env python3
"""Resume G12 from the exact two-empty-table partial state without deletion."""

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
from scripts.execute_g12_knowledge_review_plan import (
    MAX_ROWS,
    MIGRATION,
    MIGRATION_ID,
    PROJECT_ROOT,
    PROPOSALS,
    PROPOSAL_ROWS,
    canonical,
    file_hash,
    statements,
)
from scripts.validate_runtime_env import read_env


SUCCESSOR_REQUIRED_INPUTS = frozenset({
    "backend/app/knowledge_review/domain.py",
    "backend/app/knowledge_review/loader.py",
    "infra/mysql/migrations/010_g12_knowledge_review.sql",
    "scripts/execute_g12_knowledge_review_plan.py",
    "scripts/execute_g12_knowledge_review_successor.py",
    "scripts/build_g12_knowledge_review_successor_plan.py",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/review-proposals.jsonl",
})
PERMISSION_CODE = "catalog.knowledge.review"
ROLE_FACT_KEYS = (
    "g12:role:librarian:catalog.knowledge.review:v1",
    "g12:role:research_admin:catalog.knowledge.review:v1",
)
DOCKER = Path("/Applications/编程/Docker.app/Contents/Resources/bin/docker")
MYSQL_CONTAINER = "recpro-g2-tianyuhang-20260809a-mysql-1"
MYSQL_IMAGE = "mysql:8.4.10@sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6"


def dry_run_report() -> dict[str, object]:
    proposals = load_v2_review_proposals(PROPOSALS)
    if len(proposals) != PROPOSAL_ROWS:
        raise ValueError("G12 proposal artifact count differs from the successor budget")
    approved = statements()
    if not approved[2].lstrip().upper().startswith("CREATE VIEW "):
        raise ValueError("G12 successor view statement is outside the allowlist")
    if any(not item.lstrip().upper().startswith("INSERT IGNORE ") for item in approved[3:]):
        raise ValueError("G12 successor insert statement is outside the allowlist")
    return {
        "schema_version": "g12-knowledge-review-successor-dry-run-v1",
        "status": "PASS",
        "mode": "NO_WRITE_DRY_RUN",
        "expected_existing_empty_tables": 2,
        "view_statements": 1,
        "permission_rows": 1,
        "role_permission_fact_rows": 2,
        "migration_marker_rows": 1,
        "proposal_rows": len(proposals),
        "action_fact_rows": 0,
        "maximum_rows": MAX_ROWS,
        "database_connections": 0,
        "database_writes": 0,
        "privilege_grants": 0,
        "neo4j_writes": 0,
        "deepseek_requests": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
    }


def validate_plan(path: Path, *, plan_id: str, approved_hash: str) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != approved_hash:
        raise ValueError("approved G12 successor identity does not match")
    if re.fullmatch(r"[0-9a-f]{64}", approved_hash) is None:
        raise ValueError("approved G12 successor hash is malformed")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("G12 successor canonical hash does not match")
    reviewed_commit = str(plan.get("git_commit", ""))
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", reviewed_commit, "HEAD"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    ).returncode != 0:
        raise ValueError("reviewed G12 successor commit is not an ancestor")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != SUCCESSOR_REQUIRED_INPUTS:
        raise ValueError("G12 successor input hash set is incomplete")
    for relative, digest in inputs.items():
        candidate = (PROJECT_ROOT / relative).resolve(strict=True)
        if not candidate.is_relative_to(PROJECT_ROOT) or file_hash(candidate) != digest:
            raise ValueError("G12 successor approved input hash mismatch")
    if plan.get("max_changes") != MAX_ROWS:
        raise ValueError("G12 successor row budget does not match")
    return plan


async def _object_type(connection: Any, name: str) -> str:
    if name not in {
        "knowledge_review_proposal",
        "knowledge_review_action_fact",
        "knowledge_review_current_v",
    }:
        raise ValueError("G12 successor schema lookup is outside the allowlist")
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema=DATABASE() AND table_name=%s",
            (name,),
        )
        row = await cursor.fetchone()
    return str(row[0]) if row else "ABSENT"


async def _scalar(connection: Any, query: str, params: tuple[object, ...] = ()) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute(query, params)
        row = await cursor.fetchone()
    return int(row[0])


async def _assert_partial_state(connection: Any) -> None:
    if await _object_type(connection, "knowledge_review_proposal") != "BASE TABLE":
        raise ValueError("G12 successor expected the proposal table to exist")
    if await _object_type(connection, "knowledge_review_action_fact") != "BASE TABLE":
        raise ValueError("G12 successor expected the action table to exist")
    if await _object_type(connection, "knowledge_review_current_v") != "ABSENT":
        raise ValueError("G12 successor expected the current-state view to be absent")
    checks = (
        await _scalar(connection, "SELECT COUNT(*) FROM knowledge_review_proposal"),
        await _scalar(connection, "SELECT COUNT(*) FROM knowledge_review_action_fact"),
        await _scalar(connection, "SELECT COUNT(*) FROM iam_permission WHERE permission_code=%s", (PERMISSION_CODE,)),
        await _scalar(connection, "SELECT COUNT(*) FROM iam_role_permission_fact WHERE idempotency_key IN (%s,%s)", ROLE_FACT_KEYS),
        await _scalar(connection, "SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id=%s", (MIGRATION_ID,)),
    )
    if checks != (0, 0, 0, 0, 0):
        raise ValueError("G12 successor partial-state counts do not match the approved zero baseline")


def _create_view_with_container_admin(statement: str) -> None:
    compact = re.sub(r"\s+", " ", statement.strip()).upper()
    if not compact.startswith("CREATE VIEW KNOWLEDGE_REVIEW_CURRENT_V AS "):
        raise ValueError("G12 successor admin statement is outside the CREATE VIEW allowlist")
    if re.search(r"\b(GRANT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|RENAME|REPLACE)\b", compact):
        raise ValueError("G12 successor admin statement contains a forbidden capability")
    inspected = subprocess.run(
        [str(DOCKER), "inspect", "--format", "{{.State.Running}}|{{.Config.Image}}", MYSQL_CONTAINER],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if inspected.returncode != 0 or inspected.stdout.strip() != f"true|{MYSQL_IMAGE}":
        raise ValueError("G12 successor MySQL container identity is not approved")
    executed = subprocess.run(
        [
            str(DOCKER), "exec", "-i", MYSQL_CONTAINER, "sh", "-c",
            'exec mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" recpro',
        ],
        cwd=PROJECT_ROOT,
        input=statement + ";\n",
        check=False,
        capture_output=True,
        text=True,
    )
    if executed.returncode != 0:
        raise RuntimeError("G12 successor container-local CREATE VIEW failed")


async def apply(args: argparse.Namespace) -> dict[str, object]:
    plan = validate_plan(
        args.plan.resolve(strict=True),
        plan_id=args.plan_id,
        approved_hash=args.approved_plan_hash,
    )
    proposals = load_v2_review_proposals(PROPOSALS)
    if len(proposals) != PROPOSAL_ROWS:
        raise ValueError("G12 proposal artifact count differs from the approved successor budget")
    approved = statements()
    runtime = read_env(args.env_file.resolve(strict=True))
    port = runtime.get("RECPRO_MYSQL_HOST_PORT") or runtime.get("RECPRO_MYSQL_PORT", "")
    database = runtime.get("RECPRO_MYSQL_DATABASE", "")
    identity = f"mysql://127.0.0.1:{port}/{database}"
    if not port or not database or plan.get("database_identity") != identity:
        raise ValueError("G12 successor database identity is not approved")
    migration_user = runtime.get("RECPRO_MYSQL_MIGRATION_USER", "")
    migration_password = runtime.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not all((migration_user, migration_password)):
        raise ValueError("G12 successor requires the configured migration identity")
    migration = await asyncmy.connect(
        host="127.0.0.1", port=int(port), user=migration_user,
        password=migration_password, db=database, autocommit=False,
    )
    try:
        await _assert_partial_state(migration)
        _create_view_with_container_admin(approved[2])
        if await _object_type(migration, "knowledge_review_current_v") != "VIEW":
            raise RuntimeError("G12 successor view was not created")
        affected = 0
        async with migration.cursor() as cursor:
            for statement in approved[3:]:
                await cursor.execute(statement)
                affected += max(0, int(cursor.rowcount))
            for proposal in proposals:
                await cursor.execute(
                    "INSERT IGNORE INTO knowledge_review_proposal "
                    "(proposal_uuid,proposal_type,graph_version,subject_id,relation_type,object_id,"
                    "source_refs_json,reason_codes_json,confidence,agent_name,task_id,workspace_id,"
                    "idempotency_sha256,occurred_at,created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        str(proposal.proposal_uuid), proposal.proposal_type,
                        proposal.graph_version, proposal.subject_id, proposal.relation_type,
                        proposal.object_id, json.dumps(proposal.source_refs, ensure_ascii=False),
                        json.dumps(proposal.reason_codes, ensure_ascii=False), proposal.confidence,
                        proposal.agent_name, None, None, proposal.idempotency_sha256,
                        proposal.occurred_at.replace(tzinfo=None),
                        proposal.occurred_at.replace(tzinfo=None),
                    ),
                )
                affected += max(0, int(cursor.rowcount))
                if affected > MAX_ROWS:
                    raise ValueError("G12 successor append budget exceeded")
        if affected != MAX_ROWS:
            raise RuntimeError("G12 successor did not append the exact approved row count")
        await migration.commit()
        after = {
            "proposal_rows": await _scalar(migration, "SELECT COUNT(*) FROM knowledge_review_proposal"),
            "action_fact_rows": await _scalar(migration, "SELECT COUNT(*) FROM knowledge_review_action_fact"),
            "permission_rows": await _scalar(migration, "SELECT COUNT(*) FROM iam_permission WHERE permission_code=%s", (PERMISSION_CODE,)),
            "role_permission_fact_rows": await _scalar(migration, "SELECT COUNT(*) FROM iam_role_permission_fact WHERE idempotency_key IN (%s,%s)", ROLE_FACT_KEYS),
            "migration_marker_rows": await _scalar(migration, "SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id=%s", (MIGRATION_ID,)),
        }
        if after != {
            "proposal_rows": 262,
            "action_fact_rows": 0,
            "permission_rows": 1,
            "role_permission_fact_rows": 2,
            "migration_marker_rows": 1,
        }:
            raise RuntimeError("G12 successor postflight counts do not match")
        return {
            "status": "PASS",
            "mode": "APPLY_SUCCESSOR",
            "plan_id": args.plan_id,
            "plan_hash": args.approved_plan_hash,
            "rows_written": affected,
            "view_created": 1,
            "privilege_grants": 0,
            "neo4j_writes": 0,
            "deepseek_requests": 0,
            "database_physical_deletions": 0,
            "counts": after,
        }
    except Exception:
        await migration.rollback()
        raise
    finally:
        migration.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, default=PROJECT_ROOT / "plans/g12-knowledge-review-successor.json")
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--approved-plan-hash", default="")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    args = parser.parse_args(argv)
    report = asyncio.run(apply(args)) if args.apply else dry_run_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
