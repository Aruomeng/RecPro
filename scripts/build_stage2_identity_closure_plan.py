#!/usr/bin/env python3
"""Build the exact, forward-only Stage 2 local identity closure plan.

The builder never opens a database, starts a service, creates a credential, or
calls the application.  It freezes the single synthetic reader identity and
the bounded login/consent/profile workflow so that a later apply can be
reviewed independently from the plan that produced the code.
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
TEST_READER_DISPLAY_NAME = "LibraMAS 阶段二测试读者"
TEST_READER_PROFILE = {
    "major": "图书馆学",
    "grade": "研究生",
    "research_direction": "多智能体推荐",
    "preferred_language": "zh-CN",
}
APPEND_ROWS = 23
CONTROLLED_UPDATE_OPERATIONS = 10
MAXIMUM_CHANGES = APPEND_ROWS + CONTROLLED_UPDATE_OPERATIONS
FIXED_BASELINE = {
    "iam_user_account": 1,
    "iam_login_identifier": 1,
    "iam_password_credential": 1,
    "iam_auth_session": 0,
    "iam_refresh_token": 0,
    "iam_action_token": 1,
    "iam_security_event": 2,
    "user_personalization_consent_fact": 0,
    "user_declared_profile": 2,
    "user_declared_profile_history": 2,
}
INPUT_PATHS = (
    "backend/app/api/identity.py",
    "backend/app/composition.py",
    "backend/app/config.py",
    "backend/app/identity/adapters/mysql.py",
    "backend/app/identity/application.py",
    "backend/app/identity/security.py",
    "scripts/build_stage2_identity_closure_plan.py",
    "scripts/execute_stage2_identity_closure.py",
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
        raise ValueError("working tree must be clean before freezing Stage 2")


def expected_fingerprint(database_identity: str, reviewed_commit: str, run_id: str) -> str:
    payload = (
        f"recpro_local_research_stage2_identity:{database_identity}:"
        f"{PROJECT_ROOT}:{reviewed_commit}:{run_id}"
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mysql_target(identifier: str, operation: str = "APPEND") -> dict[str, object]:
    return {
        "kind": "MYSQL",
        "identifier": identifier,
        "operation": operation,
        "expected_before_count": 0,
        "expected_after_min_count": 1,
    }


def _file_target(identifier: str) -> dict[str, object]:
    return {
        "kind": "FILE",
        "identifier": identifier,
        "operation": "CREATE",
        "expected_before_count": 0,
        "expected_after_min_count": 1,
    }


def targets_for(run_id: str) -> list[dict[str, object]]:
    targets = [
        _file_target(".env.stage2-reader-login.local"),
        _file_target(f"artifacts/verification/stage2-identity-closure/{run_id}/acceptance.json"),
        _mysql_target(f"recpro.iam_user_account:user_id={TEST_READER_ID}"),
        _mysql_target(f"recpro.iam_login_identifier:identifier={TEST_READER_IDENTIFIER}"),
        _mysql_target(f"recpro.iam_action_token:purpose=ACTIVATE_ACCOUNT:user_id={TEST_READER_ID}"),
        _mysql_target(f"recpro.iam_user_role_fact:user_id={TEST_READER_ID}:role=user"),
        _mysql_target(f"recpro.iam_password_credential:user_id={TEST_READER_ID}"),
        _mysql_target(f"recpro.iam_auth_session:stage2-admin:{run_id}"),
        _mysql_target(f"recpro.iam_auth_session:stage2-reader:{run_id}"),
        _mysql_target(f"recpro.iam_refresh_token:stage2-admin-initial:{run_id}"),
        _mysql_target(f"recpro.iam_refresh_token:stage2-reader-initial:{run_id}"),
        _mysql_target(f"recpro.iam_refresh_token:stage2-reader-rotation:{run_id}"),
        _mysql_target(f"recpro.iam_security_event:stage2-admin-login:{run_id}"),
        _mysql_target(f"recpro.iam_security_event:stage2-account-provisioned:{run_id}"),
        _mysql_target(f"recpro.iam_security_event:stage2-account-activated:{run_id}"),
        _mysql_target(f"recpro.iam_security_event:stage2-reader-login:{run_id}"),
        _mysql_target(f"recpro.iam_security_event:stage2-reader-logout:{run_id}"),
        _mysql_target(f"recpro.iam_security_event:stage2-admin-logout:{run_id}"),
        _mysql_target(f"recpro.user_personalization_consent_fact:stage2-grants:{run_id}"),
        _mysql_target(f"recpro.user_personalization_consent_fact:stage2-withdraw:{run_id}"),
        _mysql_target(f"recpro.user_declared_profile_history:user_id={TEST_READER_ID}:version=1"),
        _mysql_target(f"recpro.user_declared_profile:user_id={TEST_READER_ID}:version=1"),
    ]
    targets.extend([
        _mysql_target(f"recpro.iam_user_account:user_id={10000}:last_login", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_action_token:stage2-activation:{TEST_READER_ID}:consume", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_user_account:user_id={TEST_READER_ID}:activate", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_user_account:user_id={TEST_READER_ID}:last_login", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_refresh_token:stage2-reader-initial:{run_id}:consume", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_auth_session:stage2-reader:{run_id}:last_seen", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_auth_session:stage2-reader:{run_id}:revoke", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_refresh_token:stage2-reader:{run_id}:revoke", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_auth_session:stage2-admin:{run_id}:revoke", "UPDATE_STATUS"),
        _mysql_target(f"recpro.iam_refresh_token:stage2-admin:{run_id}:revoke", "UPDATE_STATUS"),
    ])
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
            NAMESPACE_URL, f"recpro:stage2-identity-closure:{commit}:{run_id}",
        )),
        "created_at": parsed.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S2_CONTROLLED_UPDATE",
        "mode": "APPLY",
        "intent": (
            "Create one non-person synthetic Stage 2 reader (user_id 10001), "
            "activate it, verify local login/refresh/logout, append four explicit "
            "personalization grants plus one behavior-learning withdrawal, and "
            "append one declared profile version. Only the allowlisted current "
            "account/session/projection fields may be updated; no recommendation, "
            "feedback, behavior, graph, vector, model, or historical-row deletion "
            "is permitted."
        ),
        "environment": {
            "environment_id": "recpro_local_research_stage2_identity_closure",
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
        "idempotency_key": f"stage2-identity-closure-{run_id}",
        "request_run_id": run_id,
        "max_changes": MAXIMUM_CHANGES,
        "preconditions": [
            f"reviewed commit is exactly {commit} or a descendant preserving every input hash",
            "the user separately approves this exact successor plan_id and plan_hash before a database connection that can write",
            f"MySQL target is exactly {database_identity}; the fixed baseline is {json.dumps(FIXED_BASELINE, sort_keys=True)}",
            f"iam_user_account AUTO_INCREMENT is exactly {TEST_READER_ID}; no account, identifier, token, session, consent, or profile exists for the fixed Stage 2 reader",
            f"the normalized reader identifier is exactly {TEST_READER_IDENTIFIER}; it is a synthetic non-person test identity and is not user 1001 or 1002",
            "the protected administrator credential file exists and its password is never printed, logged, or written to the plan",
            "the reader credential output .env.stage2-reader-login.local is absent; the executor refuses to overwrite it",
            "the explicit local G4 identity API is already running at http://127.0.0.1:8000 and readiness is checked before any POST",
            "the executor uses only the identity endpoints: admin login, reader provision, activation, reader login, four consent grants, one behavior-learning withdrawal, profile update, one refresh rotation, and two logouts",
            f"only {APPEND_ROWS} append rows and {CONTROLLED_UPDATE_OPERATIONS} allowlisted current-state update operations are permitted; max_changes={MAXIMUM_CHANGES}",
            "recommendation, feedback, behavior, Agent Workspace audit, Neo4j, Chroma, and DeepSeek request counts remain exactly 0",
            "a partial failure is retained for inspection and requires a new forward-only plan; no destructive schema/data operation, overwrite, container, or volume action is attempted",
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
    parser.add_argument(
        "--database-identity", default="mysql://127.0.0.1:62306/recpro",
    )
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
