#!/usr/bin/env python3
"""Build the exact controlled-update plan for initial administrator activation."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.execute_g11_admin_activation import (
    BOOTSTRAP_USER_ID, DEFAULT_CREDENTIAL_FILE, DEFAULT_PLAN, MAXIMUM_CHANGES,
    REQUIRED_INPUT_PATHS, SCHEMA, ActivationMaterial,
    activation_material_from_files, expected_fingerprint, expected_targets,
)
from scripts.execute_g11_bootstrap_admin import DEFAULT_ENV_FILE, DEFAULT_MATERIAL_FILE
from scripts.execute_g11_identity_migration import canonical, file_sha256


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def build_plan(
    *, reviewed_commit: str, created_at: str, material: ActivationMaterial,
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
    operations = expected_targets(material)
    targets = [
        {
            "kind": "MYSQL", "identifier": identifier,
            "operation": operations[identifier], "expected_before_count": 0,
            "expected_after_min_count": 1,
        }
        for identifier in sorted(operations)
    ]
    plan: dict[str, object] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(
            NAMESPACE_URL,
            f"recpro:g11-admin-activation:{reviewed_commit}:{material.event_uuid}",
        )),
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S2_CONTROLLED_UPDATE",
        "mode": "APPLY",
        "intent": (
            "Activate the approved initial administrator in one transaction by inserting one "
            "frozen Argon2id password credential, consuming the existing one-time activation "
            "token, changing only the account status/authentication version fields, and appending "
            "one deterministic security event. The raw login identifier and password remain only "
            "in a Git-ignored chmod 0600 local credential file and are never printed."
        ),
        "environment": {
            "environment_id": "recpro_local_research_g11_admin_activation",
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
        "idempotency_key": f"g11-admin-activation-{material.event_uuid}",
        "max_changes": MAXIMUM_CHANGES,
        "preconditions": [
            f"reviewed administrator activation implementation commit is exactly {reviewed_commit} and remains an ancestor of execution",
            "the user separately approves this unchanged activation plan_id and canonical plan_hash before any database connection",
            "user 10000 exactly matches the approved bootstrap account, is PENDING_ACTIVATION, has auth_version 1 and role_version 3, and has no password credential",
            "the deterministic activation token matches its protected HMAC digest, is unconsumed, unrevoked, and unexpired",
            "the random login password and its frozen Argon2id-v1 PHC string match and exist only in a Git-ignored chmod 0600 local file",
            "execution uses only recpro_identity and one InnoDB transaction with row locks; any partial or changed state fails closed",
            "allowed mutations are exactly one credential INSERT, one activation-token status UPDATE, one account security-state UPDATE, and one security-event INSERT",
            "the account UPDATE changes status to ACTIVE, must_change_password to false, auth_version from 1 to 2, and updated_at only",
            "no login is performed by this plan, so new sessions, refresh tokens, login events, and last_login_at changes are 0",
            "DeepSeek requests, recommendation/behavior/profile facts, consent facts, Neo4j/Chroma writes, file deletions, physical database deletions, and container/volume changes are 0",
            "an exact complete activated state is accepted only as a zero-change idempotent replay; all other states require a forward-only successor plan",
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
    parser.add_argument("--bootstrap-file", type=Path, default=DEFAULT_MATERIAL_FILE)
    parser.add_argument("--credential-file", type=Path, default=DEFAULT_CREDENTIAL_FILE)
    args = parser.parse_args(argv)
    _, material = activation_material_from_files(
        args.env_file, args.bootstrap_file, args.credential_file,
    )
    print(json.dumps(build_plan(
        reviewed_commit=args.reviewed_commit or git_commit(),
        created_at=args.created_at, material=material,
        database_identity=args.database_identity,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
