#!/usr/bin/env python3
"""Append the remaining G12 facts from the exact view-present partial state."""

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
    MAX_ROWS, MIGRATION_ID, PROJECT_ROOT, PROPOSALS, PROPOSAL_ROWS,
    canonical, file_hash, statements,
)
from scripts.execute_g12_knowledge_review_successor import (
    PERMISSION_CODE, ROLE_FACT_KEYS, _object_type, _scalar,
)
from scripts.validate_runtime_env import read_env


FINALIZER_REQUIRED_INPUTS = frozenset({
    "backend/app/knowledge_review/domain.py",
    "backend/app/knowledge_review/loader.py",
    "infra/mysql/migrations/010_g12_knowledge_review.sql",
    "scripts/execute_g12_knowledge_review_plan.py",
    "scripts/execute_g12_knowledge_review_finalizer.py",
    "scripts/build_g12_knowledge_review_finalizer_plan.py",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/review-proposals.jsonl",
})


def dry_run_report() -> dict[str, object]:
    proposals = load_v2_review_proposals(PROPOSALS)
    approved = statements()[3:]
    if len(proposals) != PROPOSAL_ROWS or any(
        not statement.lstrip().upper().startswith("INSERT IGNORE ")
        for statement in approved
    ):
        raise ValueError("G12 finalizer inputs are outside the fixed append allowlist")
    return {
        "schema_version": "g12-knowledge-review-finalizer-dry-run-v1",
        "status": "PASS", "mode": "NO_WRITE_DRY_RUN",
        "expected_existing_tables": 2, "expected_existing_views": 1,
        "permission_rows": 1, "role_permission_fact_rows": 2,
        "migration_marker_rows": 1, "proposal_rows": len(proposals),
        "action_fact_rows": 0, "maximum_rows": MAX_ROWS,
        "database_connections": 0, "database_writes": 0,
        "admin_operations": 0, "privilege_grants": 0,
        "neo4j_writes": 0, "deepseek_requests": 0,
        "file_deletions": 0, "database_physical_deletions": 0,
    }


def validate_plan(path: Path, *, plan_id: str, approved_hash: str) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != approved_hash:
        raise ValueError("approved G12 finalizer identity does not match")
    if re.fullmatch(r"[0-9a-f]{64}", approved_hash) is None:
        raise ValueError("approved G12 finalizer hash is malformed")
    unsigned = dict(plan); unsigned.pop("plan_hash", None)
    if sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("G12 finalizer canonical hash does not match")
    commit = str(plan.get("git_commit", ""))
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=PROJECT_ROOT, check=False, capture_output=True,
    ).returncode != 0:
        raise ValueError("reviewed G12 finalizer commit is not an ancestor")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != FINALIZER_REQUIRED_INPUTS:
        raise ValueError("G12 finalizer input hash set is incomplete")
    for relative, digest in inputs.items():
        candidate = (PROJECT_ROOT / relative).resolve(strict=True)
        if not candidate.is_relative_to(PROJECT_ROOT) or file_hash(candidate) != digest:
            raise ValueError("G12 finalizer approved input hash mismatch")
    if plan.get("max_changes") != MAX_ROWS:
        raise ValueError("G12 finalizer row budget does not match")
    return plan


async def _assert_finalizer_state(connection: Any) -> None:
    actual = (
        await _object_type(connection, "knowledge_review_proposal"),
        await _object_type(connection, "knowledge_review_action_fact"),
        await _object_type(connection, "knowledge_review_current_v"),
    )
    if actual != ("BASE TABLE", "BASE TABLE", "VIEW"):
        raise ValueError("G12 finalizer schema state does not match")
    counts = (
        await _scalar(connection, "SELECT COUNT(*) FROM knowledge_review_proposal"),
        await _scalar(connection, "SELECT COUNT(*) FROM knowledge_review_action_fact"),
        await _scalar(connection, "SELECT COUNT(*) FROM iam_permission WHERE permission_code=%s", (PERMISSION_CODE,)),
        await _scalar(connection, "SELECT COUNT(*) FROM iam_role_permission_fact WHERE idempotency_key IN (%s,%s)", ROLE_FACT_KEYS),
        await _scalar(connection, "SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id=%s", (MIGRATION_ID,)),
    )
    if counts != (0, 0, 0, 0, 0):
        raise ValueError("G12 finalizer row state does not match the zero baseline")


