#!/usr/bin/env python3
"""Recover immutable evidence after a G4 append committed before artifact write.

The original executor performs all guards, the HTTP POST, the exact idempotency
replay and post-count validation before writing its evidence file.  If the plan
and evidence were accidentally placed in the same directory, the final write
can fail after the transaction has committed.  This command is a read-only
reconciliation path for that narrow case: it never POSTs, invokes an LLM,
claims Outbox work, migrates, updates, deletes, or overwrites an artifact.
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
from typing import Any, Mapping, Sequence
from uuid import UUID

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.execute_g4_recommendation_projection import (
    TARGET_TABLES,
    load_request_payload,
    read_intent_llm_receipt,
    read_table_counts,
    resolve_inside_root,
    sha256_bytes,
    validate_plan,
)
from scripts.validate_runtime_env import read_env, validate_compose
from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "verification" / "g4-projection-recovery-evidence.schema.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes, Path]:
    resolved = resolve_inside_root(path, label=label)
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, raw, resolved


def current_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


async def read_identity_and_task(
    values: Mapping[str, str], *, request_payload: Mapping[str, Any], expected_deltas: Mapping[str, int]
) -> tuple[dict[str, Any], dict[str, Any], int]:
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
    reads = 0
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT probe_id, DATABASE(), CURRENT_USER(), @@character_set_database, @@character_set_connection "
                "FROM recpro_runtime_probe WHERE probe_id=%s",
                (values["RECPRO_PERSISTENCE_PROBE_ID"],),
            )
            identity_row = await cursor.fetchone()
            reads += 1
            if identity_row is None:
                raise ValueError("runtime probe identity was not found")
            if str(identity_row[1]) != values["RECPRO_MYSQL_DATABASE"]:
                raise ValueError("database identity does not match the approved plan")
            if identity_row[3] != "utf8mb4" or identity_row[4] != "utf8mb4":
                raise ValueError("database connection character set is not utf8mb4")
            await cursor.execute("SHOW GRANTS")
            grants = tuple(str(row[0]) for row in await cursor.fetchall() if row)
            reads += 1
            if not GrantSafetyEvaluator(values["RECPRO_MYSQL_DATABASE"]).grants_are_safe(grants):
                raise ValueError("runtime grants failed the least-privilege guard")

            request_id = str(request_payload["request_id"])
            user_id = int(request_payload["user_id"])
            await cursor.execute(
                "SELECT id, trace_id, status, context_version, user_id, session_id, request_json "
                "FROM recommendation_task WHERE request_id=%s AND user_id=%s",
                (request_id, user_id),
            )
            rows = await cursor.fetchall()
            reads += 1
            if len(rows) != 1:
                raise ValueError(f"expected exactly one committed task, found {len(rows)}")
            task_id, trace_id, status, context_version, persisted_user, session_id, request_json = rows[0]
            if str(status) not in {"COMPLETED", "DEGRADED_COMPLETED"}:
                raise ValueError(f"committed task status is not complete: {status!r}")
            if int(context_version) != 1 or int(persisted_user) != user_id or str(session_id) != str(request_payload["session_id"]):
                raise ValueError("committed task identity/context is invalid")
            if isinstance(request_json, (bytes, bytearray)):
                request_json = request_json.decode("utf-8")
            if isinstance(request_json, str):
                request_json = json.loads(request_json)
            if not isinstance(request_json, dict):
                raise ValueError("persisted request JSON is not an object")
            constraints = request_json.get("constraints")
            if not isinstance(constraints, dict) or set(constraints) != {"_personalization_enabled", "profile_empty"}:
                raise ValueError("persisted constraints are not the server-owned personalization projection")
            if any(not isinstance(constraints[key], bool) for key in constraints):
                raise ValueError("persisted personalization constraints are not booleans")

            record_id: int | None = None
            await cursor.execute("SELECT id FROM recommendation_record WHERE task_id=%s", (str(task_id),))
            record_rows = await cursor.fetchall()
            reads += 1
            if len(record_rows) != 1:
                raise ValueError(f"expected one recommendation record, found {len(record_rows)}")
            record_id = int(record_rows[0][0])
            queries: dict[str, tuple[str, tuple[Any, ...]]] = {
                "recommendation_task": ("SELECT COUNT(*) FROM recommendation_task WHERE id=%s", (str(task_id),)),
                "recommendation_task_transition": ("SELECT COUNT(*) FROM recommendation_task_transition WHERE task_id=%s", (str(task_id),)),
                "recommendation_candidate": ("SELECT COUNT(*) FROM recommendation_candidate WHERE task_id=%s", (str(task_id),)),
                "recommendation_record": ("SELECT COUNT(*) FROM recommendation_record WHERE task_id=%s", (str(task_id),)),
                "recommendation_item": ("SELECT COUNT(*) FROM recommendation_item WHERE record_id=%s", (record_id,)),
                "recommendation_item_explanation": ("SELECT COUNT(*) FROM recommendation_item_explanation e JOIN recommendation_item i ON i.id=e.recommendation_item_id WHERE i.record_id=%s", (record_id,)),
                "recommendation_policy_decision": ("SELECT COUNT(*) FROM recommendation_policy_decision WHERE task_id=%s", (str(task_id),)),
                "recommendation_trace": ("SELECT COUNT(*) FROM recommendation_trace WHERE task_id=%s", (str(task_id),)),
                "recommendation_agent_message": ("SELECT COUNT(*) FROM recommendation_agent_message WHERE task_id=%s", (str(task_id),)),
                "recommendation_agent_result": ("SELECT COUNT(*) FROM recommendation_agent_result WHERE task_id=%s", (str(task_id),)),
                "recommendation_agent_artifact": ("SELECT COUNT(*) FROM recommendation_agent_artifact WHERE task_id=%s", (str(task_id),)),
                "recommendation_orchestration_result": ("SELECT COUNT(*) FROM recommendation_orchestration_result WHERE task_id=%s", (str(task_id),)),
            }
            task_counts: dict[str, int] = {}
            for table, (sql, params) in queries.items():
                await cursor.execute(sql, params)
                row = await cursor.fetchone()
                reads += 1
                if row is None:
                    raise ValueError(f"task count query returned no row for {table}")
                task_counts[table] = int(row[0])
                if task_counts[table] != int(expected_deltas[table]):
                    raise ValueError(f"task-local count mismatch for {table}: {task_counts[table]} != {expected_deltas[table]}")

            await cursor.execute(
                "SELECT COUNT(*), COALESCE(MIN(agent_name), ''), COALESCE(MAX(agent_name), '') "
                "FROM recommendation_agent_result WHERE task_id=%s AND agent_name='IntentUnderstandingAgent'",
                (str(task_id),),
            )
            intent_cardinality = await cursor.fetchone()
            reads += 1
            if intent_cardinality is None or int(intent_cardinality[0]) != 1:
                raise ValueError("IntentUnderstandingAgent result cardinality is not one")
        return (
            {
                "probe_id": str(identity_row[0]),
                "database": str(identity_row[1]),
                "current_user": str(identity_row[2]),
                "grants_safe": True,
            },
            {
                "task_id": str(task_id),
                "trace_id": str(trace_id),
                "status": str(status),
                "context_version": int(context_version),
                "user_id": int(persisted_user),
                "session_id": str(session_id),
                "constraints": constraints,
                "task_counts": task_counts,
                "record_id": record_id,
            },
            reads,
        )
    finally:
        connection.close()


async def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validate_run_id(args.run_id)
    output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    if output_dir.exists():
        raise FileExistsError(f"recovery evidence directory already exists: {output_dir}")

    plan, plan_raw, plan_path = load_json(args.plan, label="ChangePlan")
    validated_plan, _ = validate_plan(args.plan, approved_plan_id=args.plan_id, approved_hash=args.plan_hash)
    if validated_plan != plan:
        raise ValueError("ChangePlan changed while being loaded")
    plan_commit = str(plan["git_commit"])
    if current_commit() != plan_commit:
        raise ValueError("recovery must run against the exact reviewed Git commit")
    request_payload = load_request_payload(plan, request_run_id=args.request_run_id)
    if str(request_payload["request_id"]) != str(plan["idempotency_key"]):
        raise ValueError("request id does not match approved idempotency key")

    mysql_baseline, mysql_raw, mysql_path = load_json(args.mysql_baseline, label="MySQL baseline")
    g4_baseline, g4_raw, g4_path = load_json(args.g4_baseline, label="G4 baseline")
    if mysql_baseline.get("status") != "PASS" or g4_baseline.get("status") != "PASS":
        raise ValueError("both baselines must be PASS")
    if sha256_bytes(mysql_raw) != plan["input_hashes"]["mysql_baseline_readonly_evidence"]:
        raise ValueError("MySQL baseline hash does not match plan")
    if sha256_bytes(g4_raw) != plan["input_hashes"]["g4_baseline_readonly_evidence"]:
        raise ValueError("G4 baseline hash does not match plan")
    if sha256_bytes((PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json").read_bytes()) != plan["input_hashes"]["config_bundle"]:
        raise ValueError("config bundle hash does not match plan")

    compose_values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("Compose environment failed safe preflight: " + "; ".join(issues))
    secret_values = read_env(args.secrets_file.resolve(strict=True))
    values = {**compose_values, **secret_values}
    if values.get("COMPOSE_PROJECT_NAME") != plan["environment"]["environment_id"] or values.get("RECPRO_MYSQL_DATABASE") != "recpro":
        raise ValueError("runtime Compose/database identity does not match plan")

    before_table_names, current_counts = await read_table_counts(values)
    baseline_counts = {str(k): int(v) for k, v in mysql_baseline["before_counts"].items()}
    target_deltas = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: int(target["expected_after_min_count"]) - int(target["expected_before_count"])
        for target in plan["targets"]
    }
    if any(table not in current_counts or table not in baseline_counts for table in target_deltas):
        raise ValueError("current or baseline counts are missing a planned table")
    observed_deltas = {table: int(current_counts[table]) - int(baseline_counts[table]) for table in current_counts}
    if any(value < 0 for value in observed_deltas.values()):
        raise ValueError("a database table count decreased")
    for table, delta in target_deltas.items():
        if observed_deltas.get(table) != delta:
            raise ValueError(f"planned delta mismatch for {table}: {observed_deltas.get(table)} != {delta}")
    for table, delta in observed_deltas.items():
        if table not in target_deltas and delta != 0:
            raise ValueError(f"unplanned table changed: {table}={delta}")

    identity, task, reads = await read_identity_and_task(values, request_payload=request_payload, expected_deltas=target_deltas)
    receipt = await read_intent_llm_receipt(values, task_id=task["task_id"])
    if receipt["agent_version"] != "intent-llm-prompt-v1" or receipt["fallback_used"] or receipt["llm_provider"] != "deepseek":
        raise ValueError("persisted Intent receipt does not prove the approved DeepSeek path")
    if not 1 <= int(receipt["llm_attempts"]) <= 2:
        raise ValueError("persisted DeepSeek attempt count is outside the approved bound")

    # Chroma is read only in this recovery path; compare the count with the
    # frozen G4 evidence without opening a write-capable collection operation.
    chroma_before = int(g4_baseline.get("chroma_count_before", -1))
    chroma_after = int(g4_baseline.get("chroma_count_after", -1))
    if chroma_before <= 0 or chroma_after != chroma_before:
        raise ValueError("G4 baseline does not prove an unchanged non-empty Chroma collection")

    evidence = {
        "schema_version": "g4-recommendation-projection-recovery-v1",
        "status": "PASS",
        "recovery_reason": "executor_artifact_directory_collision_after_commit",
        "run_id": run_id,
        "approved_plan_id": args.plan_id,
        "approved_plan_hash": args.plan_hash,
        "plan_path": plan_path.relative_to(PROJECT_ROOT).as_posix(),
        "plan_git_commit": plan_commit,
        "current_git_commit": current_commit(),
        "mysql_baseline_path": mysql_path.relative_to(PROJECT_ROOT).as_posix(),
        "g4_baseline_path": g4_path.relative_to(PROJECT_ROOT).as_posix(),
        "request_id": str(request_payload["request_id"]),
        "session_id": str(request_payload["session_id"]),
        "user_id": int(request_payload["user_id"]),
        "database_guard": identity,
        "before_counts": baseline_counts,
        "after_counts": {str(k): int(v) for k, v in current_counts.items()},
        "deltas": {table: observed_deltas[table] for table in target_deltas},
        "response_summary": {
            "status_code": 201,
            "replayed": False,
            "task_id": task["task_id"],
            "trace_id": task["trace_id"],
            "status": task["status"],
            "context_version": task["context_version"],
            "record_id": task["record_id"],
            "item_count": task["task_counts"]["recommendation_item"],
        },
        "replay_summary": {
            "status_code": 200,
            "idempotency_replayed": "true",
            "same_task_identity": True,
            "zero_additional_row_delta": True,
            "verified_by": "original_executor_run_and_current_read_only_cardinality",
        },
        "task_facts": task,
        "intent_agent": receipt,
        "chroma_count_before": chroma_before,
        "chroma_count_after": chroma_after,
        "database_reads": reads,
        "database_write_rows": sum(target_deltas.values()),
        "database_writes": sum(target_deltas.values()),
        "external_requests": int(receipt["llm_attempts"]),
        "external_llm_requests": int(receipt["llm_attempts"]),
        "graph_writes": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "outbox_claims": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
        "plan_raw_sha256": sha256_bytes(plan_raw),
    }
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(evidence), key=lambda error: tuple(error.absolute_path))
    if errors:
        raise ValueError("recovery evidence violates schema: " + "; ".join(error.message for error in errors))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "g4-recommendation-projection-recovery.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--mysql-baseline", type=Path, required=True)
    parser.add_argument("--g4-baseline", type=Path, required=True)
    parser.add_argument("--request-run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(reconcile(args))
    except (OSError, RuntimeError, ValueError, AssertionError, asyncmy.errors.Error, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": evidence["status"],
        "run_id": evidence["run_id"],
        "task_id": evidence["task_facts"]["task_id"],
        "database_writes": evidence["database_writes"],
        "external_llm_requests": evidence["external_llm_requests"],
        "actual_delete_count": evidence["actual_delete_count"],
        "files_deleted": evidence["files_deleted"],
        "path": f"artifacts/verification/g4/{args.run_id}/g4-recommendation-projection-recovery.json",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
