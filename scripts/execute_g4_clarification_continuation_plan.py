#!/usr/bin/env python3
"""Fail-closed executor for one approved G4 clarification continuation plan."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import UUID

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator
from scripts.build_g4_clarification_continuation_plan import (
    CONFIG_PATH,
    canonical,
    load_evidence,
    resolve_inside_root,
    sha256_bytes,
)
from scripts.execute_g4_clarification_plan import build_settings
from scripts.verify_g4_clarification_readonly import COUNT_TABLES, read_counts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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
    plan, raw = load_json(path, label="continuation ChangePlan")
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
        raise ValueError("only an S1_APPEND DRY_RUN continuation plan may be approved")
    if str(plan.get("plan_id")) != approved_plan_id:
        raise ValueError("approved plan id does not match ChangePlan")
    if not HASH_PATTERN.fullmatch(approved_hash) or str(plan.get("plan_hash")) != approved_hash:
        raise ValueError("approved hash does not match ChangePlan")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if sha256_bytes(canonical(unsigned)) != approved_hash:
        raise ValueError("ChangePlan hash does not match canonical contents")
    if plan.get("safety_assertions") != {
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "overwrite_existing": False,
        "destructive_capabilities_required": False,
        "counts_must_not_decrease": True,
    }:
        raise ValueError("ChangePlan safety assertions are not zero-destructive")
    target_tables: dict[str, dict[str, object]] = {}
    for target in plan.get("targets", []):
        if not isinstance(target, dict) or target.get("kind") != "MYSQL" or target.get("operation") != "APPEND":
            raise ValueError("continuation plan contains a non-MySQL append target")
        table = str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        if table in target_tables:
            raise ValueError(f"continuation plan contains duplicate target: {table}")
        target_tables[table] = target
    if int(plan.get("max_changes", -1)) != 44:
        raise ValueError("continuation plan max_changes must equal 44")
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


async def read_database_guard(
    values: Mapping[str, str], *, task_id: UUID, idempotency_key: str
) -> dict[str, object]:
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
                "SELECT context_version FROM recommendation_task_context "
                "WHERE task_id = %s AND idempotency_key = %s LIMIT 1",
                (str(task_id), idempotency_key),
            )
            if await cursor.fetchone() is not None:
                raise RuntimeError("continuation idempotency key already exists; refusing replay/apply")
        return {
            "probe_id": values["RECPRO_PERSISTENCE_PROBE_ID"],
            "grants_safe": True,
            "existing_idempotency": False,
        }
    finally:
        connection.close()


def validate_pre_counts(plan: Mapping[str, Any], counts: Mapping[str, int]) -> None:
    targets = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: target
        for target in plan["targets"]
    }
    for table, target in targets.items():
        expected = int(target["expected_before_count"])
        if int(counts.get(table, -1)) != expected:
            raise RuntimeError(f"pre-count drift for {table}: {counts.get(table)} != {expected}")


def validate_post_counts(
    plan: Mapping[str, Any], before: Mapping[str, int], after: Mapping[str, int]
) -> dict[str, int]:
    if set(before) != set(after):
        raise RuntimeError("database table set changed during the approved continuation")
    targets = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: target
        for target in plan["targets"]
    }
    deltas = {table: int(after[table]) - int(before[table]) for table in before}
    if any(value < 0 for value in deltas.values()):
        raise RuntimeError(f"a table count decreased: {deltas}")
    for table, delta in deltas.items():
        if table not in targets and delta != 0:
            raise RuntimeError(f"unplanned table changed: {table}={delta}")
    expected: dict[str, int] = {}
    for table, target in targets.items():
        planned = int(target["expected_after_min_count"]) - int(target["expected_before_count"])
        if deltas.get(table) != planned:
            raise RuntimeError(f"planned delta mismatch for {table}: {deltas.get(table)} != {planned}")
        expected[table] = deltas[table]
    return expected


async def read_task_guard(
    values: Mapping[str, str], *, task_id: UUID, user_id: int, context_version: int
) -> None:
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
                "SELECT user_id FROM recommendation_task WHERE id = %s",
                (str(task_id),),
            )
            task = await cursor.fetchone()
            if task is None or int(task[0]) != user_id:
                raise RuntimeError("continuation task identity or user does not match the plan")
            await cursor.execute(
                "SELECT status, context_version, answers_json, idempotency_key "
                "FROM recommendation_task_context WHERE task_id = %s "
                "ORDER BY context_version DESC LIMIT 1",
                (str(task_id),),
            )
            context = await cursor.fetchone()
            if (
                context is None
                or int(context[1]) != context_version
                or str(context[0]) != "WAITING_CLARIFICATION"
                or json.loads(context[2]) != {}
                or context[3] is not None
            ):
                raise RuntimeError("continuation requires the latest unanswered WAITING context")
    finally:
        connection.close()


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
    plan_tables = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        for target in plan["targets"]
    }
    evidence_tables = {str(key) for key in evidence["expected_deltas"]}
    if plan_tables != evidence_tables:
        raise ValueError("continuation plan target set does not match read-only evidence")
    if sha256_bytes(evidence_raw) != str(plan["input_hashes"]["clarification_continuation_readonly_evidence"]):
        raise ValueError("continuation evidence hash does not match the approved plan")
    if sha256_bytes(CONFIG_PATH.read_bytes()) != str(plan["input_hashes"]["config_bundle"]):
        raise ValueError("config bundle hash does not match the approved plan")
    answer_payload = {
        "task_id": str(evidence["task_id"]),
        "trace_id": str(evidence["trace_id"]),
        "user_id": int(evidence["user_id"]),
        "previous_context_version": int(evidence["previous_context_version"]),
        "next_context_version": int(evidence["next_context_version"]),
        "answers": dict(evidence["answers"]),
        "idempotency_key": str(evidence["proposed_idempotency_key"]),
    }
    if sha256_bytes(canonical(answer_payload)) != str(plan["input_hashes"]["answer_payload"]):
        raise ValueError("answer payload hash does not match the approved plan")
    if str(plan["idempotency_key"]) != str(evidence["proposed_idempotency_key"]):
        raise ValueError("continuation idempotency key does not match evidence")

    from scripts.validate_runtime_env import read_env, validate_compose

    compose_values = read_env(args.env_file.resolve())
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    values = {**compose_values, **read_env(args.secrets_file.resolve())}
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

    task_id = UUID(str(evidence["task_id"]))
    trace_id = UUID(str(evidence["trace_id"]))
    user_id = int(evidence["user_id"])
    context_version = int(evidence["previous_context_version"])
    idempotency_key = str(evidence["proposed_idempotency_key"])
    await read_database_guard(values, task_id=task_id, idempotency_key=idempotency_key)
    await read_task_guard(
        values, task_id=task_id, user_id=user_id, context_version=context_version
    )
    before_counts = await _read_counts(values)
    validate_pre_counts(plan, before_counts)
    if before_counts != {str(key): int(value) for key, value in evidence["before_counts"].items()}:
        raise RuntimeError("continuation evidence count drifted before apply")

    from backend.app.composition import build_research_g4_recommendation_service

    settings = build_settings(values)
    service = build_research_g4_recommendation_service(
        settings,
        dataset_version="lib-books-v1-20260810",
        enable_llm_provider=False,
        deadline_seconds=90.0,
    )
    result = await service.submit_clarification(
        task_id,
        context_version=context_version,
        answers=dict(evidence["answers"]),
        idempotency_key=idempotency_key,
        user_id=user_id,
    )
    if result.status_code != 200 or result.replayed:
        raise RuntimeError(
            f"approved continuation did not create a new context: status_code={result.status_code}, replayed={result.replayed}"
        )
    payload = dict(result.payload)
    if payload.get("status") not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise RuntimeError("approved continuation did not complete the task")
    if int(payload.get("context_version", -1)) != context_version + 1:
        raise RuntimeError("approved continuation returned the wrong context version")
    if not isinstance(payload.get("items"), list) or not payload["items"]:
        raise RuntimeError("approved continuation returned no recommendation items")
    after_counts = await _read_counts(values)
    deltas = validate_post_counts(plan, before_counts, after_counts)
    readback = await service.get_task(task_id, user_id=user_id)
    if readback.get("status") not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise RuntimeError("continuation task readback did not complete")
    if int(readback.get("context_version", -1)) != context_version + 1:
        raise RuntimeError("continuation task readback has the wrong context version")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / args.run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    evidence_output = {
        "schema_version": "g4-clarification-continuation-approved-append-v1",
        "status": "PASS",
        "run_id": args.run_id,
        "approved_plan_id": args.plan_id,
        "approved_plan_hash": args.approved_plan_hash,
        "plan_path": str(resolve_inside_root(args.plan, label="ChangePlan")),
        "plan_git_commit": plan["git_commit"],
        "current_git_commit": current_commit,
        "evidence_path": str(resolve_inside_root(args.evidence, label="continuation evidence")),
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_host": "127.0.0.1",
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "task_id": str(task_id),
        "trace_id": str(trace_id),
        "user_id": user_id,
        "previous_context_version": context_version,
        "next_context_version": context_version + 1,
        "answers": dict(evidence["answers"]),
        "idempotency_key": idempotency_key,
        "database_guard": {
            "grants_safe": True,
            "existing_idempotency": False,
            "probe_id": values["RECPRO_PERSISTENCE_PROBE_ID"],
        },
        "before_counts": before_counts,
        "after_counts": after_counts,
        "deltas": deltas,
        "response_summary": {
            "status_code": result.status_code,
            "replayed": result.replayed,
            "status": payload.get("status"),
            "context_version": payload.get("context_version"),
            "task_id": payload.get("task_id"),
            "trace_id": payload.get("trace_id"),
            "record_id": payload.get("record_id"),
            "item_count": len(payload["items"]),
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
    (evidence_dir / "g4-clarification-continuation-apply.json").write_text(
        json.dumps(evidence_output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence_output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
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
        print(
            "[FAIL] G4 clarification continuation apply did not complete: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
