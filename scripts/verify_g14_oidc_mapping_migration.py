#!/usr/bin/env python3
"""Statically verify the forward-only OIDC identity-binding migration.

This is deliberately a no-connection intake check.  It neither constructs an
OIDC client nor opens MySQL; the approved apply executor and a real issuer are
separate future inputs.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = PROJECT_ROOT / "infra/mysql/migrations/011_g14_oidc_identity_binding.sql"
MIGRATION_ID = "g14-oidc-identity-binding-v1"


def validate_migration(source: str) -> tuple[str, ...]:
    statements = tuple(item.strip() for item in source.split(";") if item.strip())
    if len(statements) != 2:
        raise ValueError("G14 OIDC migration must contain exactly two statements")
    compact = tuple(re.sub(r"--[^\n]*", " ", item).strip() for item in statements)
    create, marker = (re.sub(r"\s+", " ", item).upper() for item in compact)
    if not create.startswith("CREATE TABLE IF NOT EXISTS IAM_OIDC_IDENTITY_BINDING "):
        raise ValueError("G14 OIDC migration has an unexpected schema operation")
    if not marker.startswith("INSERT IGNORE INTO RECPRO_SCHEMA_MIGRATION "):
        raise ValueError("G14 OIDC migration has an unexpected marker operation")
    for statement in (create, marker):
        if re.search(r"\b(DROP|TRUNCATE|ALTER|RENAME|REPLACE)\b|\bDELETE\s+FROM\b|^UPDATE\b", statement):
            raise ValueError("G14 OIDC migration contains a destructive operation")
    required = (
        "ISSUER_SHA256 BINARY(32)", "SUBJECT_HASH BINARY(32)",
        "ON DELETE RESTRICT ON UPDATE RESTRICT", "STATUS IN ('ACTIVE','DISABLED')",
    )
    if any(fragment not in create for fragment in required):
        raise ValueError("G14 OIDC migration is missing a security boundary")
    if any(fragment in create for fragment in ("SUBJECT VARCHAR", "TOKEN VARCHAR", "ROLE_CODE")):
        raise ValueError("G14 OIDC migration attempts to persist external identity claims")
    if MIGRATION_ID.upper() not in marker:
        raise ValueError("G14 OIDC migration marker identity is invalid")
    return compact


def dry_run_report() -> dict[str, object]:
    statements = validate_migration(MIGRATION.read_text(encoding="utf-8"))
    return {
        "schema_version": "g14-oidc-mapping-dry-run-v1",
        "status": "PASS",
        "mode": "NO_WRITE_DRY_RUN",
        "migration_id": MIGRATION_ID,
        "statement_count": len(statements),
        "new_tables": ["iam_oidc_identity_binding"],
        "new_indexes": ["uq_iam_oidc_identity_subject", "ix_iam_oidc_identity_user"],
        "binding_rows": 0,
        "migration_marker_rows": 1,
        "database_connections": 0,
        "database_writes": 0,
        "deepseek_requests": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        raise ValueError("G14 OIDC migration verifier accepts no runtime arguments")
    print(json.dumps(dry_run_report(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
