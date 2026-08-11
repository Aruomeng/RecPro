#!/usr/bin/env python3
"""Reconcile one approved G4 projection append using reads only.

The apply executor already committed one bounded append under an approved
ChangePlan.  This verifier never replays the business request.  It compares
the immutable apply evidence with current MySQL counts, reads the task-local
facts, performs the explicit G4 HTTP ``GET`` status read, and checks the
version-pinned Chroma count.  No POST, migration, seed, update, delete, or
external LLM request is allowed in this command.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

import asyncmy
from fastapi.testclient import TestClient
from pydantic import SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.catalog.runtime.g4_ports import build_g4_readonly_runtime
from backend.app.composition import build_research_g4_http_app_from_runtime
from backend.app.config import AppSettings
from scripts.execute_g4_recommendation_projection import (
    TARGET_TABLES,
    load_request_payload,
    read_table_counts,
    resolve_inside_root,
    sha256_bytes,
    validate_plan,
)
from scripts.g4_operator_runtime import load_existing_chroma_collection
from scripts.validate_runtime_env import read_env, validate_compose


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
GRAPH_VERSION = "lib-books-v1-20260810"
EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"
NAMESPACE_NAME = "library_resources__hash_char_ngram_v1"
CHROMA_DIMENSION = 384


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return dict(value)


def _settings(values: Mapping[str, str]) -> AppSettings:
    """Build an explicit in-memory G4 setting without changing env files."""

    return AppSettings(
        app_env="demo",
        app_version="g4-projection-reconciliation",
        log_level="WARNING",
        config_bundle_version=values["RECPRO_CONFIG_BUNDLE_VERSION"],
        config_bundle_path=values["RECPRO_CONFIG_BUNDLE_PATH"],
        config_bundle_sha256=values["RECPRO_CONFIG_BUNDLE_SHA256"],
        prompt_bundle_version=values["RECPRO_PROMPT_BUNDLE_VERSION"],
        prompt_bundle_path=values["RECPRO_PROMPT_BUNDLE_PATH"],
        prompt_bundle_sha256=values["RECPRO_PROMPT_BUNDLE_SHA256"],
        mysql_host="127.0.0.1",
        mysql_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        mysql_database=values["RECPRO_MYSQL_DATABASE"],
        mysql_user=values["RECPRO_MYSQL_USER"],
        mysql_password=SecretStr(values["RECPRO_MYSQL_PASSWORD"]),
        mysql_connect_timeout_seconds=min(
            float(values.get("RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS", "3")), 30.0
        ),
        persistence_probe_id=values["RECPRO_PERSISTENCE_PROBE_ID"],
        llm_provider="mock",
        g4_http_enabled=True,
    )


async def _connect(values: Mapping[str, str]) -> Any:
    return await asyncmy.connect(
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


def _expected_request_json(request_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request_id": str(request_payload["request_id"]),
        "session_id": str(request_payload["session_id"]),
        "user_id": int(request_payload["user_id"]),
        "scene": str(request_payload["scene"]),
        "input_text": request_payload["input_text"],
        "resource_types": list(request_payload["requested_resource_types"]),
        "output_type": request_payload["requested_output_type"],
        "source_resource_id": None,
        "source_item_id": None,
        "evaluation_at": None,
        "constraints": {},
        "limit": int(request_payload["limit"]),
    }


async def read_task_facts(
    values: Mapping[str, str],
    *,
    request_payload: Mapping[str, Any],
    expected_deltas: Mapping[str, int],
) -> dict[str, Any]:
    """Read one task and every planned row family scoped to that task."""

    request_id = str(request_payload["request_id"])
    user_id = int(request_payload["user_id"])
    connection = await _connect(values)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, trace_id, status, context_version, user_id, session_id, "
                "request_json FROM recommendation_task "
                "WHERE request_id = %s AND user_id = %s",
                (request_id, user_id),
            )
            rows = await cursor.fetchall()
            if len(rows) != 1:
                raise RuntimeError(
                    f"expected one committed task for request_id, found {len(rows)}"
                )
            task_id, trace_id, status, context_version, persisted_user, session_id, request_json = rows[0]
            expected_request = _expected_request_json(request_payload)
            if _canonical(_json_object(request_json)) != _canonical(expected_request):
                raise RuntimeError("persisted request JSON does not match approved payload")
            if str(status) not in {"COMPLETED", "DEGRADED_COMPLETED"}:
                raise RuntimeError(f"committed task status is not complete: {status!r}")
            if int(persisted_user) != user_id or str(session_id) != str(request_payload["session_id"]):
                raise RuntimeError("committed task user/session identity is invalid")
            if int(context_version) != 1:
                raise RuntimeError(f"initial G4 projection context version is {context_version}")

            record_query = (
                "SELECT id FROM recommendation_record WHERE task_id = %s",
                (str(task_id),),
            )
            await cursor.execute(*record_query)
            record_rows = await cursor.fetchall()
            if len(record_rows) != 1:
                raise RuntimeError(f"expected one record for task, found {len(record_rows)}")
            record_id = int(record_rows[0][0])

            count_queries: dict[str, tuple[str, tuple[object, ...]]] = {
                "recommendation_task": (
                    "SELECT COUNT(*) FROM recommendation_task WHERE id = %s",
                    (str(task_id),),
                ),
                "recommendation_task_transition": (
                    "SELECT COUNT(*) FROM recommendation_task_transition WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_candidate": (
                    "SELECT COUNT(*) FROM recommendation_candidate WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_record": (
                    "SELECT COUNT(*) FROM recommendation_record WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_item": (
                    "SELECT COUNT(*) FROM recommendation_item WHERE record_id = %s",
                    (record_id,),
                ),
                "recommendation_item_explanation": (
                    "SELECT COUNT(*) FROM recommendation_item_explanation e "
                    "JOIN recommendation_item i ON i.id = e.recommendation_item_id "
                    "WHERE i.record_id = %s",
                    (record_id,),
                ),
                "recommendation_policy_decision": (
                    "SELECT COUNT(*) FROM recommendation_policy_decision WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_trace": (
                    "SELECT COUNT(*) FROM recommendation_trace WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_agent_message": (
                    "SELECT COUNT(*) FROM recommendation_agent_message WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_agent_result": (
                    "SELECT COUNT(*) FROM recommendation_agent_result WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_agent_artifact": (
                    "SELECT COUNT(*) FROM recommendation_agent_artifact WHERE task_id = %s",
                    (str(task_id),),
                ),
                "recommendation_orchestration_result": (
                    "SELECT COUNT(*) FROM recommendation_orchestration_result WHERE task_id = %s",
                    (str(task_id),),
                ),
            }
            counts: dict[str, int] = {}
            for table in TARGET_TABLES:
                query, params = count_queries[table]
                await cursor.execute(query, params)
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError(f"task-local count query returned no row for {table}")
                counts[table] = int(row[0])
        for table in TARGET_TABLES:
            expected = int(expected_deltas[table])
            if counts[table] != expected:
                raise RuntimeError(
                    f"task-local {table} count mismatch: {counts[table]} != {expected}"
                )
        return {
            "task_id": str(task_id),
            "trace_id": str(trace_id),
            "status": str(status),
            "context_version": int(context_version),
            "record_id": record_id,
            "task_local_counts": counts,
        }
    finally:
        connection.close()


def _load_apply_evidence(path: Path, *, plan_id: str, plan_hash: str) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label="apply evidence")
    raw = resolved.read_bytes()
    evidence = json.loads(raw.decode("utf-8"))
    if not isinstance(evidence, dict) or evidence.get("status") != "PASS":
        raise ValueError("apply evidence must be a PASS object")
    if evidence.get("approved_plan_id") != plan_id or evidence.get("approved_plan_hash") != plan_hash:
        raise ValueError("apply evidence plan identity does not match approval")
    if int(evidence.get("database_writes", -1)) <= 0:
        raise ValueError("apply evidence does not prove a database append")
    if any(int(evidence.get(key, -1)) != 0 for key in ("actual_delete_count", "files_deleted", "overwritten_inputs")):
        raise ValueError("apply evidence contains a destructive action")
    return evidence, raw


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validate_run_id(args.run_id)
    plan, plan_raw = validate_plan(
        args.plan,
        approved_plan_id=args.plan_id,
        approved_hash=args.approved_plan_hash,
    )
    apply_evidence, apply_raw = _load_apply_evidence(
        args.apply_evidence,
        plan_id=args.plan_id,
        plan_hash=args.approved_plan_hash,
    )
    if sha256_bytes(plan_raw) != str(apply_evidence["plan_raw_sha256"]):
        raise ValueError("ChangePlan bytes differ from the approved apply evidence")
    if str(apply_evidence.get("plan_git_commit")) != str(plan["git_commit"]):
        raise ValueError("apply evidence reviewed commit differs from the ChangePlan")
    request_payload = load_request_payload(plan, request_run_id=args.request_run_id)
    expected_deltas = {
        str(table): int(delta)
        for table, delta in dict(apply_evidence.get("deltas", {})).items()
    }
    if set(expected_deltas) != set(TARGET_TABLES):
        raise ValueError("apply evidence delta set does not match the bounded target set")
    if sum(expected_deltas.values()) != int(apply_evidence["database_writes"]):
        raise ValueError("apply evidence write total does not equal target deltas")

    compose_values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secret_values = read_env(args.secrets_file.resolve(strict=True))
    values = {**compose_values, **secret_values}
    required = (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_PERSISTENCE_PROBE_ID",
        "RECPRO_CONFIG_BUNDLE_VERSION",
        "RECPRO_CONFIG_BUNDLE_PATH",
        "RECPRO_CONFIG_BUNDLE_SHA256",
        "RECPRO_PROMPT_BUNDLE_VERSION",
        "RECPRO_PROMPT_BUNDLE_PATH",
        "RECPRO_PROMPT_BUNDLE_SHA256",
        "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT",
        "RECPRO_NEO4J_ADMIN_USER",
        "RECPRO_NEO4J_ADMIN_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required reconciliation keys: {missing}")
    if values["COMPOSE_PROJECT_NAME"] != plan["environment"]["environment_id"]:
        raise ValueError("Compose project does not match the approved plan")

    before_counts = {str(key): int(value) for key, value in apply_evidence["before_counts"].items()}
    expected_after_counts = {
        str(key): int(value) for key, value in apply_evidence["after_counts"].items()
    }
    before_table_names, current_counts = await read_table_counts(values)
    if set(current_counts) != set(expected_after_counts) or tuple(sorted(before_table_names)) != tuple(sorted(expected_after_counts)):
        raise RuntimeError("current MySQL table set differs from the apply evidence")
    if current_counts != expected_after_counts:
        changed = {
            table: (expected_after_counts.get(table), current_counts.get(table))
            for table in sorted(set(expected_after_counts) | set(current_counts))
            if expected_after_counts.get(table) != current_counts.get(table)
        }
        raise RuntimeError(f"current MySQL counts differ from apply evidence: {changed}")
    if any(current_counts[table] < before_counts[table] for table in before_counts):
        raise RuntimeError("a MySQL table count decreased after the approved append")

    task_facts = await read_task_facts(
        values,
        request_payload=request_payload,
        expected_deltas=expected_deltas,
    )
    response_summary = dict(apply_evidence["response_summary"])
    if task_facts["task_id"] != str(response_summary["task_id"]):
        raise RuntimeError("task readback does not match apply response task_id")
    if task_facts["trace_id"] != str(response_summary["trace_id"]):
        raise RuntimeError("task readback does not match apply response trace_id")
    if task_facts["record_id"] != int(response_summary["record_id"]):
        raise RuntimeError("task readback does not match apply response record_id")

    loaded = load_existing_chroma_collection(
        chroma_path=args.chroma_path,
        collection_name=NAMESPACE_NAME,
        expected_metadata={
            "recpro_namespace_name": NAMESPACE_NAME,
            "recpro_graph_version": GRAPH_VERSION,
            "recpro_embedding_version": EMBEDDING_VERSION,
            "recpro_index_version": INDEX_VERSION,
            "hnsw:space": "cosine",
        },
        expected_count=int(apply_evidence["chroma_count_after"]),
        site_packages=args.chroma_site_packages,
    )
    chroma_count = int(loaded.collection.count())
    if chroma_count != int(apply_evidence["chroma_count_before"]) or chroma_count != int(apply_evidence["chroma_count_after"]):
        raise RuntimeError("Chroma count differs from the approved apply evidence")

    graph_endpoint = (
        f"http://127.0.0.1:{values['RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT']}"
        "/db/neo4j/tx/commit"
    )
    runtime = build_g4_readonly_runtime(
        graph_endpoint=graph_endpoint,
        graph_username=values["RECPRO_NEO4J_ADMIN_USER"],
        graph_password=values["RECPRO_NEO4J_ADMIN_PASSWORD"],
        chroma_collection=loaded.collection,
        graph_version=GRAPH_VERSION,
        embedding_version=EMBEDDING_VERSION,
        index_version=INDEX_VERSION,
        namespace_name=NAMESPACE_NAME,
        dimension=CHROMA_DIMENSION,
        timeout=8.0,
    )
    application = build_research_g4_http_app_from_runtime(
        _settings(values),
        runtime=runtime,
        enable_llm_provider=False,
        deadline_seconds=120.0,
    )
    with TestClient(application) as client:
        live = client.get("/api/v1/health/live")
        ready = client.get("/api/v1/health/ready")
        task_response = client.get(
            f"/api/v1/recommendation-tasks/{task_facts['task_id']}",
            headers={"X-Demo-User-Id": str(request_payload["user_id"])},
        )
    if live.status_code != 200 or ready.status_code != 200 or task_response.status_code != 200:
        raise RuntimeError(
            "read-only G4 HTTP reconciliation failed: "
            f"live={live.status_code}, ready={ready.status_code}, task={task_response.status_code}"
        )
    ready_payload = ready.json()
    task_payload = task_response.json()
    if ready_payload.get("can_recommend") is not True:
        raise RuntimeError("G4 readiness did not confirm recommendation capability")
    if task_payload.get("status") not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise RuntimeError("G4 task GET did not confirm a completed task")
    if str(task_payload.get("task_id")) != task_facts["task_id"]:
        raise RuntimeError("G4 task GET returned a different task identity")
    if int(task_payload.get("context_version", -1)) != 1:
        raise RuntimeError("G4 task GET returned an unexpected context version")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"reconciliation directory already exists: {evidence_dir}")
    evidence = {
        "schema_version": "g4-recommendation-projection-approved-append-reconciliation-v1",
        "status": "PASS",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "approved_plan_id": args.plan_id,
        "approved_plan_hash": args.approved_plan_hash,
        "plan_path": str(resolve_inside_root(args.plan, label="ChangePlan")),
        "apply_evidence_path": str(resolve_inside_root(args.apply_evidence, label="apply evidence")),
        "apply_evidence_sha256": sha256_bytes(apply_raw),
        "plan_git_commit": plan["git_commit"],
        "current_git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip(),
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "request_id": str(request_payload["request_id"]),
        "user_id": int(request_payload["user_id"]),
        "task_facts": task_facts,
        "http_readback": {
            "live_status_code": live.status_code,
            "ready_status_code": ready.status_code,
            "ready_status": ready_payload.get("status"),
            "can_recommend": ready_payload.get("can_recommend"),
            "task_status_code": task_response.status_code,
            "task_status": task_payload.get("status"),
            "task_context_version": task_payload.get("context_version"),
            "task_record_id": task_payload.get("record_id"),
            "business_post_count": 0,
        },
        "before_counts": before_counts,
        "after_counts": current_counts,
        "deltas": {
            table: current_counts[table] - before_counts[table]
            for table in sorted(before_counts)
        },
        "chroma_count_before": int(apply_evidence["chroma_count_before"]),
        "chroma_count_after": chroma_count,
        "reconciliation_database_writes": 0,
        "reconciliation_business_posts": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "external_requests": 0,
        "external_llm_requests": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "reconciliation.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply-evidence", type=Path, required=True)
    parser.add_argument("--request-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    parser.add_argument("--chroma-path", type=Path, default=PROJECT_ROOT / "data" / "chroma")
    parser.add_argument(
        "--chroma-site-packages",
        type=Path,
        default=PROJECT_ROOT / ".venv-chroma-g6-20260811" / "lib" / "python3.11" / "site-packages",
    )
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
    ) as exc:
        print(
            "[FAIL] G4 projection read-only reconciliation did not complete: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
