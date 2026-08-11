#!/usr/bin/env python3
"""Apply one explicitly approved G7 recommendation ChangePlan exactly once.

This command is intentionally fail-closed.  It accepts a DRY_RUN ChangePlan
only when the caller supplies the exact approved hash and an explicit
``--apply`` flag.  It never performs schema changes, seed work, external LLM
requests, graph writes, vector writes, or destructive database operations.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.composition import build_demo_mysql_http_app
from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator
from backend.app.config import AppSettings
from scripts.verify_g7_mysql_http_readonly import COUNT_TABLES, build_settings
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
CONFIG_PATH = PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
REQUEST_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
EXTRA_ASSERTION_TABLES = (
    "recommendation_task_context",
    "recommendation_clarification",
    "recommendation_trace_revision",
)
ALL_COUNT_TABLES = COUNT_TABLES + EXTRA_ASSERTION_TABLES
TARGET_DELTAS = {
    "recommendation_task": (1, 1),
    "recommendation_task_transition": (8, 8),
    "recommendation_candidate": (0, 15),
    "recommendation_record": (1, 1),
    "recommendation_item": (0, 5),
    "recommendation_item_explanation": (0, 5),
    "recommendation_policy_decision": (1, 1),
    "recommendation_trace": (1, 1),
}
APPEND_TABLES = tuple(TARGET_DELTAS)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def resolve_inside_root(value: Path, *, label: str) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def validate_run_id(value: str, *, label: str = "run id") -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must use 3-64 safe characters")
    return value


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("current git HEAD is not a full commit hash")
    return commit


def changed_paths_since(commit: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{commit}..HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label=label)
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, raw


def validate_plan(path: Path, approved_hash: str) -> tuple[dict[str, Any], bytes]:
    plan, raw = load_json(path, label="ChangePlan")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan)
    )
    if errors:
        locations = ", ".join(
            ".".join(str(item) for item in error.absolute_path) for error in errors
        )
        raise ValueError(f"ChangePlan violates schema: {locations}")
    if plan.get("classification") != "S1_APPEND" or plan.get("mode") != "DRY_RUN":
        raise ValueError("only an S1_APPEND DRY_RUN ChangePlan may be approved here")
    plan_hash = str(plan["plan_hash"])
    if approved_hash != plan_hash:
        raise ValueError("approved hash does not equal the ChangePlan hash")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if sha256_bytes(canonical(unsigned)) != plan_hash:
        raise ValueError("ChangePlan hash does not match its canonical contents")
    safety = plan["safety_assertions"]
    if safety != {
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "overwrite_existing": False,
        "destructive_capabilities_required": False,
        "counts_must_not_decrease": True,
    }:
        raise ValueError("ChangePlan safety assertions are not zero-destructive")
    targets = plan.get("targets")
    if not isinstance(targets, list):
        raise ValueError("ChangePlan targets are not an array")
    target_by_table: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict) or target.get("kind") != "MYSQL":
            raise ValueError("ChangePlan contains a non-MySQL target")
        if target.get("operation") != "APPEND":
            raise ValueError("ChangePlan contains a non-append target")
        table = str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        target_by_table[table] = target
    if set(target_by_table) != set(APPEND_TABLES):
        raise ValueError("ChangePlan target set does not match the bounded G3 write set")
    return plan, raw


def validate_git_boundary(plan: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    reviewed = str(plan["git_commit"])
    current = current_git_commit()
    changed = changed_paths_since(reviewed) if current != reviewed else ()
    allowed = {
        "README.md",
        "docs/LibraMAS_实施状态与交接记录.md",
        "scripts/execute_g7_recommendation_post.py",
    }
    unexpected = sorted(set(changed) - allowed)
    if unexpected:
        raise ValueError(
            "runtime code changed after the reviewed plan commit: "
            + ", ".join(unexpected)
        )
    return current, changed


def build_request_payload(*, request_run_id: str, user_id: int, request_id: UUID) -> dict[str, Any]:
    if REQUEST_RUN_ID_PATTERN.fullmatch(request_run_id) is None:
        raise ValueError("request run id must use 3-64 safe characters")
    expected_request_id = uuid5(
        NAMESPACE_URL, f"g7-recommendation-request:{request_run_id}"
    )
    if request_id != expected_request_id:
        raise ValueError("request id does not match the reviewed request run id")
    session_id = uuid5(
        NAMESPACE_URL, f"g7-recommendation-session:{request_run_id}"
    )
    return {
        "request_id": str(request_id),
        "session_id": str(session_id),
        "user_id": user_id,
        "scene": "SEARCH_AFTER",
        "input_text": "多智能体系统与智慧图书馆",
        "requested_resource_types": ["BOOK", "PAPER"],
        "limit": 5,
    }


async def read_counts(values: dict[str, str]) -> dict[str, int]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        counts: dict[str, int] = {}
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            )
            available = {str(row[0]) for row in await cursor.fetchall()}
            missing = sorted(set(ALL_COUNT_TABLES) - available)
            if missing:
                raise RuntimeError(f"required count tables are missing: {missing}")
            for table in ALL_COUNT_TABLES:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError(f"count query returned no row for {table}")
                counts[table] = int(row[0])
        return counts
    finally:
        connection.close()


async def read_database_guard(
    values: dict[str, str], *, request_id: UUID, user_id: int
) -> dict[str, Any]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT probe_id, DATABASE(), CURRENT_USER(), "
                "@@character_set_database, @@character_set_connection "
                "FROM recpro_runtime_probe WHERE probe_id = %s",
                (values["RECPRO_PERSISTENCE_PROBE_ID"],),
            )
            identity = await cursor.fetchone()
            if (
                identity is None
                or identity[0] != values["RECPRO_PERSISTENCE_PROBE_ID"]
                or identity[1] != values["RECPRO_MYSQL_DATABASE"]
                or str(identity[2]).split("@", maxsplit=1)[0]
                != values["RECPRO_MYSQL_USER"]
                or identity[3] != "utf8mb4"
                or identity[4] != "utf8mb4"
            ):
                raise RuntimeError("database identity or runtime probe does not match the plan")
            await cursor.execute("SHOW GRANTS")
            grants = tuple(str(row[0]) for row in await cursor.fetchall() if row)
            if not GrantSafetyEvaluator(values["RECPRO_MYSQL_DATABASE"]).grants_are_safe(grants):
                raise RuntimeError("runtime grants failed the least-privilege guard")
            await cursor.execute(
                "SELECT id FROM recommendation_task "
                "WHERE request_id = %s AND user_id = %s LIMIT 1",
                (str(request_id), user_id),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                raise RuntimeError("approved request_id already exists; refusing replay/apply")
        return {
            "probe_id": values["RECPRO_PERSISTENCE_PROBE_ID"],
            "current_user": str(identity[2]),
            "grants_safe": True,
            "existing_request": False,
        }
    finally:
        connection.close()


def delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {table: after[table] - before[table] for table in ALL_COUNT_TABLES}


def validate_deltas(
    *, plan: dict[str, Any], before: dict[str, int], after: dict[str, int]
) -> dict[str, int]:
    changes = delta(before, after)
    if any(value < 0 for value in changes.values()):
        raise RuntimeError(f"a table count decreased: {changes}")
    for table in EXTRA_ASSERTION_TABLES:
        if changes[table] != 0:
            raise RuntimeError(f"an unplanned context table changed: {table}={changes[table]}")
    target_by_table = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: target
        for target in plan["targets"]
    }
    for table, (minimum, maximum) in TARGET_DELTAS.items():
        actual = changes[table]
        if actual < minimum or actual > maximum:
            raise RuntimeError(
                f"planned delta outside bound for {table}: {actual} not in {minimum}..{maximum}"
            )
        expected_before = int(target_by_table[table]["expected_before_count"])
        if before[table] != expected_before:
            raise RuntimeError(
                f"pre-count drift for {table}: {before[table]} != {expected_before}"
            )
    if sum(changes[table] for table in APPEND_TABLES) > int(plan["max_changes"]):
        raise RuntimeError("actual append rows exceeded ChangePlan max_changes")
    return changes


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if not args.apply:
        raise ValueError("--apply is required; omission is fail-closed")
    run_id = validate_run_id(args.run_id)
    approved_hash = args.approved_plan_hash
    if not re.fullmatch(r"[0-9a-f]{64}", approved_hash):
        raise ValueError("approved plan hash must be 64 lowercase hexadecimal characters")
    plan, plan_raw = validate_plan(args.plan, approved_hash)
    current_commit, changed_paths = validate_git_boundary(plan)
    baseline, baseline_raw = load_json(args.baseline, label="baseline evidence")
    if baseline.get("status") != "PASS":
        raise ValueError("baseline evidence must be PASS")
    if sha256_bytes(baseline_raw) != plan["input_hashes"]["baseline_readonly_evidence"]:
        raise ValueError("baseline evidence hash does not match the approved plan")
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    expected_environment = plan["environment"]
    if values["COMPOSE_PROJECT_NAME"] != expected_environment["environment_id"]:
        raise ValueError("Compose project does not match the approved plan")
    if f"mysql://{values['COMPOSE_PROJECT_NAME']}/{values['RECPRO_MYSQL_DATABASE']}" != expected_environment["database_identity"]:
        raise ValueError("MySQL database identity does not match the approved plan")
    if sha256_bytes(CONFIG_PATH.read_bytes()) != plan["input_hashes"]["config_bundle"]:
        raise ValueError("config bundle hash does not match the approved plan")
    request_id = UUID(str(plan["idempotency_key"]))
    if str(request_id) != plan["idempotency_key"]:
        raise ValueError("approved idempotency key is not a UUID request identity")
    payload = build_request_payload(
        request_run_id=args.request_run_id,
        user_id=args.user_id,
        request_id=request_id,
    )
    if sha256_bytes(canonical(payload)) != plan["input_hashes"]["request_payload"]:
        raise ValueError("reconstructed request payload hash does not match the approved plan")

    before = await read_counts(values)
    expected_before = {
        str(key): int(value) for key, value in baseline["before_counts"].items()
    }
    for table in COUNT_TABLES:
        if before[table] != expected_before.get(table):
            raise RuntimeError(
                f"baseline count drift for {table}: {before[table]} != {expected_before.get(table)}"
            )
    guard = await read_database_guard(values, request_id=request_id, user_id=args.user_id)
    settings = build_settings(values)
    application = build_demo_mysql_http_app(settings)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g7" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")

    with TestClient(application) as client:
        live = client.get("/api/v1/health/live")
        ready = client.get("/api/v1/health/ready")
        if live.status_code != 200 or ready.status_code != 200:
            raise RuntimeError(
                f"health gate failed before apply: live={live.status_code}, ready={ready.status_code}"
            )
        ready_body = ready.json()
        if ready_body.get("can_recommend") is not True:
            raise RuntimeError("health gate did not enable recommendation capability")
        response = client.post(
            "/api/v1/recommendation-tasks",
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": str(request_id),
                "X-Demo-User-Id": str(args.user_id),
            },
        )
        if response.status_code != 201:
            raise RuntimeError(
                f"approved recommendation POST returned unexpected status {response.status_code}: "
                f"{response.text[:400]}"
            )
        if response.headers.get("Idempotency-Replayed") != "false":
            raise RuntimeError("approved recommendation POST was unexpectedly replayed")
        response_body = response.json()
        task_id = response_body.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("recommendation response did not contain task_id")
        persisted = client.get(
            f"/api/v1/recommendation-tasks/{task_id}",
            headers={"X-Demo-User-Id": str(args.user_id)},
        )
        if persisted.status_code != 200:
            raise RuntimeError(
                f"persisted recommendation GET returned {persisted.status_code}: {persisted.text[:400]}"
            )
        persisted_body = persisted.json()

    after = await read_counts(values)
    changes = validate_deltas(plan=plan, before=before, after=after)
    if persisted_body.get("task_id") != task_id:
        raise RuntimeError("persisted task identity mismatch")
    status = persisted_body.get("status")
    if status not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise RuntimeError(f"persisted recommendation did not complete: {status!r}")
    item_count = len(persisted_body.get("items", []))
    if item_count != changes["recommendation_item"]:
        raise RuntimeError(
            "response item count does not match recommendation_item delta: "
            f"{item_count} != {changes['recommendation_item']}"
        )

    evidence: dict[str, Any] = {
        "schema_version": "g7-mysql-http-approved-append-evidence-v1",
        "status": "PASS",
        "run_id": run_id,
        "approved_plan_hash": approved_hash,
        "plan_path": str(resolve_inside_root(args.plan, label="ChangePlan")),
        "plan_git_commit": plan["git_commit"],
        "current_git_commit": current_commit,
        "post_plan_changed_paths": list(changed_paths),
        "baseline_path": str(resolve_inside_root(args.baseline, label="baseline evidence")),
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_host": "127.0.0.1",
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "request_id": str(request_id),
        "session_id": payload["session_id"],
        "user_id": args.user_id,
        "request_run_id": args.request_run_id,
        "health_gate": {
            "live_status_code": live.status_code,
            "ready_status_code": ready.status_code,
            "ready_status": ready_body.get("status"),
            "can_recommend": ready_body.get("can_recommend"),
            "recommendation_pipeline": ready_body.get("components", {}).get(
                "recommendation_pipeline"
            ),
        },
        "database_guard": guard,
        "before_counts": before,
        "after_counts": after,
        "deltas": changes,
        "response_summary": {
            "status_code": response.status_code,
            "idempotency_replayed": response.headers.get("Idempotency-Replayed"),
            "task_id": task_id,
            "persisted_status": status,
            "item_count": item_count,
            "persisted_get_status_code": persisted.status_code,
        },
        "mode": "APPLY_ONE_BOUNDED_APPEND",
        "database_write_rows": sum(changes[table] for table in APPEND_TABLES),
        "database_writes": sum(changes[table] for table in APPEND_TABLES),
        "external_requests": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
        "http_business_posts": 1,
        "http_business_gets": 1,
        "max_changes": int(plan["max_changes"]),
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "recommendation-post-apply.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--request-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (
        OSError,
        RuntimeError,
        ValueError,
        asyncmy.errors.Error,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"[FAIL] G7 approved recommendation apply did not complete: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
