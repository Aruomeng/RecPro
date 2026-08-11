#!/usr/bin/env python3
"""Apply one explicitly approved initial G4 clarification ChangePlan.

The executor is intentionally separate from the completed-result G4 executor.
It accepts only the bounded 19-row HOME-empty waiting plan, verifies the exact
read-only evidence and current table counts, then invokes one opt-in service
transaction.  It never migrates, seeds, updates, deletes, writes graph/vector
stores, or enables an external LLM provider.
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
from typing import Any, Mapping, Sequence
from uuid import UUID

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.recommendation.domain.public import RecommendationTaskCommand
from scripts.build_g4_clarification_plan import (
    REQUEST_SPEC,
    WAITING_DELTAS,
    canonical,
    load_evidence,
    request_payload,
    sha256_bytes,
)
from scripts.verify_g4_clarification_readonly import COUNT_TABLES, read_counts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
CONFIG_PATH = PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def resolve_inside_root(value: Path, *, label: str, strict: bool = True) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=strict)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


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


def load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label=label)
    raw = resolved.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value, raw


def validate_plan(
    path: Path, *, approved_plan_id: str, approved_hash: str
) -> tuple[dict[str, Any], bytes]:
    plan, raw = load_json(path, label="clarification ChangePlan")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan))
    if errors:
        locations = ", ".join(
            ".".join(str(item) for item in error.absolute_path) for error in errors
        )
        raise ValueError(f"ChangePlan violates schema: {locations}")
    if plan.get("classification") != "S1_APPEND" or plan.get("mode") != "DRY_RUN":
        raise ValueError("only an S1_APPEND DRY_RUN clarification plan may be approved")
    if str(plan.get("plan_id")) != approved_plan_id:
        raise ValueError("approved plan id does not match ChangePlan")
    if not HASH_PATTERN.fullmatch(approved_hash) or str(plan.get("plan_hash")) != approved_hash:
        raise ValueError("approved hash does not match ChangePlan")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if sha256_bytes(canonical(unsigned)) != approved_hash:
        raise ValueError("ChangePlan hash does not match canonical contents")
    safety = plan.get("safety_assertions")
    if safety != {
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "overwrite_existing": False,
        "destructive_capabilities_required": False,
        "counts_must_not_decrease": True,
    }:
        raise ValueError("ChangePlan safety assertions are not zero-destructive")
    target_tables = {}
    for target in plan.get("targets", []):
        if not isinstance(target, dict) or target.get("kind") != "MYSQL" or target.get("operation") != "APPEND":
            raise ValueError("clarification plan contains a non-MySQL append target")
        table = str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        if table in target_tables:
            raise ValueError(f"clarification plan contains duplicate target: {table}")
        target_tables[table] = target
    expected_tables = {table for table, _delta in WAITING_DELTAS}
    if set(target_tables) != expected_tables:
        raise ValueError("clarification plan target set is outside the 19-row waiting scope")
    expected_total = sum(
        int(target["expected_after_min_count"])
        - int(target["expected_before_count"])
        for target in target_tables.values()
    )
    if int(plan.get("max_changes", -1)) != expected_total or expected_total != 19:
        raise ValueError("clarification plan max_changes must equal 19 bounded rows")
    return plan, raw


def validate_git_boundary(plan: Mapping[str, Any]) -> str:
    reviewed = str(plan["git_commit"])
    current = current_git_commit()
    if current != reviewed:
        raise ValueError(
            "runtime code changed after the reviewed plan commit; regenerate the plan "
            f"(reviewed={reviewed}, current={current})"
        )
    return current


def load_request_payload(
    plan: Mapping[str, Any], *, request_run_id: str, user_id: int
) -> dict[str, object]:
    if RUN_ID_PATTERN.fullmatch(request_run_id) is None:
        raise ValueError("request run id must use 3-64 safe characters")
    if isinstance(user_id, bool) or user_id < 1:
        raise ValueError("user id must be positive")
    payload = request_payload(request_run_id, user_id=user_id)
    if str(payload["request_id"]) != str(plan["idempotency_key"]):
        raise ValueError("request run id does not match the reviewed idempotency key")
    if sha256_bytes(canonical(payload)) != str(plan["input_hashes"]["request_payload"]):
        raise ValueError("reconstructed request payload hash does not match the plan")
    return payload


def validate_pre_counts(plan: Mapping[str, Any], counts: Mapping[str, int]) -> None:
    targets = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: target
        for target in plan["targets"]
    }
    for table, target in targets.items():
        expected = int(target["expected_before_count"])
        actual = int(counts.get(table, -1))
        if actual != expected:
            raise RuntimeError(f"pre-count drift for {table}: {actual} != {expected}")


def validate_post_counts(
    plan: Mapping[str, Any],
    before: Mapping[str, int],
    after: Mapping[str, int],
) -> dict[str, int]:
    if set(before) != set(after):
        raise RuntimeError("database table set changed during the approved append")
    target_tables = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: target
        for target in plan["targets"]
    }
    deltas = {table: int(after[table]) - int(before[table]) for table in before}
    if any(value < 0 for value in deltas.values()):
        raise RuntimeError(f"a table count decreased: {deltas}")
    for table, delta in deltas.items():
        if table not in target_tables and delta != 0:
            raise RuntimeError(f"unplanned table changed: {table}={delta}")
    expected: dict[str, int] = {}
    for table, target in target_tables.items():
        value = int(target["expected_after_min_count"]) - int(target["expected_before_count"])
        if deltas.get(table) != value:
            raise RuntimeError(f"planned delta mismatch for {table}: {deltas.get(table)} != {value}")
        expected[table] = deltas[table]
    return expected


def build_settings(values: Mapping[str, str]):
    from backend.app.config import AppSettings

    return AppSettings(
        app_env="demo",
        app_version="0.1.0",
        config_bundle_path=values["RECPRO_CONFIG_BUNDLE_PATH"],
        config_bundle_sha256=values["RECPRO_CONFIG_BUNDLE_SHA256"],
        config_bundle_version=values["RECPRO_CONFIG_BUNDLE_VERSION"],
        prompt_bundle_path=values.get(
            "RECPRO_PROMPT_BUNDLE_PATH", "contracts/prompts/rec-prompts-v1.0.0.json"
        ),
        prompt_bundle_sha256=values.get(
            "RECPRO_PROMPT_BUNDLE_SHA256",
            "bad547702e4c3b42395280ea44781e60992a85f981605afbcd29aa13d33db94a",
        ),
        prompt_bundle_version=values.get("RECPRO_PROMPT_BUNDLE_VERSION", "prompt-v1"),
        mysql_host="127.0.0.1",
        mysql_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        mysql_database=values["RECPRO_MYSQL_DATABASE"],
        mysql_user=values["RECPRO_MYSQL_USER"],
        mysql_password=values["RECPRO_MYSQL_PASSWORD"],
        mysql_connect_timeout_seconds=float(values.get("RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS", "3")),
        persistence_probe_id=values["RECPRO_PERSISTENCE_PROBE_ID"],
        llm_provider="mock",
        llm_api_key=None,
    )


async def read_database_guard(values: Mapping[str, str], *, request_id: UUID, user_id: int) -> dict[str, object]:
    from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator

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
                "SELECT probe_id, DATABASE(), CURRENT_USER(), @@character_set_database, "
                "@@character_set_connection FROM recpro_runtime_probe WHERE probe_id = %s",
                (values["RECPRO_PERSISTENCE_PROBE_ID"],),
            )
            identity = await cursor.fetchone()
            if (
                identity is None
                or identity[0] != values["RECPRO_PERSISTENCE_PROBE_ID"]
                or identity[1] != values["RECPRO_MYSQL_DATABASE"]
                or str(identity[2]).split("@", maxsplit=1)[0] != values["RECPRO_MYSQL_USER"]
                or identity[3] != "utf8mb4"
                or identity[4] != "utf8mb4"
            ):
                raise RuntimeError("database identity or runtime probe does not match the plan")
            await cursor.execute("SHOW GRANTS")
            grants = tuple(str(row[0]) for row in await cursor.fetchall() if row)
            if not GrantSafetyEvaluator(values["RECPRO_MYSQL_DATABASE"]).grants_are_safe(grants):
                raise RuntimeError("runtime grants failed the least-privilege guard")
            await cursor.execute(
                "SELECT id FROM recommendation_task WHERE request_id = %s AND user_id = %s LIMIT 1",
                (str(request_id), user_id),
            )
            if await cursor.fetchone() is not None:
                raise RuntimeError("approved clarification request_id already exists; refusing replay/apply")
        return {"probe_id": values["RECPRO_PERSISTENCE_PROBE_ID"], "grants_safe": True, "existing_request": False}
    finally:
        connection.close()


async def execute(args: argparse.Namespace) -> dict[str, object]:
    if not args.apply:
        raise ValueError("--apply is required; omission is fail-closed")
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    plan, plan_raw = validate_plan(
        args.plan,
        approved_plan_id=args.plan_id,
        approved_hash=args.approved_plan_hash,
    )
    current_commit = validate_git_boundary(plan)
    evidence, evidence_raw = load_evidence(args.evidence)
    if sha256_bytes(evidence_raw) != str(plan["input_hashes"]["clarification_readonly_evidence"]):
        raise ValueError("clarification evidence hash does not match the approved plan")
    if sha256_bytes(CONFIG_PATH.read_bytes()) != str(plan["input_hashes"]["config_bundle"]):
        raise ValueError("config bundle hash does not match the approved plan")
    request = load_request_payload(
        plan, request_run_id=args.request_run_id, user_id=args.user_id
    )

    from scripts.validate_runtime_env import read_env, validate_compose

    compose_values = read_env(args.env_file.resolve())
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    values = {**compose_values, **read_env(args.secrets_file.resolve())}
    required = (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")
    if values["COMPOSE_PROJECT_NAME"] != plan["environment"]["environment_id"]:
        raise ValueError("Compose project does not match the approved plan")
    database_identity = f"mysql://{values['COMPOSE_PROJECT_NAME']}/{values['RECPRO_MYSQL_DATABASE']}"
    if database_identity != plan["environment"]["database_identity"]:
        raise ValueError("MySQL database identity does not match the approved plan")
    host_fingerprint = "sha256:" + sha256_bytes(
        f"{values['COMPOSE_PROJECT_NAME']}:{values['RECPRO_MYSQL_DATABASE']}:{PROJECT_ROOT}:{current_commit}".encode(
            "utf-8"
        )
    )
    if host_fingerprint != plan["environment"]["host_fingerprint"]:
        raise ValueError("host fingerprint does not match the approved plan")

    request_id = UUID(str(request["request_id"]))
    user_id = int(request["user_id"])
    guard = await read_database_guard(values, request_id=request_id, user_id=user_id)
    before_counts = await _read_counts(values)
    validate_pre_counts(plan, before_counts)
    evidence_counts = {
        str(key): int(value) for key, value in evidence["before_counts"].items()
    }
    for table in COUNT_TABLES:
        if before_counts.get(table) != evidence_counts.get(table):
            raise RuntimeError(
                f"read-only evidence count drift for {table}: "
                f"{before_counts.get(table)} != {evidence_counts.get(table)}"
            )
    if evidence.get("before_counts") != evidence.get("after_counts"):
        raise ValueError("approved read-only evidence counts are not stable")

    from backend.app.composition import build_research_g4_recommendation_service

    settings = build_settings(values)
    service = build_research_g4_recommendation_service(
        settings,
        dataset_version="lib-books-v1-20260810",
        enable_llm_provider=False,
        deadline_seconds=90.0,
    )
    command = RecommendationTaskCommand(
        request_id=request_id,
        session_id=UUID(str(request["session_id"])),
        user_id=user_id,
        scene="HOME",
        input_text=None,
        resource_types=(),
        output_type=None,
        source_resource_id=None,
        source_item_id=None,
        evaluation_at=None,
        constraints={},
        limit=5,
    )
    result = await service.create_task(command, idempotency_key=str(request_id))
    if result.status_code != 201 or result.replayed:
        raise RuntimeError(
            f"approved clarification plan did not create a new task: status_code={result.status_code}, replayed={result.replayed}"
        )
    payload = dict(result.payload)
    if payload.get("status") != "WAITING_CLARIFICATION" or payload.get("record_id") is not None:
        raise RuntimeError("approved clarification plan did not return a waiting response")
    if not isinstance(payload.get("questions"), list) or not payload["questions"]:
        raise RuntimeError("approved clarification plan returned no questions")

    after_counts = await _read_counts(values)
    deltas = validate_post_counts(plan, before_counts, after_counts)
    readback = await service.get_task(UUID(str(payload["task_id"])), user_id=user_id)
    if readback.get("status") != "WAITING_CLARIFICATION" or int(readback.get("context_version", -1)) != 1:
        raise RuntimeError("waiting task readback does not match the committed context")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / args.run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    evidence_output = {
        "schema_version": "g4-clarification-approved-append-v1",
        "status": "PASS",
        "run_id": args.run_id,
        "approved_plan_id": args.plan_id,
        "approved_plan_hash": args.approved_plan_hash,
        "plan_path": str(resolve_inside_root(args.plan, label="ChangePlan")),
        "plan_git_commit": plan["git_commit"],
        "current_git_commit": current_commit,
        "evidence_path": str(resolve_inside_root(args.evidence, label="clarification evidence")),
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_host": "127.0.0.1",
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "request_id": str(request_id),
        "session_id": str(command.session_id),
        "user_id": user_id,
        "database_guard": guard,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "deltas": deltas,
        "response_summary": {
            "status_code": result.status_code,
            "replayed": result.replayed,
            "task_id": payload.get("task_id"),
            "trace_id": payload.get("trace_id"),
            "status": payload.get("status"),
            "context_version": payload.get("context_version"),
            "record_id": payload.get("record_id"),
            "question_count": len(payload["questions"]),
        },
        "mode": "APPLY_ONE_BOUNDED_APPEND",
        "database_write_rows": sum(deltas.values()),
        "database_writes": sum(deltas.values()),
        "external_requests": 0,
        "external_llm_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
        "max_changes": int(plan["max_changes"]),
        "plan_raw_sha256": sha256_bytes(plan_raw),
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "g4-clarification-apply.json").write_text(
        json.dumps(evidence_output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence_output


async def _read_counts(values: Mapping[str, str]) -> dict[str, int]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=60,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        return await read_counts(connection)
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--request-run-id", required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (
        OSError,
        RuntimeError,
        ValueError,
        AssertionError,
        asyncmy.errors.Error,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"[FAIL] G4 clarification apply did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
