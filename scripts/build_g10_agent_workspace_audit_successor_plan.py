#!/usr/bin/env python3
"""Build the exact successor ChangePlan for bounded G10 audit acceptance.

The builder only hashes committed implementation inputs and prints JSON.  It
does not inspect credentials, connect to a database, invoke DeepSeek, or write
an output file.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from scripts.execute_g10_agent_workspace_audit import PROJECT_ROOT, REQUIRED_INPUT_PATHS, canonical, file_sha256


SCHEMA = PROJECT_ROOT / "contracts/safety/change-plan.schema.json"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def build_plan(*, reviewed_commit: str, created_at: str) -> dict[str, object]:
    if COMMIT_PATTERN.fullmatch(reviewed_commit) is None:
        raise ValueError("reviewed commit must be a full lowercase Git SHA")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must include an explicit timezone")

    database_identity = "mysql://127.0.0.1:62306/recpro"
    environment_id = "recpro_local_research_g10"
    fingerprint_payload = (
        f"{environment_id}:{database_identity}:{PROJECT_ROOT}:{reviewed_commit}"
    ).encode()
    input_hashes = {
        relative_path: file_sha256(PROJECT_ROOT / relative_path)
        for relative_path in sorted(REQUIRED_INPUT_PATHS)
    }
    plan_id = str(uuid5(NAMESPACE_URL, f"recpro:g10-audit-successor:{reviewed_commit}"))
    plan: dict[str, object] = {
        "schema_version": "1.0.0",
        "plan_id": plan_id,
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S1_APPEND",
        "mode": "APPLY",
        "intent": (
            "Create only the two new append-only Agent Workspace audit tables, append the fixed "
            "demo acceptance trace (11 public workspace events and 5 directive state facts), and "
            "append one migration marker. No existing row is updated or removed; DeepSeek, Neo4j, "
            "Chroma, Outbox, container, volume, and file mutations are prohibited."
        ),
        "environment": {
            "environment_id": environment_id,
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": "sha256:" + hashlib.sha256(fingerprint_payload).hexdigest(),
            "database_identity": database_identity,
            "index_namespace": None,
        },
        "targets": [
            {
                "kind": "MYSQL", "identifier": "recpro.agent_workspace_event:schema",
                "operation": "CREATE", "expected_before_count": 0, "expected_after_min_count": 1,
            },
            {
                "kind": "MYSQL", "identifier": "recpro.interaction_directive_fact:schema",
                "operation": "CREATE", "expected_before_count": 0, "expected_after_min_count": 1,
            },
            {
                "kind": "MYSQL",
                "identifier": "recpro.recpro_schema_migration:migration_id=g10-agent-workspace-audit-v1",
                "operation": "APPEND", "expected_before_count": 0, "expected_after_min_count": 1,
            },
            {
                "kind": "MYSQL",
                "identifier": "recpro.agent_workspace_event:workspace_id=de6b0647-85f5-4e62-9be0-876dd9dd39e7",
                "operation": "APPEND", "expected_before_count": 0, "expected_after_min_count": 11,
            },
            {
                "kind": "MYSQL",
                "identifier": "recpro.interaction_directive_fact:workspace_id=de6b0647-85f5-4e62-9be0-876dd9dd39e7",
                "operation": "APPEND", "expected_before_count": 0, "expected_after_min_count": 5,
            },
        ],
        "input_hashes": input_hashes,
        "idempotency_key": f"g10-agent-workspace-audit-successor-{reviewed_commit[:12]}",
        "max_changes": 17,
        "preconditions": [
            f"reviewed implementation commit is exactly {reviewed_commit} and remains an ancestor of the execution revision",
            "the user separately approves this unchanged successor plan_id and canonical plan_hash before any database connection",
            "database identity and host fingerprint match; both audit tables and the migration marker are absent",
            "all seven migration, executor, reconciler, audit port, adapter, worker, and fact-model input hashes match",
            "executor accepts CREATE TABLE IF NOT EXISTS and INSERT IGNORE only; UPDATE, DELETE, DROP, TRUNCATE, REPLACE, ALTER, and RENAME are rejected",
            "demo user_id is exactly 1001; workspace_id is de6b0647-85f5-4e62-9be0-876dd9dd39e7; session_id is 57f4cc50-2593-4c0d-952f-060b251f8521",
            "DeepSeek request budget, external network requests, Neo4j writes, Chroma writes, Outbox claims, container changes, volume changes, and file deletions are exactly 0",
            "preflight verifies zero table/marker existence before the first statement and postflight reconciles exactly 11 event facts, 5 directive facts, and 1 marker",
            "rollback is fail-forward only: retain any created schema or appended immutable facts, disable the opt-in adapter, and report failure; no compensating removal is allowed",
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
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(plan)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-commit", default=None)
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(reviewed_commit=args.reviewed_commit or git_commit(), created_at=args.created_at)
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=False))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
