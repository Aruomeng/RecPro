#!/usr/bin/env python3
"""Dry-run or exactly apply the forward-only G10 Workspace audit plan.

Dry-run is deterministic and does not read environment credentials, connect to
MySQL, call DeepSeek, or mutate any service.  Apply is unavailable without an
exact successor ChangePlan bound to this executor's committed revision.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Sequence
from uuid import UUID

import asyncmy

from backend.app.agent_workspace.adapters import MySQLAgentWorkspaceAuditAdapter
from backend.app.agent_workspace.audit import AgentWorkspaceAuditBuffer, DirectiveStateFact, WorkspaceEventFact
from scripts.migrate_g2 import split_statements
from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/008_g10_agent_workspace_audit.sql"
DEFAULT_PLAN = PROJECT_ROOT / "plans/agent-workspace-audit-successor.json"
WORKSPACE_ID = UUID("de6b0647-85f5-4e62-9be0-876dd9dd39e7")
SESSION_ID = UUID("57f4cc50-2593-4c0d-952f-060b251f8521")
USER_ID = 1001
OCCURRED_AT = "2026-08-20T05:00:00.000Z"
ALLOWED_TABLES = frozenset({"agent_workspace_event", "interaction_directive_fact", "recpro_schema_migration"})
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def validate_migration_statements(text: str) -> tuple[str, ...]:
    statements = tuple(split_statements(text))
    if len(statements) != 3:
        raise ValueError("G10 migration must contain exactly three statements")
    for statement in statements:
        compact = re.sub(r"--[^\n]*", " ", statement).strip()
        upper = re.sub(r"\s+", " ", compact).upper()
        if upper.startswith("CREATE TABLE IF NOT EXISTS AGENT_WORKSPACE_EVENT"):
            table = "agent_workspace_event"
        elif upper.startswith("CREATE TABLE IF NOT EXISTS INTERACTION_DIRECTIVE_FACT"):
            table = "interaction_directive_fact"
        elif upper.startswith("INSERT IGNORE INTO RECPRO_SCHEMA_MIGRATION"):
            table = "recpro_schema_migration"
        else:
            raise ValueError("migration statement is outside CREATE/INSERT allowlist")
        if table not in ALLOWED_TABLES or re.search(r"\b(UPDATE|DELETE|DROP|TRUNCATE|REPLACE|ALTER|RENAME)\b", upper):
            raise ValueError("migration contains a destructive or non-allowlisted operation")
    return statements


def build_acceptance_buffer() -> AgentWorkspaceAuditBuffer:
    """Replay the fixed public acceptance trace entirely in memory."""
    buffer = AgentWorkspaceAuditBuffer(enabled=True, max_facts=17, demo_user_id=USER_ID)
    event_types = (
        "WORKSPACE_CREATED", "OBSERVATION_ACCEPTED", "AGENT_STARTED", "AGENT_COMPLETED",
        "AGENT_STARTED", "AGENT_COMPLETED", "DIRECTIVE_PROPOSED", "DIRECTIVE_PROPOSED",
        "DIRECTIVE_PROPOSED", "DIRECTIVE_PROPOSED", "DIRECTIVE_ACTIONED",
    )
    for sequence, event_type in enumerate(event_types, start=1):
        buffer.capture_event(
            mode="demo", session_id=SESSION_ID, user_id=USER_ID,
            event={
                "schema_version": "agent-workspace-event-v1",
                "sequence": sequence,
                "event_type": event_type,
                "workspace_id": str(WORKSPACE_ID),
                "context_version": 2,
                "occurred_at": OCCURRED_AT,
                "reason_code": "G10_BOUNDED_ACCEPTANCE",
            },
        )
    directive_types = (
        "SHOW_GUIDANCE", "SET_EXPLANATION_DENSITY", "SET_PRIMARY_ENTRY", "SUGGEST_TOPICS"
    )
    first: dict[str, object] | None = None
    for index, directive_type in enumerate(directive_types, start=1):
        directive = {
            "directive_id": str(UUID(f"e9ab275f-b057-42ec-933a-e6a856bdc9{20 + index:02d}")),
            "directive_version": 1,
            "type": directive_type,
            "scope": "global" if index < 3 else "home",
            "behavior": "SUGGESTION",
            "payload": {"acceptance": "bounded-public-decision", "index": index},
            "reason_codes": ["G10_BOUNDED_ACCEPTANCE"],
            "evidence_refs": ["workspace:fixed-replay"],
            "confidence": 0.8,
            "created_at": OCCURRED_AT,
            "status": "PROPOSED",
        }
        first = first or directive
        buffer.capture_directive(
            mode="demo", workspace_id=WORKSPACE_ID, session_id=SESSION_ID,
            user_id=USER_ID, directive=directive,
        )
    assert first is not None
    buffer.capture_directive(
        mode="demo", workspace_id=WORKSPACE_ID, session_id=SESSION_ID,
        user_id=USER_ID, directive=first, state="ACCEPTED", occurred_at=OCCURRED_AT,
    )
    return buffer


def dry_run_report() -> dict[str, object]:
    statements = validate_migration_statements(MIGRATION.read_text(encoding="utf-8"))
    facts = build_acceptance_buffer().snapshot()
    events = [fact for fact in facts if isinstance(fact, WorkspaceEventFact)]
    directives = [fact for fact in facts if isinstance(fact, DirectiveStateFact)]
    return {
        "schema_version": "g10-agent-workspace-audit-dry-run-v1",
        "status": "PASS",
        "mode": "NO_WRITE_DRY_RUN",
        "workspace_id": str(WORKSPACE_ID),
        "session_id": str(SESSION_ID),
        "user_id": USER_ID,
        "migration_statement_count": len(statements),
        "workspace_event_facts": len(events),
        "directive_state_facts": len(directives),
        "migration_marker_rows": 1,
        "maximum_rows": len(events) + len(directives) + 1,
        "stable_fact_ids": len({str(fact.event_uuid if isinstance(fact, WorkspaceEventFact) else fact.fact_uuid) for fact in facts}),
        "database_connections": 0,
        "database_writes": 0,
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
    }


def validate_plan(path: Path, *, plan_id: str, approved_hash: str) -> dict[str, object]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if str(plan.get("plan_id")) != plan_id or str(plan.get("plan_hash")) != approved_hash:
        raise ValueError("approved plan identity does not match the plan file")
    if HASH_PATTERN.fullmatch(approved_hash) is None:
        raise ValueError("approved plan hash is malformed")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("ChangePlan canonical hash does not match")
    if plan.get("git_commit") != current_commit():
        raise ValueError("ChangePlan is not bound to the current executor commit")
    if plan.get("classification") != "S1_APPEND" or plan.get("max_changes") != 17:
        raise ValueError("ChangePlan operation or maximum change budget is invalid")
    if plan.get("input_hashes", {}).get(MIGRATION.relative_to(PROJECT_ROOT).as_posix()) != file_sha256(MIGRATION):
        raise ValueError("migration hash does not match ChangePlan")
    if any(target.get("operation") not in {"CREATE", "APPEND"} for target in plan.get("targets", [])):
        raise ValueError("ChangePlan contains a non-append operation")
    return plan


async def _table_exists(connection: object, table: str) -> int:
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
            (table,),
        )
        row = await cursor.fetchone()
    return int(row[0])


async def _workspace_count(connection: object, table: str) -> int:
    if table not in {"agent_workspace_event", "interaction_directive_fact"}:
        raise ValueError("count table is outside allowlist")
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id = %s", (str(WORKSPACE_ID),))
        row = await cursor.fetchone()
    return int(row[0])


async def apply_approved_plan(args: argparse.Namespace) -> dict[str, object]:
    plan = validate_plan(args.plan.resolve(strict=True), plan_id=args.plan_id, approved_hash=args.approved_plan_hash)
    statements = validate_migration_statements(MIGRATION.read_text(encoding="utf-8"))
    values = read_env(args.env_file.resolve(strict=True))
    if values.get("RECPRO_APP_ENV") != "demo":
        raise ValueError("G10 audit apply requires demo environment")
    user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not user or not password:
        raise ValueError("migration credentials are required")
    expected_identity = f"mysql://127.0.0.1:{values['RECPRO_MYSQL_HOST_PORT']}/{values['RECPRO_MYSQL_DATABASE']}"
    if plan["environment"].get("database_identity") != expected_identity:
        raise ValueError("database identity does not match approved plan")
    connection = await asyncmy.connect(
        host="127.0.0.1", port=int(values["RECPRO_MYSQL_HOST_PORT"]), user=user,
        password=password, db=values["RECPRO_MYSQL_DATABASE"], autocommit=False,
    )
    try:
        before_exists = {table: await _table_exists(connection, table) for table in ALLOWED_TABLES if table != "recpro_schema_migration"}
        if any(before_exists.values()):
            raise ValueError("audit tables already exist; successor plan expected an absent schema")
        async with connection.cursor() as cursor:
            for statement in statements:
                await cursor.execute(statement)
        await connection.commit()
        adapter = MySQLAgentWorkspaceAuditAdapter()
        facts = build_acceptance_buffer().snapshot()
        for fact in facts:
            await adapter.append(connection, fact)
        await connection.commit()
        after = {
            "agent_workspace_event": await _workspace_count(connection, "agent_workspace_event"),
            "interaction_directive_fact": await _workspace_count(connection, "interaction_directive_fact"),
        }
        if after != {"agent_workspace_event": 11, "interaction_directive_fact": 5}:
            raise RuntimeError("post-append reconciliation exceeded or missed the approved count")
        return {
            "status": "APPLIED", "plan_id": args.plan_id, "plan_hash": args.approved_plan_hash,
            "workspace_counts": after, "total_rows": 17, "deepseek_requests": 0,
            "database_physical_deletions": 0,
        }
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--plan-id")
    parser.add_argument("--approved-plan-hash")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.apply:
            if args.dry_run or not args.plan_id or not args.approved_plan_hash:
                raise ValueError("apply requires exact plan id/hash and cannot combine with dry-run")
            report = asyncio.run(apply_approved_plan(args))
        else:
            report = dry_run_report()
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

