#!/usr/bin/env python3
"""Apply the plan-bound Stage 2 recovery including two missing DB grants.

The identity account was deliberately kept least-privileged, but the profile
tables were omitted from its grant set.  This executor uses the already
running MySQL container's local root socket only after a read-only image/state
check, executes two fixed GRANT statements, then completes the bounded
identity verification.  It never changes container lifecycle, schema, graph,
vector data, or historical facts.
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
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from backend.app.identity.domain import ConsentScope
from scripts.build_stage2_identity_closure_plan import (
    PROJECT_ROOT,
    SCHEMA,
    canonical,
    file_sha256,
)
from scripts.build_stage2_identity_grant_recovery_plan import (
    APPEND_ROWS,
    CONTROLLED_UPDATE_OPERATIONS,
    DATABASE_IDENTITY_PATTERN,
    EXPECTED_DELTAS,
    GRANT_OPERATIONS,
    INPUT_PATHS,
    MAXIMUM_CHANGES,
    PARTIAL_BASELINE,
    RUN_ID_PATTERN,
    TEST_READER_ID,
    TEST_READER_IDENTIFIER,
    TEST_READER_PROFILE,
    expected_fingerprint,
    targets_for,
)
from scripts.execute_stage2_identity_closure import (
    BASE_URL,
    _HTTPClient,
    _read_only_state,
    _write_evidence,
)
from scripts.execute_stage2_identity_recovery import (
    _profile_projection,
    _read_protected_values,
)
from scripts.validate_runtime_env import read_env


DEFAULT_PLAN = PROJECT_ROOT / "plans/stage2-identity-grant-recovery-successor-20260831.json"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.host"
DEFAULT_ADMIN_FILE = PROJECT_ROOT / ".env.admin-login.local"
DEFAULT_READER_FILE = PROJECT_ROOT / ".env.stage2-reader-login.local"
MYSQL_CONTAINER = "recpro-g2-tianyuhang-20260809a-mysql-1"
MYSQL_IMAGE = "mysql:8.4.10@sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6"
DOCKER = Path("/Applications/编程/Docker.app/Contents/Resources/bin/docker")
BASELINE_CONSENTS = sorted([
    [ConsentScope.BEHAVIOR_LEARNING.value, "WITHDRAW"],
    [ConsentScope.DECLARED_PROFILE.value, "GRANT"],
    [ConsentScope.PERSONALIZED_RECOMMENDATION.value, "GRANT"],
    [ConsentScope.RESEARCH_ANALYTICS.value, "GRANT"],
])
_HASH = re.compile(r"^[0-9a-f]{64}$")


class GrantRecoveryExecutionError(RuntimeError):
    """Sanitized failure marker with an explicit partial-write boundary."""

    def __init__(self, message: str, *, writes_started: bool) -> None:
        super().__init__(message)
        self.writes_started = writes_started


def reviewed_commit_is_ancestor(commit: str) -> bool:
    return bool(
        re.fullmatch(r"[0-9a-f]{40}", commit)
        and subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True,
        ).returncode
        == 0
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Stage 2 grant recovery plan must be a JSON object")
    return value


def validate_plan(path: Path, *, plan_id: str, approved_hash: str) -> dict[str, Any]:
    plan = _read_json(path.resolve(strict=True))
    Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    ).validate(plan)
    if (
        plan.get("plan_id") != plan_id
        or plan.get("plan_hash") != approved_hash
        or _HASH.fullmatch(approved_hash) is None
    ):
        raise ValueError("approved Stage 2 grant recovery plan identity does not match")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_hash:
        raise ValueError("Stage 2 grant recovery plan canonical hash does not match")
    commit = str(plan.get("git_commit", ""))
    if not reviewed_commit_is_ancestor(commit):
        raise ValueError("reviewed Stage 2 grant recovery commit is not an ancestor")
    if (
        plan.get("classification") != "S2_CONTROLLED_UPDATE"
        or plan.get("mode") != "APPLY"
        or plan.get("max_changes") != MAXIMUM_CHANGES
    ):
        raise ValueError("Stage 2 grant recovery operation budget is invalid")
    run_id = str(plan.get("request_run_id", ""))
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("Stage 2 grant recovery run identity is invalid")
    inputs = plan.get("input_hashes")
    if not isinstance(inputs, dict) or set(inputs) != set(INPUT_PATHS):
        raise ValueError("Stage 2 grant recovery input hash set is incomplete")
    for relative in INPUT_PATHS:
        if inputs.get(relative) != file_sha256(PROJECT_ROOT / relative):
            raise ValueError(f"Stage 2 grant recovery input hash mismatch: {relative}")
    if plan.get("targets") != targets_for(run_id):
        raise ValueError("Stage 2 grant recovery target set is not the fixed allowlist")
    environment = plan.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("Stage 2 grant recovery environment is missing")
    database_identity = str(environment.get("database_identity", ""))
    if DATABASE_IDENTITY_PATTERN.fullmatch(database_identity) is None:
        raise ValueError("Stage 2 grant recovery database identity is outside the fixed target")
    if environment.get("host_fingerprint") != expected_fingerprint(
        database_identity, commit, run_id,
    ):
        raise ValueError("Stage 2 grant recovery environment fingerprint does not match")
    if plan.get("idempotency_key") != f"stage2-identity-grant-recovery-{run_id}":
        raise ValueError("Stage 2 grant recovery idempotency key does not match run identity")
    return plan


def dry_run_report() -> dict[str, object]:
    return {
        "status": "PASS",
        "mode": "NO_WRITE_STAGE2_IDENTITY_GRANT_RECOVERY_DRY_RUN",
        "mysql_container": MYSQL_CONTAINER,
        "grant_operations": GRANT_OPERATIONS,
        "append_rows": APPEND_ROWS,
        "controlled_update_operations": CONTROLLED_UPDATE_OPERATIONS,
        "maximum_changes": MAXIMUM_CHANGES,
        "database_connections": 0,
        "database_writes": 0,
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "container_deletions": 0,
        "volume_deletions": 0,
    }


def _docker_output(args: Sequence[str], *, env: dict[str, str] | None = None) -> str:
    if not DOCKER.is_file() or not DOCKER.exists():
        raise RuntimeError("approved Docker binary is unavailable")
    completed = subprocess.run(
        [str(DOCKER), *args], cwd=PROJECT_ROOT, env=env,
        capture_output=True, text=True, timeout=15,
    )
    if completed.returncode != 0:
        raise RuntimeError("approved MySQL container command failed")
    return completed.stdout


def _container_root_password() -> str:
    output = _docker_output([
        "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", MYSQL_CONTAINER,
    ])
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if key == "MYSQL_ROOT_PASSWORD" and separator and value:
            return value
    raise RuntimeError("MySQL container root credential is unavailable")


def _container_preflight() -> tuple[str, ...]:
    state = _docker_output([
        "inspect", "-f", "{{.State.Status}}|{{.Config.Image}}", MYSQL_CONTAINER,
    ]).strip()
    if state != f"running|{MYSQL_IMAGE}":
        raise RuntimeError("MySQL container state or image differs from approved target")
    root_password = _container_root_password()
    env = {"MYSQL_PWD": root_password}
    grants = _docker_output([
        "exec", "-e", "MYSQL_PWD", MYSQL_CONTAINER, "mysql", "--protocol=socket",
        "-uroot", "-Drecpro", "--batch", "--skip-column-names", "-e",
        "SHOW GRANTS FOR 'recpro_identity'@'%';",
    ], env={**__import__("os").environ, **env})
    if "user_declared_profile" in grants or "user_declared_profile_history" in grants:
        raise RuntimeError("one or more profile grants already exist; refusing to reuse this plan")
    return tuple(line for line in grants.splitlines() if line.strip())


def _apply_grants() -> None:
    root_password = _container_root_password()
    env = {**__import__("os").environ, "MYSQL_PWD": root_password}
    statement = (
        "GRANT SELECT, INSERT, UPDATE ON recpro.user_declared_profile "
        "TO 'recpro_identity'@'%'; "
        "GRANT SELECT, INSERT ON recpro.user_declared_profile_history "
        "TO 'recpro_identity'@'%';"
    )
    _docker_output([
        "exec", "-e", "MYSQL_PWD", MYSQL_CONTAINER, "mysql", "--protocol=socket",
        "-uroot", "-Drecpro", "--batch", "--skip-column-names", "-e", statement,
    ], env=env)


def _grants_after() -> str:
    root_password = _container_root_password()
    env = {**__import__("os").environ, "MYSQL_PWD": root_password}
    grants = _docker_output([
        "exec", "-e", "MYSQL_PWD", MYSQL_CONTAINER, "mysql", "--protocol=socket",
        "-uroot", "-Drecpro", "--batch", "--skip-column-names", "-e",
        "SHOW GRANTS FOR 'recpro_identity'@'%';",
    ], env=env)
    expected = (
        "GRANT SELECT, INSERT, UPDATE ON `recpro`.`user_declared_profile` "
        "TO `recpro_identity`@`%`",
        "GRANT SELECT, INSERT ON `recpro`.`user_declared_profile_history` "
        "TO `recpro_identity`@`%`",
    )
    if not all(item in grants for item in expected):
        raise RuntimeError("required profile grants were not reconciled")
    return grants


def _expected_after(before: dict[str, Any]) -> dict[str, int]:
    expected = dict(before["counts"])
    for table, delta in EXPECTED_DELTAS.items():
        expected[table] = expected.get(table, 0) + delta
    return expected


async def apply_plan(
    *, plan_path: Path, plan_id: str, approved_hash: str,
    env_path: Path, admin_path: Path, reader_path: Path,
) -> dict[str, object]:
    plan = validate_plan(plan_path, plan_id=plan_id, approved_hash=approved_hash)
    run_id = str(plan["request_run_id"])
    env = read_env(env_path.resolve(strict=True))
    database_identity = str(plan["environment"]["database_identity"])
    port = env.get("RECPRO_MYSQL_HOST_PORT") or env.get("RECPRO_MYSQL_PORT")
    if f"mysql://127.0.0.1:{port}/{env.get('RECPRO_MYSQL_DATABASE', '')}" != database_identity:
        raise ValueError("Stage 2 grant recovery MySQL environment does not match approved plan")
    if not env.get("RECPRO_AUTH_IDENTIFIER_PEPPER"):
        raise ValueError("Stage 2 grant recovery identifier pepper is missing")

    before = await _read_only_state(env)
    evidence_path = PROJECT_ROOT / "artifacts/verification/stage2-identity-grant-recovery" / run_id / "acceptance.json"
    if before["complete"]:
        if not reader_path.resolve().exists():
            raise ValueError("Stage 2 grant recovery is complete but protected reader credential is missing")
        evidence = {
            "status": "PASS",
            "mode": "IDEMPOTENT_REPLAY",
            "run_id": run_id,
            "plan_id": plan_id,
            "plan_hash": approved_hash,
            "verified_at": datetime.now(UTC).isoformat(),
            "database_writes": 0,
            "grant_operations": 0,
            "deepseek_requests": 0,
            "database_physical_deletions": 0,
            "file_deletions": 0,
            "credential_values_printed": 0,
            "read_only_state": before,
        }
        if evidence_path.exists():
            evidence["evidence_path"] = str(evidence_path.relative_to(PROJECT_ROOT))
        else:
            path = _write_evidence(run_id, evidence)
            evidence["evidence_path"] = str(path.relative_to(PROJECT_ROOT))
        return evidence

    if before["counts"] != PARTIAL_BASELINE:
        raise ValueError("Stage 2 grant recovery baseline table counts do not match observed state")
    if (
        before["next_user_id"] != TEST_READER_ID
        or before["reader_user_id"] != TEST_READER_ID
        or before["account"] != ["ACTIVE", 2, 1, 0]
        or before["credential_count"] != 1
        or before["activation_token_count"] != 1
        or before["effective_consents"] != BASELINE_CONSENTS
        or before["profile_count"] != 0
    ):
        raise ValueError("Stage 2 grant recovery reader state is not the approved baseline")
    if evidence_path.exists():
        raise ValueError("Stage 2 grant recovery evidence path exists; refusing overwrite")

    _read_protected_values(
        admin_path, ("RECPRO_ADMIN_LOGIN_IDENTIFIER", "RECPRO_ADMIN_LOGIN_PASSWORD"),
    )
    reader_values = _read_protected_values(
        reader_path, (
            "RECPRO_STAGE2_READER_IDENTIFIER", "RECPRO_STAGE2_READER_PASSWORD",
        ),
    )
    if reader_values["RECPRO_STAGE2_READER_IDENTIFIER"] != TEST_READER_IDENTIFIER:
        raise ValueError("protected reader identifier does not match grant recovery target")
    readiness = _HTTPClient(BASE_URL)
    status, ready_payload = readiness.request("GET", "/api/v1/health/ready")
    _require_status(status, 200, "readiness")
    if not isinstance(ready_payload, dict) or str(ready_payload.get("status", "")).upper() not in {"READY", "UP"}:
        raise ValueError("Stage 2 grant recovery API readiness is not confirmed")
    _container_preflight()

    writes_started = False
    try:
        writes_started = True
        _apply_grants()
        _grants_after()
        admin_values = _read_protected_values(
            admin_path, ("RECPRO_ADMIN_LOGIN_IDENTIFIER", "RECPRO_ADMIN_LOGIN_PASSWORD"),
        )
        client = _HTTPClient(BASE_URL)
        statuses: dict[str, int] = {}
        status, payload = client.request(
            "POST", "/api/v1/auth/login",
            payload={
                "identifier_type": "READER_NUMBER",
                "identifier": admin_values["RECPRO_ADMIN_LOGIN_IDENTIFIER"],
                "password": admin_values["RECPRO_ADMIN_LOGIN_PASSWORD"],
                "device_type": "BROWSER",
            },
        )
        statuses["admin_login"] = status
        _require_status(status, 200, "admin_login")
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RuntimeError("admin login response omitted access token")
        admin_access = str(payload["access_token"])

        status, payload = client.request(
            "POST", "/api/v1/auth/login",
            payload={
                "identifier_type": "READER_NUMBER",
                "identifier": reader_values["RECPRO_STAGE2_READER_IDENTIFIER"],
                "password": reader_values["RECPRO_STAGE2_READER_PASSWORD"],
                "device_type": "BROWSER",
            },
        )
        statuses["reader_login"] = status
        _require_status(status, 200, "reader_login")
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RuntimeError("reader login response omitted access token")
        if not isinstance(payload.get("user"), dict) or payload["user"].get("user_id") != TEST_READER_ID:
            raise RuntimeError("reader login response did not reconcile to user 10001")
        reader_access = str(payload["access_token"])

        status, payload = client.request(
            "PUT", "/api/v1/me/declared-profile", payload=TEST_READER_PROFILE,
            headers={"Authorization": f"Bearer {reader_access}"},
        )
        statuses["declared_profile_update"] = status
        _require_status(status, 200, "declared_profile_update")
        if not isinstance(payload, dict) or not isinstance(payload.get("profile"), dict):
            raise RuntimeError("declared profile response omitted profile")
        profile = payload["profile"]
        if any(profile.get(key) != value for key, value in TEST_READER_PROFILE.items()):
            raise RuntimeError("declared profile response did not reconcile to fixed profile")
        if profile.get("declared_version") != 1 or profile.get("personalization_enabled") is not True:
            raise RuntimeError("declared profile version or compatibility projection is invalid")

        csrf = client.cookies().get("recpro_csrf")
        if not csrf:
            raise RuntimeError("reader login did not issue a CSRF cookie")
        status, payload = client.request(
            "POST", "/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf},
        )
        statuses["reader_refresh_rotation"] = status
        _require_status(status, 200, "reader_refresh_rotation")
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RuntimeError("reader refresh response omitted access token")
        refreshed_reader_access = str(payload["access_token"])
        status, _ = client.request(
            "POST", "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {refreshed_reader_access}"},
        )
        statuses["reader_logout"] = status
        _require_status(status, 204, "reader_logout")
        status, _ = client.request(
            "POST", "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {admin_access}"},
        )
        statuses["admin_logout"] = status
        _require_status(status, 204, "admin_logout")
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise GrantRecoveryExecutionError(str(exc), writes_started=writes_started) from exc

    after = await _read_only_state(env)
    if after["counts"] != _expected_after(before):
        raise GrantRecoveryExecutionError(
            "Stage 2 grant recovery postflight counts do not match fixed budget",
            writes_started=True,
        )
    projection = await _profile_projection(env)
    expected_projection = (
        TEST_READER_PROFILE["major"], TEST_READER_PROFILE["grade"],
        TEST_READER_PROFILE["research_direction"], TEST_READER_PROFILE["preferred_language"],
        1, 1,
    )
    if projection != expected_projection or not after["complete"]:
        raise GrantRecoveryExecutionError(
            "Stage 2 grant recovery did not reconcile fixed profile and account state",
            writes_started=True,
        )
    evidence = {
        "status": "PASS",
        "mode": "APPLY",
        "run_id": run_id,
        "plan_id": plan_id,
        "plan_hash": approved_hash,
        "verified_at": datetime.now(UTC).isoformat(),
        "fixed_reader": {
            "user_id": TEST_READER_ID,
            "identifier": TEST_READER_IDENTIFIER,
            "credential_path": str(reader_path.resolve()),
            "credential_permissions": "0600",
            "plaintext_values_printed": 0,
        },
        "mysql_container": MYSQL_CONTAINER,
        "privilege_grants_applied": GRANT_OPERATIONS,
        "http_statuses": statuses,
        "before": before,
        "after": after,
        "profile_projection_verified": True,
        "prior_partial_sessions_retained": True,
        "append_rows": APPEND_ROWS,
        "controlled_update_operations": CONTROLLED_UPDATE_OPERATIONS,
        "database_writes": MAXIMUM_CHANGES,
        "grant_operations": GRANT_OPERATIONS,
        "business_writes": 0,
        "deepseek_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "container_deletions": 0,
        "volume_deletions": 0,
    }
    path = _write_evidence(run_id, evidence)
    evidence["evidence_path"] = str(path.relative_to(PROJECT_ROOT))
    return evidence


def _require_status(status: int, expected: int, step: str) -> None:
    if status != expected:
        raise RuntimeError(f"Stage 2 grant recovery API step {step} returned HTTP {status}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--approved-plan-hash", default="")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--admin-file", type=Path, default=DEFAULT_ADMIN_FILE)
    parser.add_argument("--reader-file", type=Path, default=DEFAULT_READER_FILE)
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps(dry_run_report(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    try:
        report = asyncio.run(apply_plan(
            plan_path=args.plan, plan_id=args.plan_id,
            approved_hash=args.approved_plan_hash,
            env_path=args.env_file, admin_path=args.admin_file,
            reader_path=args.reader_file,
        ))
    except GrantRecoveryExecutionError as exc:
        print(json.dumps({
            "status": "FAIL",
            "error": type(exc).__name__,
            "message": str(exc),
            "database_writes": "UNKNOWN_AFTER_PARTIAL_FAILURE" if exc.writes_started else 0,
            "partial_failure_requires_new_plan": exc.writes_started,
            "deepseek_requests": 0,
            "file_deletions": 0,
            "database_physical_deletions": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 1
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({
            "status": "FAIL",
            "error": type(exc).__name__,
            "message": str(exc),
            "database_writes": 0,
            "partial_failure_requires_new_plan": False,
            "deepseek_requests": 0,
            "file_deletions": 0,
            "database_physical_deletions": 0,
        }, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
