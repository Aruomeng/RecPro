#!/usr/bin/env python3
"""Build the exact zero-connection G12 MySQL ChangePlan."""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import re
import subprocess
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from scripts.execute_g12_knowledge_review_plan import (
    MAX_ROWS, PROJECT_ROOT, REQUIRED_INPUTS, canonical, dry_run_report, file_hash,
)


def build_plan(*, reviewed_commit: str, created_at: str, database_identity: str) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{40}", reviewed_commit) is None:
        raise ValueError("reviewed commit is invalid")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None or re.fullmatch(r"mysql://127\.0\.0\.1:[0-9]{1,5}/recpro", database_identity) is None:
        raise ValueError("G12 plan time or database identity is invalid")
    dry = dry_run_report()
    plan: dict[str, object] = {
        "schema_version": "recpro-g12-knowledge-review-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"recpro:g12:{reviewed_commit}:{file_hash(PROJECT_ROOT / 'infra/mysql/migrations/010_g12_knowledge_review.sql')}")),
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S1_APPEND", "mode": "APPLY",
        "database_identity": database_identity,
        "intent": "Create two append-only knowledge review tables and one current-state view, append one permission, two role grants, one migration marker, and exactly 262 v2 review proposals. No action facts or Neo4j changes are included.",
        "targets": [
            {"kind": "MYSQL", "identifier": "recpro.knowledge_review_proposal", "operation": "CREATE_AND_APPEND", "rows": 262},
            {"kind": "MYSQL", "identifier": "recpro.knowledge_review_action_fact", "operation": "CREATE", "rows": 0},
            {"kind": "MYSQL", "identifier": "recpro.knowledge_review_current_v", "operation": "CREATE", "rows": 0},
            {"kind": "MYSQL", "identifier": "recpro.iam_permission:catalog.knowledge.review", "operation": "APPEND", "rows": 1},
            {"kind": "MYSQL", "identifier": "recpro.iam_role_permission_fact:g12", "operation": "APPEND", "rows": 2},
            {"kind": "MYSQL", "identifier": "recpro.recpro_schema_migration:g12", "operation": "APPEND", "rows": 1},
        ],
        "input_hashes": {relative: file_hash(PROJECT_ROOT / relative) for relative in sorted(REQUIRED_INPUTS)},
        "max_changes": MAX_ROWS,
        "dry_run": dry,
        "preconditions": [
            "user approves unchanged plan_id and plan_hash before any database connection",
            "both tables, the view, permission 16, G12 grants, marker, and all 262 proposals are absent",
            "only CREATE TABLE, CREATE VIEW, and INSERT IGNORE statements are accepted",
            "failure recovery is forward-only; no compensating deletion or schema removal",
        ],
        "safety": {"database_deletions": 0, "file_deletions": 0, "neo4j_writes": 0, "deepseek_requests": 0, "action_fact_rows": 0},
    }
    plan["plan_hash"] = sha256(canonical(plan)).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-commit")
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--database-identity", default="mysql://127.0.0.1:62306/recpro")
    args = parser.parse_args(argv)
    commit = args.reviewed_commit or subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    print(json.dumps(build_plan(reviewed_commit=commit, created_at=args.created_at, database_identity=args.database_identity), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
