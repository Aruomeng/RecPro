#!/usr/bin/env python3
"""Apply one explicitly approved G8 cold guided append plan.

The executor is intentionally narrow: it accepts the exact plan/evidence
pair, appends one four-Agent clarification task through the existing
transactional G4 service, and verifies the bounded 19-row delta.  It never
migrates, updates, deletes, claims outbox work, calls Neo4j/Chroma, or enables
an external LLM provider.  Omitting ``--apply`` is fail-closed.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import UUID

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator
from backend.app.recommendation.domain.public import RecommendationTaskCommand
from scripts.build_g8_cold_user_guided_plan import (
    CONFIG_PATH,
    EXPECTED_DELTAS,
    SCHEMA_PATH,
    canonical,
    load_browser_plan,
    load_evidence,
    resolve_inside_project,
    sha256_bytes,
)
from scripts.verify_g8_cold_user_guided_readonly import read_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
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
        raise ValueError("git HEAD is not a full commit hash")
    return commit


def load_plan(path: Path, *, approved_plan_id: str, approved_hash: str) -> tuple[dict[str, Any], bytes, Path]:
    resolved = resolve_inside_project(path, label="cold guided ChangePlan")
    raw = resolved.read_bytes()
    plan = json.loads(raw.decode("utf-8"))
    if not isinstance(plan, dict):
        raise ValueError("cold guided ChangePlan must contain a JSON object")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan),
        key=lambda error: tuple(error.absolute_path),
    )
    if errors:
        raise ValueError("ChangePlan violates schema: " + "; ".join(error.message for error in errors))
    if plan.get("classification") != "S1_APPEND" or plan.get("mode") != "DRY_RUN":
        raise ValueError("only an S1_APPEND DRY_RUN cold guided plan may be approved")
    if str(plan.get("plan_id")) != approved_plan_id:
        raise ValueError("approved plan id does not match ChangePlan")
    if not HASH_PATTERN.fullmatch(approved_hash) or str(plan.get("plan_hash")) != approved_hash:
        raise ValueError("approved plan hash does not match ChangePlan")
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
    targets: dict[str, Mapping[str, Any]] = {}
    for target in plan.get("targets", []):
        if not isinstance(target, dict) or target.get("kind") != "MYSQL" or target.get("operation") != "APPEND":
            raise ValueError("cold guided plan contains a non-MySQL append target")
        table = str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        if table in targets:
            raise ValueError(f"cold guided plan contains duplicate target: {table}")
        targets[table] = target
    if set(targets) != set(EXPECTED_DELTAS) or int(plan.get("max_changes", -1)) != sum(EXPECTED_DELTAS.values()):
        raise ValueError("cold guided plan target set or max_changes is outside the 19-row scope")
    for table, delta in EXPECTED_DELTAS.items():
        actual_delta = int(targets[table]["expected_after_min_count"]) - int(targets[table]["expected_before_count"])
        if actual_delta != delta:
            raise ValueError(f"cold guided plan delta mismatch for {table}: {actual_delta} != {delta}")
    return plan, raw, resolved


def validate_git_boundary(plan: Mapping[str, Any]) -> str:
    reviewed = str(plan["git_commit"])
    current = current_git_commit()
    if reviewed != current:
        raise ValueError(
            "runtime code changed after the reviewed plan commit; regenerate the plan "
            f"(reviewed={reviewed}, current={current})"
        )
    return current


def build_settings(values: Mapping[str, str]):
    from backend.app.config import AppSettings

    return AppSettings(
        app_env="demo",
        app_version="0.1.0",
        config_bundle_path=values["RECPRO_CONFIG_BUNDLE_PATH"],
        config_bundle_sha256=values["RECPRO_CONFIG_BUNDLE_SHA256"],
        config_bundle_version=values["RECPRO_CONFIG_BUNDLE_VERSION"],
        prompt_bundle_path=values.get("RECPRO_PROMPT_BUNDLE_PATH", "contracts/prompts/rec-prompts-v1.0.1.json"),
        prompt_bundle_sha256=values.get("RECPRO_PROMPT_BUNDLE_SHA256", "1fa3b19788574189ae1680a0ef5565fd378200d146d9c0ba83da583ba3abce1a"),
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
                or str(identity[0]) != values["RECPRO_PERSISTENCE_PROBE_ID"]
                or str(identity[1]) != values["RECPRO_MYSQL_DATABASE"]
                or str(identity[2]).split("@", maxsplit=1)[0] != values["RECPRO_MYSQL_USER"]
                or str(identity[3]) != "utf8mb4"
                or str(identity[4]) != "utf8mb4"
            ):
                raise RuntimeError("database identity or runtime probe does not match the approved plan")
            await cursor.execute("SHOW GRANTS")
            grants = tuple(str(row[0]) for row in await cursor.fetchall() if row)
            if not GrantSafetyEvaluator(values["RECPRO_MYSQL_DATABASE"]).grants_are_safe(grants):
                raise RuntimeError("runtime grants failed the least-privilege guard")
            await cursor.execute(
                "SELECT id FROM recommendation_task WHERE request_id = %s AND user_id = %s LIMIT 1",
                (str(request_id), user_id),
            )
            if await cursor.fetchone() is not None:
                raise RuntimeError("cold guided request_id already exists; refusing replay/apply")
        return {
            "probe_id": str(identity[0]),
            "database": str(identity[1]),
            "current_user": str(identity[2]),
            "grants_safe": True,
            "existing_request": False,
        }
    finally:
        connection.close()


def validate_pre_counts(plan: Mapping[str, Any], counts: Mapping[str, int]) -> None:
    for target in plan["targets"]:
        table = str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        expected = int(target["expected_before_count"])
        actual = int(counts.get(table, -1))
        if actual != expected:
            raise RuntimeError(f"pre-count drift for {table}: {actual} != {expected}")


def validate_post_counts(plan: Mapping[str, Any], before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    if set(before) != set(after):
        raise RuntimeError("database table set changed during the approved cold guided append")
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


async def execute(args: argparse.Namespace) -> dict[str, object]:
    if not args.apply:
        raise ValueError("--apply is required; omission is fail-closed")
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run id must use lowercase letters, digits, and hyphens")
    output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / args.run_id
    if output_dir.exists():
        raise FileExistsError(f"apply evidence directory already exists: {output_dir}")

    plan, plan_raw, resolved_plan = load_plan(
        args.plan,
        approved_plan_id=args.plan_id,
        approved_hash=args.approved_plan_hash,
    )
    current_commit = validate_git_boundary(plan)
    evidence, evidence_raw, resolved_evidence = load_evidence(args.evidence)
    browser_plan, browser_raw, resolved_browser_plan = load_browser_plan(
        args.browser_plan, current_commit=current_commit, evidence=evidence
    )
    if sha256_bytes(evidence_raw) != str(plan["input_hashes"]["cold_guided_readonly_evidence"]):
        raise ValueError("cold guided read-only evidence hash does not match approved plan")
    if sha256_bytes(browser_raw) != str(plan["input_hashes"]["aggregate_browser_plan"]):
        raise ValueError("aggregate browser plan hash does not match approved plan")
    if sha256_bytes(CONFIG_PATH.read_bytes()) != str(plan["input_hashes"]["config_bundle"]):
        raise ValueError("config bundle hash does not match approved plan")
    request_payload = dict(evidence["request_payload"])
    if sha256_bytes(canonical(request_payload)) != str(plan["input_hashes"]["request_payload"]):
        raise ValueError("request payload hash does not match approved plan")
    if str(plan["idempotency_key"]) != str(request_payload["request_id"]):
        raise ValueError("idempotency key does not match exact request payload")
    if str(plan.get("request_run_id")) != str(evidence["run_id"]):
        raise ValueError("plan request_run_id does not match read-only evidence run")

    from scripts.validate_runtime_env import read_env, validate_compose

    compose_values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    values = {**compose_values, **read_env(args.secrets_file.resolve(strict=True))}
    required = (
        "COMPOSE_PROJECT_NAME",
        "RECPRO_PERSISTENCE_PROBE_ID",
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")
    if values["COMPOSE_PROJECT_NAME"] != plan["environment"]["environment_id"]:
        raise ValueError("Compose project does not match approved plan")
    database_identity = f"mysql://{values['COMPOSE_PROJECT_NAME']}/{values['RECPRO_MYSQL_DATABASE']}"
    if database_identity != plan["environment"]["database_identity"]:
        raise ValueError("MySQL database identity does not match approved plan")
    host_fingerprint = "sha256:" + sha256_bytes(
        f"{values['COMPOSE_PROJECT_NAME']}:{values['RECPRO_MYSQL_DATABASE']}:{PROJECT_ROOT}:{current_commit}".encode("utf-8")
    )
    if host_fingerprint != plan["environment"]["host_fingerprint"]:
        raise ValueError("host fingerprint does not match approved plan")

    request_id = UUID(str(request_payload["request_id"]))
    session_id = UUID(str(request_payload["session_id"]))
    user_id = int(request_payload["user_id"])
    guard = await read_database_guard(values, request_id=request_id, user_id=user_id)

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
        _table_names, before_counts = await read_snapshot(connection)
    finally:
        connection.close()
    validate_pre_counts(plan, before_counts)
    if before_counts != {str(key): int(value) for key, value in evidence["before_counts"].items()}:
        raise RuntimeError("database counts drifted from the reviewed read-only evidence")

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
        session_id=session_id,
        user_id=user_id,
        scene=str(request_payload["scene"]),
        input_text=str(request_payload["input_text"]),
        resource_types=tuple(str(item) for item in request_payload["requested_resource_types"]),
        output_type=str(request_payload["requested_output_type"]),
        source_resource_id=None,
        source_item_id=None,
        evaluation_at=None,
        constraints={},
        limit=int(request_payload["limit"]),
    )
    result = await service.create_task(command, idempotency_key=str(request_id))
    if result.status_code != 201 or result.replayed:
        raise RuntimeError(
            f"approved cold guided plan did not create a new task: status_code={result.status_code}, replayed={result.replayed}"
        )
    payload = dict(result.payload)
    if payload.get("status") != "WAITING_CLARIFICATION" or payload.get("record_id") is not None:
        raise RuntimeError("approved cold guided plan did not return a waiting response")
    questions = payload.get("questions")
    if not isinstance(questions, list) or len(questions) != 2:
        raise RuntimeError("approved cold guided plan returned an unexpected clarification set")
    if payload.get("task_id") != str(evidence["task_id"]):
        raise RuntimeError("persisted task identity differs from reviewed read-only identity")
    if payload.get("trace_id") != str(evidence["trace_id"]):
        raise RuntimeError("persisted trace identity differs from reviewed read-only identity")

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
        _names_after, after_counts = await read_snapshot(connection)
    finally:
        connection.close()
    deltas = validate_post_counts(plan, before_counts, after_counts)
    readback = await service.get_task(UUID(str(payload["task_id"])), user_id=user_id)
    if readback.get("status") != "WAITING_CLARIFICATION" or int(readback.get("context_version", -1)) != 1:
        raise RuntimeError("waiting task readback does not match the committed context")

    evidence_output = {
        "schema_version": "g8-cold-user-guided-approved-append-v1",
        "status": "PASS",
        "run_id": args.run_id,
        "scenario_id": "cold_user_guided",
        "approved_plan_id": args.plan_id,
        "approved_plan_hash": args.approved_plan_hash,
        "plan_path": str(resolved_plan),
        "plan_git_commit": plan["git_commit"],
        "current_git_commit": current_commit,
        "evidence_path": str(resolved_evidence),
        "browser_plan_path": str(resolved_browser_plan),
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "database_identity": guard,
        "request_id": str(request_id),
        "session_id": str(session_id),
        "task_id": payload.get("task_id"),
        "trace_id": payload.get("trace_id"),
        "user_id": user_id,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "deltas": deltas,
        "response_summary": {
            "status_code": result.status_code,
            "replayed": result.replayed,
            "status": payload.get("status"),
            "context_version": payload.get("context_version"),
            "question_count": len(questions),
            "record_id": payload.get("record_id"),
        },
        "mode": "APPLY_ONE_BOUNDED_APPEND",
        "database_write_rows": sum(deltas.values()),
        "database_writes": sum(deltas.values()),
        "external_requests": 0,
        "external_llm_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "outbox_claims": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
        "max_changes": int(plan["max_changes"]),
        "plan_raw_sha256": sha256_bytes(plan_raw),
        "browser_plan_raw_sha256": sha256_bytes(browser_raw),
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "apply.json").write_text(
        json.dumps(evidence_output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence_output, ensure_ascii=False, indent=2, sort_keys=True))
    return evidence_output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--browser-plan", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] G8 cold guided apply did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
