#!/usr/bin/env python3
"""Build the exact no-connection ChangePlan for the first local administrator."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import subprocess
from pathlib import Path
import sys
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.execute_g11_bootstrap_admin import (
    BOOTSTRAP_USER_ID, DEFAULT_ENV_FILE, DEFAULT_MATERIAL_FILE, DEFAULT_PLAN,
    DISPLAY_NAME, MAXIMUM_ROWS, REQUIRED_INPUT_PATHS, ROLE_IDS,
    SCHEMA, BootstrapMaterial, expected_fingerprint, expected_targets,
    material_from_files,
)
from scripts.execute_g11_identity_migration import canonical, file_sha256


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def build_plan(
    *, reviewed_commit: str, created_at: str, material: BootstrapMaterial,
    database_identity: str = "mysql://127.0.0.1:62306/recpro",
) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{40}", reviewed_commit) is None:
        raise ValueError("reviewed commit must be a full Git SHA")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if (
        parsed.tzinfo is None
        or re.fullmatch(r"mysql://127\.0\.0\.1:[0-9]{1,5}/recpro", database_identity) is None
    ):
        raise ValueError("timestamp or database identity is invalid")
    targets = [
        {
            "kind": "MYSQL", "identifier": identifier, "operation": "APPEND",
            "expected_before_count": 0, "expected_after_min_count": 1,
        }
        for identifier in sorted(expected_targets(material))
    ]
    plan: dict[str, object] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(
            NAMESPACE_URL,
            f"recpro:g11-bootstrap-admin:{reviewed_commit}:{material.account_uuid}:{material.token_uuid}",
        )),
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S1_APPEND",
        "mode": "APPLY",
        "intent": (
            f"Append exactly one pending-activation local human account named {DISPLAY_NAME}, "
            f"one hashed reader identifier, the {', '.join(ROLE_IDS)} role grants, one hashed "
            "24-hour activation token, and one public security event. The bootstrap resolves only "
            "the first-actor dependency and creates no password, session, consent, behavior, "
            "recommendation, model request, or destructive operation."
        ),
        "environment": {
            "environment_id": "recpro_local_research_g11_bootstrap_admin",
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": expected_fingerprint(
                database_identity, reviewed_commit, material,
            ),
            "database_identity": database_identity,
            "index_namespace": None,
        },
        "targets": targets,
        "input_hashes": {
            relative: file_sha256(PROJECT_ROOT / relative)
            for relative in sorted(REQUIRED_INPUT_PATHS)
        },
        "idempotency_key": f"g11-bootstrap-admin-{material.account_uuid}",
        "max_changes": MAXIMUM_ROWS,
        "preconditions": [
            f"reviewed bootstrap implementation commit is exactly {reviewed_commit} and remains an ancestor of execution",
            "the user separately approves this unchanged bootstrap plan_id and canonical plan_hash before any database connection",
            "all 12 G11 IAM tables, 3 effective-state views, 4 fixed roles, 15 permissions, and 17 fixed role-permission grants already reconcile",
            "iam_user_account contains exactly 0 rows and user_id 10000 plus every deterministic target UUID/hash are absent",
            "execution uses only the table-bounded recpro_identity principal and one InnoDB transaction; a partial pre-existing target fails closed",
            "the synthetic identifier and random activation code are stored only in a Git-ignored chmod 0600 local file; the database stores HMAC-SHA256 digests only",
            "the account starts PENDING_ACTIVATION with no password; the user must choose a 10-128 character password through the activation API",
            "the three interactive roles are explicitly granted; service_worker is excluded and no implicit role inheritance is used",
            "the activation token expires 24 hours after successful apply; raw credential material is never printed by the executor",
            "maximum appended rows are exactly 7; updates, deletes, drops, replaces, schema changes, DeepSeek calls, Neo4j/Chroma writes, file deletions, and container or volume changes are 0",
            "an exact complete prior state is accepted only as a zero-write idempotent replay; all other non-empty account states require a new successor plan",
        ],
        "safety_assertions": {
            "file_deletions": 0, "database_physical_deletions": 0,
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
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--reviewed-commit", default=None)
    parser.add_argument("--database-identity", default="mysql://127.0.0.1:62306/recpro")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--material-file", type=Path, default=DEFAULT_MATERIAL_FILE)
    args = parser.parse_args(argv)
    _, material = material_from_files(args.env_file, args.material_file)
    plan = build_plan(
        reviewed_commit=args.reviewed_commit or git_commit(),
        created_at=args.created_at, material=material,
        database_identity=args.database_identity,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
