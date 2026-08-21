#!/usr/bin/env python3
"""Build the zero-connection G11 least-privilege MySQL principal plan."""

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

from scripts.execute_g11_identity_principal import (
    DEFAULT_PLAN, IDENTITY_HOST, IDENTITY_USER, MAXIMUM_CHANGES, PROJECT_ROOT,
    REQUIRED_INPUT_PATHS, SCHEMA, TABLE_PRIVILEGES, canonical,
    expected_fingerprint, file_sha256,
)


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def build_plan(*, reviewed_commit: str, created_at: str, database_identity: str = "mysql://127.0.0.1:62306/recpro") -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{40}", reviewed_commit) is None:
        raise ValueError("reviewed commit must be a full Git SHA")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None or not re.fullmatch(r"mysql://127\.0\.0\.1:[0-9]{1,5}/recpro", database_identity):
        raise ValueError("timestamp or database identity is invalid")
    targets = [{"kind":"MYSQL","identifier":f"mysql-principal:{IDENTITY_USER}@{IDENTITY_HOST}","operation":"CREATE","expected_before_count":0,"expected_after_min_count":1}]
    targets.extend(
        {"kind":"MYSQL","identifier":f"recpro.{table}:{privilege}","operation":"APPEND","expected_before_count":0,"expected_after_min_count":1}
        for table, privileges in TABLE_PRIVILEGES.items() for privilege in privileges
    )
    plan: dict[str, object] = {
        "schema_version":"1.0.0",
        "plan_id":str(uuid5(NAMESPACE_URL, f"recpro:g11-identity-principal:{reviewed_commit}")),
        "created_at":parsed.isoformat().replace("+00:00","Z"),
        "git_commit":reviewed_commit,
        "classification":"S1_APPEND", "mode":"APPLY",
        "intent":"Create one dedicated recpro_identity MySQL login and grant only the exact table-level SELECT, INSERT, and UPDATE privileges required by the IAM adapter. Grant no schema, deletion, grant-option, graph, vector, model, or business-data capability.",
        "environment":{"environment_id":"recpro_local_research_g11_identity_principal","workspace":str(PROJECT_ROOT),"host_fingerprint":expected_fingerprint(database_identity,reviewed_commit),"database_identity":database_identity,"index_namespace":None},
        "targets":targets,
        "input_hashes":{relative:file_sha256(PROJECT_ROOT/relative) for relative in sorted(REQUIRED_INPUT_PATHS)},
        "idempotency_key":f"g11-identity-principal-{reviewed_commit[:12]}",
        "max_changes":MAXIMUM_CHANGES,
        "preconditions":[
            f"reviewed identity principal implementation commit is exactly {reviewed_commit} and remains an ancestor of execution",
            "the G11 identity schema plan has already completed and all 15 IAM tables/views exist",
            "the user separately approves this unchanged principal plan_id and canonical plan_hash before any database connection",
            "recpro_identity@% does not exist; an exact complete grant set is accepted only as a zero-change idempotent replay",
            "a root credential and a separately supplied 20+ character recpro_identity password exist only in the local protected environment file and are never printed",
            "allowed privileges are table-level SELECT, INSERT, and UPDATE only; DELETE, DROP, ALTER, CREATE, REFERENCES, INDEX, FILE, PROCESS, SUPER, and GRANT OPTION are forbidden",
            "business row writes, DeepSeek calls, Neo4j/Chroma writes, file deletions, container changes, and volume changes are exactly 0",
            "partial principal or grant state fails closed and requires a new forward-only successor plan; no principal or grant is removed automatically",
        ],
        "safety_assertions":{"file_deletions":0,"database_physical_deletions":0,"overwrite_existing":False,"destructive_capabilities_required":False,"counts_must_not_decrease":True},
    }
    plan["plan_hash"] = hashlib.sha256(canonical(plan)).hexdigest()
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")),format_checker=FormatChecker()).validate(plan)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--created-at",required=True); parser.add_argument("--reviewed-commit",default=None); parser.add_argument("--database-identity",default="mysql://127.0.0.1:62306/recpro"); args=parser.parse_args(argv)
    print(json.dumps(build_plan(reviewed_commit=args.reviewed_commit or git_commit(),created_at=args.created_at,database_identity=args.database_identity),ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
