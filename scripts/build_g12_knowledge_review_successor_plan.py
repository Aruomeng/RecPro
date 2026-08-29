#!/usr/bin/env python3
"""Build a zero-connection G12 fail-forward successor ChangePlan."""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import re
import subprocess
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from scripts.execute_g12_knowledge_review_plan import MAX_ROWS, PROJECT_ROOT, canonical, file_hash
from scripts.execute_g12_knowledge_review_successor import SUCCESSOR_REQUIRED_INPUTS, dry_run_report


def build_plan(*, reviewed_commit: str, created_at: str, database_identity: str) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{40}", reviewed_commit) is None:
        raise ValueError("reviewed commit is invalid")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None or re.fullmatch(r"mysql://127\.0\.0\.1:[0-9]{1,5}/recpro", database_identity) is None:
        raise ValueError("G12 successor time or database identity is invalid")
    plan: dict[str, object] = {
        "schema_version": "recpro-g12-knowledge-review-successor-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"recpro:g12-successor:{reviewed_commit}:{file_hash(PROJECT_ROOT / 'scripts/execute_g12_knowledge_review_successor.py')}")),
        "created_at": parsed.isoformat(),
        "git_commit": reviewed_commit,
        "classification": "S1_APPEND",
        "mode": "APPLY",
        "database_identity": database_identity,
        "intent": "Resume from the exact G12 partial state: retain two existing empty append-only tables, create only the missing read-only view with the configured admin identity, then append one permission, two role grants, one migration marker, and exactly 262 proposals with the migration identity. No GRANT statement, action fact, update, overwrite, or deletion is allowed.",
        "partial_state": {
            "knowledge_review_proposal": {"object": "BASE TABLE", "rows": 0},
            "knowledge_review_action_fact": {"object": "BASE TABLE", "rows": 0},
            "knowledge_review_current_v": {"object": "ABSENT"},
            "permission_rows": 0,
            "role_permission_fact_rows": 0,
            "migration_marker_rows": 0,
        },
        "targets": [
            {"kind": "MYSQL", "identifier": "recpro.knowledge_review_current_v", "operation": "CREATE", "rows": 0},
            {"kind": "MYSQL", "identifier": "recpro.knowledge_review_proposal", "operation": "APPEND", "rows": 262},
            {"kind": "MYSQL", "identifier": "recpro.iam_permission:catalog.knowledge.review", "operation": "APPEND", "rows": 1},
            {"kind": "MYSQL", "identifier": "recpro.iam_role_permission_fact:g12", "operation": "APPEND", "rows": 2},
            {"kind": "MYSQL", "identifier": "recpro.recpro_schema_migration:g12", "operation": "APPEND", "rows": 1},
        ],
        "input_hashes": {
            relative: file_hash(PROJECT_ROOT / relative)
            for relative in sorted(SUCCESSOR_REQUIRED_INPUTS)
        },
        "max_changes": MAX_ROWS,
        "dry_run": dry_run_report(),
        "preconditions": [
            "user approves this exact successor plan_id and plan_hash before any database connection",
            "the two G12 tables exist with zero rows; the view, permission, role facts, marker, and proposals are absent",
            "the configured admin identity executes exactly one CREATE VIEW statement and no GRANT statement",
            "the migration identity executes only three fixed INSERT IGNORE seeds and 262 bounded proposal INSERT IGNORE statements",
            "failure recovery remains forward-only; no table, view, fact, permission, or proposal is removed",
        ],
        "safety": {
            "database_deletions": 0,
            "file_deletions": 0,
            "neo4j_writes": 0,
            "deepseek_requests": 0,
            "privilege_grants": 0,
            "action_fact_rows": 0,
            "existing_table_replacements": 0,
        },
    }
    plan["plan_hash"] = sha256(canonical(plan)).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-commit")
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--database-identity", default="mysql://127.0.0.1:62306/recpro")
    args = parser.parse_args(argv)
    commit = args.reviewed_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    print(json.dumps(build_plan(
        reviewed_commit=commit,
        created_at=args.created_at,
        database_identity=args.database_identity,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
