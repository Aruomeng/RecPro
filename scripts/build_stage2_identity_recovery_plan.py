#!/usr/bin/env python3
"""Build a forward-only recovery plan for the interrupted Stage 2 run.

The original Stage 2 plan appended the reader account, credentials, consent
facts, and sessions before the stale workbench stopped at the profile route.
This builder freezes that observed partial state and authorizes only the
remaining profile write plus a fresh, bounded login/refresh/logout verification.
It never opens a database connection and never reuses the original plan.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = PROJECT_ROOT / "contracts/safety/change-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
DATABASE_IDENTITY_PATTERN = re.compile(r"^mysql://127\.0\.0\.1:[0-9]{1,5}/recpro$")
TEST_READER_ID = 10_001
TEST_READER_IDENTIFIER = "LIBRAMAS-STAGE2-READER-20260831"
TEST_READER_PROFILE = {
    "major": "图书馆学",
    "grade": "研究生",
    "research_direction": "多智能体推荐",
    "preferred_language": "zh-CN",
}

# This is the read-only state observed after the approved closure stopped at
# the stale-process 404.  It intentionally includes the already appended rows
# so a recovery executor cannot replay or overwrite them.
PARTIAL_BASELINE = {
    "iam_user_account": 2,
    "iam_login_identifier": 2,
    "iam_password_credential": 2,
    "iam_auth_session": 2,
    "iam_refresh_token": 2,
    "iam_action_token": 2,
    "iam_security_event": 6,
    "user_personalization_consent_fact": 5,
    "user_declared_profile": 2,
    "user_declared_profile_history": 2,
    "iam_permission": 16,
    "iam_role": 4,
    "iam_role_permission_fact": 19,
    "iam_user_role_fact": 4,
    "recommendation_task": 58,
    "user_behavior_event": 55,
}
EXPECTED_DELTAS = {
    "iam_auth_session": 2,
    "iam_refresh_token": 3,
    "iam_security_event": 4,
    "user_declared_profile": 1,
    "user_declared_profile_history": 1,
}
APPEND_ROWS = 11
CONTROLLED_UPDATE_OPERATIONS = 8
MAXIMUM_CHANGES = APPEND_ROWS + CONTROLLED_UPDATE_OPERATIONS

INPUT_PATHS = (
    "backend/app/api/identity.py",
    "backend/app/composition.py",
    "backend/app/config.py",
    "backend/app/identity/adapters/mysql.py",
    "backend/app/identity/application.py",
    "backend/app/identity/security.py",
    "scripts/build_stage2_identity_closure_plan.py",
    "scripts/execute_stage2_identity_closure.py",
    "scripts/build_stage2_identity_recovery_plan.py",
    "scripts/execute_stage2_identity_recovery.py",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("current Git commit must be a full SHA")
    return commit


def require_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        raise ValueError("working tree must be clean before freezing Stage 2 recovery")


def expected_fingerprint(database_identity: str, reviewed_commit: str, run_id: str) -> str:
    payload = (
        f"recpro_local_research_stage2_identity_recovery:{database_identity}:"
        f"{PROJECT_ROOT}:{reviewed_commit}:{run_id}"
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _target(
    identifier: str, operation: str, *, before: int = 0, after: int = 1,
    kind: str = "MYSQL",
) -> dict[str, object]:
    return {
        "kind": kind,
        "identifier": identifier,
        "operation": operation,
        "expected_before_count": before,
        "expected_after_min_count": after,
    }


def targets_for(run_id: str) -> list[dict[str, object]]:
    targets = [
        _target(".env.admin-login.local", "READ", before=1, after=1, kind="FILE"),
        _target(".env.stage2-reader-login.local", "READ", before=1, after=1, kind="FILE"),
        _target(
            f"recpro.iam_login_identifier:user_id={TEST_READER_ID}:identifier={TEST_READER_IDENTIFIER}",
            "READ", before=1, after=1,
        ),
        _target(
            f"artifacts/verification/stage2-identity-recovery/{run_id}/acceptance.json",
            "CREATE", kind="FILE",
        ),
        _target(f"recpro.iam_auth_session:stage2-recovery-admin:{run_id}", "APPEND"),
        _target(f"recpro.iam_auth_session:stage2-recovery-reader:{run_id}", "APPEND"),
        _target(f"recpro.iam_refresh_token:stage2-recovery-admin:{run_id}", "APPEND"),
        _target(f"recpro.iam_refresh_token:stage2-recovery-reader:{run_id}", "APPEND"),
        _target(f"recpro.iam_refresh_token:stage2-recovery-reader-rotation:{run_id}", "APPEND"),
        _target(f"recpro.iam_security_event:stage2-recovery-admin-login:{run_id}", "APPEND"),
        _target(f"recpro.iam_security_event:stage2-recovery-reader-login:{run_id}", "APPEND"),
        _target(f"recpro.iam_security_event:stage2-recovery-reader-logout:{run_id}", "APPEND"),
        _target(f"recpro.iam_security_event:stage2-recovery-admin-logout:{run_id}", "APPEND"),
        _target(f"recpro.user_declared_profile_history:user_id={TEST_READER_ID}:version=1", "APPEND"),
        _target(f"recpro.user_declared_profile:user_id={TEST_READER_ID}:version=1", "APPEND"),
        _target(f"recpro.iam_user_account:user_id={10000}:last_login", "UPDATE_STATUS"),
        _target(f"recpro.iam_user_account:user_id={TEST_READER_ID}:last_login", "UPDATE_STATUS"),
        _target(f"recpro.iam_refresh_token:stage2-recovery-reader-initial:{run_id}:consume", "UPDATE_STATUS"),
        _target(f"recpro.iam_auth_session:stage2-recovery-reader:{run_id}:last_seen", "UPDATE_STATUS"),
        _target(f"recpro.iam_auth_session:stage2-recovery-reader:{run_id}:revoke", "UPDATE_STATUS"),
        _target(f"recpro.iam_refresh_token:stage2-recovery-reader:{run_id}:revoke", "UPDATE_STATUS"),
        _target(f"recpro.iam_auth_session:stage2-recovery-admin:{run_id}:revoke", "UPDATE_STATUS"),
        _target(f"recpro.iam_refresh_token:stage2-recovery-admin:{run_id}:revoke", "UPDATE_STATUS"),
    ]
    return targets


def build_plan(*, run_id: str, created_at: str, database_identity: str) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run_id must use lowercase letters, digits, and hyphens")
    if DATABASE_IDENTITY_PATTERN.fullmatch(database_identity) is None:
        raise ValueError("database identity is outside the fixed local target")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must contain a timezone")
    require_clean_worktree()
    commit = current_commit()
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(
            NAMESPACE_URL, f"recpro:stage2-identity-recovery:{commit}:{run_id}",
        )),
        "created_at": parsed.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S2_CONTROLLED_UPDATE",
        "mode": "APPLY",
        "intent": (
            "Complete the already partially appended synthetic Stage 2 reader "
            "10001 without replaying or overwriting prior facts: append one declared "
            "profile version, perform one fresh admin/reader login pair, rotate the "
            "reader refresh token, and log out only the two fresh verification sessions. "
            "The original interrupted sessions remain retained; no deletion or direct "
            "database repair is permitted."
        ),
        "environment": {
            "environment_id": "recpro_local_research_stage2_identity_recovery",
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": expected_fingerprint(database_identity, commit, run_id),
            "database_identity": database_identity,
            "index_namespace": None,
        },
        "targets": targets_for(run_id),
        "input_hashes": {
            relative: file_sha256(PROJECT_ROOT / relative)
            for relative in sorted(INPUT_PATHS)
        },
        "idempotency_key": f"stage2-identity-recovery-{run_id}",
        "request_run_id": run_id,
        "max_changes": MAXIMUM_CHANGES,
        "preconditions": [
            f"reviewed commit is exactly {commit} or a descendant preserving every input hash",
            "the user separately approves this exact recovery plan_id and plan_hash before a database connection that can write",
            f"MySQL target is exactly {database_identity}; the observed partial baseline is {json.dumps(PARTIAL_BASELINE, sort_keys=True)}",
            f"reader identifier {TEST_READER_IDENTIFIER} maps only to active synthetic user {TEST_READER_ID} with one credential, four effective consent facts, and no declared profile",
            "the original reader credential file exists with mode 0600 and is read without printing or overwriting its values",
            "the explicit local G4 identity API is running current code at http://127.0.0.1:8000 and readiness is checked before any POST or PUT",
            "the executor performs only fresh login, profile update, refresh rotation, and two matching logouts; it never attempts to replay the interrupted sessions",
            f"only {APPEND_ROWS} append rows and {CONTROLLED_UPDATE_OPERATIONS} allowlisted current-state updates are permitted; max_changes={MAXIMUM_CHANGES}",
            "recommendation, feedback, behavior, Agent Workspace audit, Neo4j, Chroma, and DeepSeek request counts remain exactly 0",
            "a partial recovery failure is retained for inspection and requires another forward-only plan; no destructive schema/data operation, overwrite, container, or volume action is attempted",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--created-at", default="2026-08-31T00:00:00Z")
    parser.add_argument("--database-identity", default="mysql://127.0.0.1:62306/recpro")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan = build_plan(
        run_id=args.run_id, created_at=args.created_at,
        database_identity=args.database_identity,
    )
    if args.output is None:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output = output.resolve(strict=False)
    if not output.is_relative_to(PROJECT_ROOT):
        raise ValueError("output must remain inside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "status": "PASS",
        "mode": "NO_WRITE_PLAN_BUILD",
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "git_commit": plan["git_commit"],
        "path": output.relative_to(PROJECT_ROOT).as_posix(),
        "database_connections": 0,
        "database_writes": 0,
        "deepseek_requests": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
