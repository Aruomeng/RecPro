#!/usr/bin/env python3
"""Forward-complete the exact partial G11 schema state without deleting it."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Sequence

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.execute_g11_identity_migration import (
    IAM_TABLES, IAM_VIEWS, MAXIMUM_ROWS, MIGRATION, MIGRATION_ID, PROJECT_ROOT,
    SCHEMA, SEED_ROWS, canonical, file_sha256, validate_migration_statements,
)
from scripts.validate_runtime_env import read_env


DEFAULT_PLAN = PROJECT_ROOT / "plans/g11-identity-access-successor.json"
REQUIRED_INPUT_PATHS = frozenset({
    "infra/mysql/migrations/009_g11_identity_access.sql",
    "scripts/build_g11_identity_successor_plan.py",
    "scripts/execute_g11_identity_successor.py",
})
_HASH = re.compile(r"^[0-9a-f]{64}$")


def reviewed_commit_is_ancestor(commit: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{40}", commit) is not None and subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=PROJECT_ROOT,
        capture_output=True,
    ).returncode == 0


def expected_fingerprint(database_identity: str, reviewed_commit: str) -> str:
    value = f"recpro_local_research_g11_successor:{database_identity}:{PROJECT_ROOT}:{reviewed_commit}"
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def completion_statements() -> tuple[str, ...]:
    statements = validate_migration_statements(MIGRATION.read_text(encoding="utf-8"))
    selected = statements[len(IAM_TABLES):]
    if len(selected) != len(IAM_VIEWS) + len(SEED_ROWS):
        raise ValueError("G11 successor statement set is not exact")
    for index, statement in enumerate(selected):
        compact = re.sub(r"--[^\n]*", " ", statement).strip()
        upper = re.sub(r"\s+", " ", compact).upper()
        if index < len(IAM_VIEWS):
            if not upper.startswith(f"CREATE VIEW {IAM_VIEWS[index].upper()} AS "):
                raise ValueError("G11 successor view order is invalid")
        elif not upper.startswith("INSERT IGNORE INTO "):
            raise ValueError("G11 successor seed statement is invalid")
        operation_text = re.sub(r"'(?:''|[^'])*'", "''", upper)
        if re.search(r"\b(DROP|DELETE|TRUNCATE|ALTER|RENAME|REPLACE|UPDATE)\b", operation_text):
            raise ValueError("G11 successor contains a forbidden operation")
    return selected


def dry_run_report() -> dict[str, object]:
    return {
        "status": "PASS", "mode": "NO_WRITE_SUCCESSOR_DRY_RUN",
        "required_existing_empty_tables": list(IAM_TABLES),
        "new_views": list(IAM_VIEWS), "seed_rows": dict(SEED_ROWS),
        "statement_count": len(completion_statements()), "maximum_rows": MAXIMUM_ROWS,
        "database_connections": 0, "database_writes": 0,
        "deepseek_requests": 0, "file_deletions": 0,
        "database_physical_deletions": 0,
    }


def validate_plan(path: Path, *, plan_id: str, approved_hash: str) -> dict[str, object]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")),format_checker=FormatChecker()).validate(plan)
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != approved_hash or _HASH.fullmatch(approved_hash) is None:
        raise ValueError("approved successor identity does not match")
    unsigned=dict(plan); unsigned.pop("plan_hash",None)
    if hashlib.sha256(canonical(unsigned)).hexdigest()!=approved_hash:
        raise ValueError("successor canonical hash does not match")
    commit=str(plan.get("git_commit",""))
    if not reviewed_commit_is_ancestor(commit): raise ValueError("successor commit is not an ancestor")
    if plan.get("classification")!="S1_APPEND" or plan.get("mode")!="APPLY" or plan.get("max_changes")!=MAXIMUM_ROWS:
        raise ValueError("successor budget is invalid")
    inputs=plan.get("input_hashes")
    if not isinstance(inputs,dict) or set(inputs)!=REQUIRED_INPUT_PATHS: raise ValueError("successor input set is invalid")
    for relative in REQUIRED_INPUT_PATHS:
        if inputs.get(relative)!=file_sha256(PROJECT_ROOT/relative): raise ValueError(f"successor input mismatch: {relative}")
    expected={*(f"recpro.{name}:schema" for name in IAM_VIEWS),"recpro.iam_role:fixed-role-seed","recpro.iam_permission:fixed-permission-seed","recpro.iam_role_permission_fact:fixed-grant-seed",f"recpro.recpro_schema_migration:migration_id={MIGRATION_ID}"}
    targets=plan.get("targets")
    if not isinstance(targets,list) or {str(t.get("identifier")) for t in targets if isinstance(t,dict)}!=expected:
        raise ValueError("successor target set is invalid")
    return plan


async def _object_count(connection: object, object_type: str, name: str) -> int:
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type=%s AND table_name=%s",(object_type,name)); return int((await cursor.fetchone())[0])


async def _row_count(connection: object, table: str) -> int:
    if table not in IAM_TABLES: raise ValueError("row count outside G11 allowlist")
    async with connection.cursor() as cursor:  # type: ignore[attr-defined]
        await cursor.execute(f"SELECT COUNT(*) FROM `{table}`"); return int((await cursor.fetchone())[0])


async def apply_plan(args: argparse.Namespace) -> dict[str, object]:
    plan=validate_plan(args.plan.resolve(strict=True),plan_id=args.plan_id,approved_hash=args.approved_plan_hash)
    values=read_env(args.env_file.resolve(strict=True)); port=values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT"); database=values.get("RECPRO_MYSQL_DATABASE",""); root=values.get("RECPRO_MYSQL_ROOT_PASSWORD","")
    if not port or not database or not root: raise ValueError("protected MySQL root credential is required for successor")
    identity=f"mysql://127.0.0.1:{port}/{database}"; environment=plan.get("environment")
    if not isinstance(environment,dict) or environment.get("database_identity")!=identity or environment.get("host_fingerprint")!=expected_fingerprint(identity,str(plan["git_commit"])): raise ValueError("successor environment mismatch")
    connection=await asyncmy.connect(host="127.0.0.1",port=int(port),user="root",password=root,db=database,autocommit=True)
    try:
        table_presence={name:await _object_count(connection,"BASE TABLE",name) for name in IAM_TABLES}; view_presence={name:await _object_count(connection,"VIEW",name) for name in IAM_VIEWS}; rows={name:await _row_count(connection,name) for name in IAM_TABLES}
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id=%s",(MIGRATION_ID,)); marker=int((await cursor.fetchone())[0])
        if marker==1 and all(table_presence.values()) and all(view_presence.values()):
            return {"status":"PASS","mode":"IDEMPOTENT_REPLAY","rows_written":0,"views_created":0}
        if not all(value==1 for value in table_presence.values()) or any(view_presence.values()) or any(rows.values()) or marker!=0:
            raise ValueError("database is not in the exact approved partial G11 state")
        affected=0
        async with connection.cursor() as cursor:
            for statement in completion_statements():
                await cursor.execute(statement)
                if statement.lstrip().upper().startswith("INSERT IGNORE INTO"):
                    affected+=max(0,int(cursor.rowcount))
                    if affected>MAXIMUM_ROWS: raise RuntimeError("successor exceeded row budget")
        views_after={name:await _object_count(connection,"VIEW",name) for name in IAM_VIEWS}
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) FROM iam_role WHERE role_id BETWEEN 1 AND 4"); roles=int((await cursor.fetchone())[0]); await cursor.execute("SELECT COUNT(*) FROM iam_permission WHERE permission_id BETWEEN 1 AND 15"); permissions=int((await cursor.fetchone())[0]); await cursor.execute("SELECT COUNT(*) FROM iam_role_permission_fact WHERE reason_code='G11_FIXED_SEED'"); grants=int((await cursor.fetchone())[0]); await cursor.execute("SELECT COUNT(*) FROM recpro_schema_migration WHERE migration_id=%s",(MIGRATION_ID,)); marker_after=int((await cursor.fetchone())[0])
        if not all(views_after.values()) or (roles,permissions,grants,marker_after)!=(4,15,17,1) or affected!=MAXIMUM_ROWS: raise RuntimeError("successor postflight reconciliation failed")
        return {"status":"PASS","mode":"APPLY","views_created":3,"rows_written":affected,"seed_counts":{"iam_role":roles,"iam_permission":permissions,"iam_role_permission_fact":grants,"recpro_schema_migration":marker_after},"deletions":0}
    finally: connection.close()


def main(argv: Sequence[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--apply",action="store_true"); parser.add_argument("--plan",type=Path,default=DEFAULT_PLAN); parser.add_argument("--plan-id",default=""); parser.add_argument("--approved-plan-hash",default=""); parser.add_argument("--env-file",type=Path,default=PROJECT_ROOT/".env.host"); args=parser.parse_args(argv)
    print(json.dumps(asyncio.run(apply_plan(args)) if args.apply else dry_run_report(),ensure_ascii=False,indent=2,sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
