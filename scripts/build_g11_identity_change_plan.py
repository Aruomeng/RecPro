#!/usr/bin/env python3
"""Build the exact, zero-connection G11 identity schema ChangePlan.

The builder hashes only committed runtime inputs. It never reads credentials,
opens a database connection, creates an account, or invokes an external model.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import subprocess
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from scripts.execute_g11_identity_migration import (
    IAM_TABLES,
    IAM_VIEWS,
    MAXIMUM_ROWS,
    MIGRATION_ID,
    PROJECT_ROOT,
    REQUIRED_INPUT_PATHS,
    SCHEMA,
    canonical,
    expected_host_fingerprint,
    file_sha256,
)


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def build_plan(
    *, reviewed_commit: str, created_at: str,
    database_identity: str = "mysql://127.0.0.1:62306/recpro",
) -> dict[str, object]:
    if COMMIT_PATTERN.fullmatch(reviewed_commit) is None:
        raise ValueError("reviewed commit must be a full lowercase Git SHA")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must include an explicit timezone")
    if not re.fullmatch(r"mysql://127\.0\.0\.1:[0-9]{1,5}/recpro", database_identity):
        raise ValueError("database identity is outside the local G11 allowlist")

    inputs = {
        relative: file_sha256(PROJECT_ROOT / relative)
        for relative in sorted(REQUIRED_INPUT_PATHS)
    }
    targets = [
        {
            "kind": "MYSQL", "identifier": f"recpro.{name}:schema",
            "operation": "CREATE", "expected_before_count": 0,
            "expected_after_min_count": 1,
        }
        for name in (*IAM_TABLES, *IAM_VIEWS)
    ]
    targets.extend([
        {
            "kind": "MYSQL", "identifier": "recpro.iam_role:fixed-role-seed",
            "operation": "APPEND", "expected_before_count": 0,
            "expected_after_min_count": 4,
        },
        {
            "kind": "MYSQL", "identifier": "recpro.iam_permission:fixed-permission-seed",
            "operation": "APPEND", "expected_before_count": 0,
            "expected_after_min_count": 15,
        },
        {
            "kind": "MYSQL", "identifier": "recpro.iam_role_permission_fact:fixed-grant-seed",
            "operation": "APPEND", "expected_before_count": 0,
            "expected_after_min_count": 17,
        },
        {
            "kind": "MYSQL",
            "identifier": f"recpro.recpro_schema_migration:migration_id={MIGRATION_ID}",
            "operation": "APPEND", "expected_before_count": 0,
            "expected_after_min_count": 1,
        },
    ])
    plan_id = str(uuid5(NAMESPACE_URL, f"recpro:g11-identity-access:{reviewed_commit}"))
    plan: dict[str, object] = {
        "schema_version": "1.0.0",
        "plan_id": plan_id,
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S1_APPEND",
        "mode": "APPLY",
        "intent": (
            "Create exactly 12 new IAM tables and 3 read-only effective-state views, then append "
            "the four fixed roles, 15 fixed permissions, 17 initial role-permission grant facts, "
            "and one migration marker. No user account, credential, session, consent, behavior, "
            "recommendation, graph, vector, or model fact is created by this plan."
        ),
        "environment": {
            "environment_id": "recpro_local_research_g11",
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": expected_host_fingerprint(
                database_identity=database_identity, reviewed_commit=reviewed_commit,
            ),
            "database_identity": database_identity,
            "index_namespace": None,
        },
        "targets": targets,
        "input_hashes": inputs,
        "idempotency_key": f"g11-identity-schema-{reviewed_commit[:12]}",
        "max_changes": MAXIMUM_ROWS,
        "preconditions": [
            f"reviewed identity implementation commit is exactly {reviewed_commit} and remains an ancestor of the execution revision",
            "the user separately approves this unchanged plan_id and canonical plan_hash before the executor opens any database connection",
            "the target is exactly the local recpro MySQL database named by environment.database_identity",
            "all 12 IAM tables, all 3 effective-state views, and the G11 migration marker are absent before the first statement; any partial schema fails closed",
            "all identity domain, MySQL adapter, password/JWT security, migration, builder, and executor input hashes match",
            "the executor accepts only CREATE TABLE, CREATE VIEW, and fixed INSERT IGNORE statements; UPDATE, DELETE, DROP, TRUNCATE, ALTER, RENAME, REPLACE, and cascading foreign keys are rejected",
            "the maximum appended row budget is exactly 37: 4 roles, 15 permissions, 17 role-permission facts, and 1 migration marker",
            "bootstrap administrator rows, real reader rows, security events, consents, sessions, refresh tokens, and action tokens are exactly 0",
            "DeepSeek and all external model requests, Neo4j writes, Chroma writes, container changes, volume changes, and file deletions are exactly 0",
            "failure recovery is fail-forward only: retain any implicitly committed schema, keep the identity composition disabled, and report the partial state; never compensate by deleting objects or rows",
        ],
        "safety_assertions": {
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "overwrite_existing": False,
            "destructive_capabilities_required": False,
            "counts_must_not_decrease": True,
        },
    }
    plan["plan_hash"] = hashlib.sha256(canonical(plan)).hexdigest()
    Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    ).validate(plan)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-commit", default=None)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--database-identity", default="mysql://127.0.0.1:62306/recpro")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(
            reviewed_commit=args.reviewed_commit or git_commit(),
            created_at=args.created_at, database_identity=args.database_identity,
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=False))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