async def apply(args: argparse.Namespace) -> dict[str, object]:
    plan = validate_plan(args.plan.resolve(strict=True), plan_id=args.plan_id, approved_hash=args.approved_plan_hash)
    proposals = load_v2_review_proposals(PROPOSALS)
    if len(proposals) != PROPOSAL_ROWS:
        raise ValueError("G12 finalizer proposal count differs from the approved budget")
    values = read_env(args.env_file.resolve(strict=True))
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT", "")
    database = values.get("RECPRO_MYSQL_DATABASE", "")
    if plan.get("database_identity") != f"mysql://127.0.0.1:{port}/{database}":
        raise ValueError("G12 finalizer database identity is not approved")
    user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not all((port, database, user, password)):
        raise ValueError("G12 finalizer migration identity is not configured")
    connection = await asyncmy.connect(host="127.0.0.1", port=int(port), user=user, password=password, db=database, autocommit=False)
    try:
        await _assert_finalizer_state(connection)
        affected = 0
        async with connection.cursor() as cursor:
            for statement in statements()[3:]:
                await cursor.execute(statement); affected += max(0, int(cursor.rowcount))
            for proposal in proposals:
                await cursor.execute(
                    "INSERT IGNORE INTO knowledge_review_proposal "
                    "(proposal_uuid,proposal_type,graph_version,subject_id,relation_type,object_id,source_refs_json,reason_codes_json,confidence,agent_name,task_id,workspace_id,idempotency_sha256,occurred_at,created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (str(proposal.proposal_uuid), proposal.proposal_type, proposal.graph_version, proposal.subject_id, proposal.relation_type, proposal.object_id, json.dumps(proposal.source_refs, ensure_ascii=False), json.dumps(proposal.reason_codes, ensure_ascii=False), proposal.confidence, proposal.agent_name, None, None, proposal.idempotency_sha256, proposal.occurred_at.replace(tzinfo=None), proposal.occurred_at.replace(tzinfo=None)),
                )
                affected += max(0, int(cursor.rowcount))
                if affected > MAX_ROWS: raise ValueError("G12 finalizer append budget exceeded")
        if affected != MAX_ROWS: raise RuntimeError("G12 finalizer did not append exactly 266 rows")
        await connection.commit()
        counts = {
            "proposal_rows": await _scalar(connection, "SELECT COUNT(*) FROM knowledge_review_proposal"),
            "action_fact_rows": await _scalar(connection, "SELECT COUNT(*) FROM knowledge_review_action_fact"),
            "permission_rows": await _scalar(connection, "SELECT COUNT(*) FROM iam_permission WHERE permission_code=%s", (PERMISSION_CODE,)),
            "role_permission_fact_rows": await _scalar(connection, "SELECT COUNT(*) FROM iam_role_permission_fact WHERE idempotency_key IN (%s,%s)", ROLE_FACT_KEYS),
            "migration_marker_rows": await _scalar(connection, "SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id=%s", (MIGRATION_ID,)),
        }
        if counts != {"proposal_rows":262,"action_fact_rows":0,"permission_rows":1,"role_permission_fact_rows":2,"migration_marker_rows":1}:
            raise RuntimeError("G12 finalizer postflight counts do not match")
        return {"status":"PASS","mode":"APPLY_FINALIZER","plan_id":args.plan_id,"plan_hash":args.approved_plan_hash,"rows_written":affected,"admin_operations":0,"database_physical_deletions":0,"deepseek_requests":0,"neo4j_writes":0,"counts":counts}
    except Exception:
        await connection.rollback(); raise
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--plan",type=Path,default=PROJECT_ROOT/"plans/g12-knowledge-review-finalizer.json")
    parser.add_argument("--plan-id",default=""); parser.add_argument("--approved-plan-hash",default="")
    parser.add_argument("--env-file",type=Path,default=PROJECT_ROOT/".env.host")
    args=parser.parse_args(argv)
    print(json.dumps(asyncio.run(apply(args)) if args.apply else dry_run_report(),ensure_ascii=False,indent=2,sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
