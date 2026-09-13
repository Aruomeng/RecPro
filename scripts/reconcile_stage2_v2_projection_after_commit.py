#!/usr/bin/env python3
"""Reconcile a Stage 2 append that committed before postflight completed.

This recovery command is read-only with respect to MySQL, Neo4j, and Chroma.
It accepts the already approved ChangePlan and its hash-bound baselines,
requires every planned target to be at the exact approved after-count, reads
the task-local append families, validates the stored and replayed v2 graph
evidence, and issues only the already-authorized idempotent POST replay.  It
never creates a new recommendation task and never calls an external model.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

import asyncmy
from fastapi.testclient import TestClient

from backend.app.catalog.adapters.chroma import ChromaVectorReader
from backend.app.catalog.adapters.embedding import HashCharNgramQueryEmbedder
from backend.app.catalog.adapters.neo4j import Neo4jGraphReader
from backend.app.composition import (
    build_research_g4_http_app,
    build_research_g4_recommendation_service,
)
from scripts.execute_g4_recommendation_projection import (
    CHROMA_DIMENSION,
    EMBEDDING_VERSION,
    INDEX_VERSION,
    NAMESPACE_NAME,
    SHARED_TABLES,
    TARGET_TABLES,
    build_settings,
    current_git_commit,
    load_approved_graph_runtime,
    load_chroma,
    load_pass_evidence,
    load_request_payload,
    plan_requires_v2_graph_paths,
    read_table_counts,
    resolve_inside_root,
    validate_persisted_status_projection,
    validate_plan,
)
from scripts.g4_graph_evidence_contract import (
    validate_v2_http_items,
    validate_v2_ranked_candidates,
    validate_v2_readonly_evidence,
)
from scripts.run_research_workbench import (
    merge_runtime_values,
    require_final_readonly_graph,
)
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g4_recommendation_projection_result import read_task_facts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("persisted orchestration payload is not an object")
    return dict(value)


def _target_deltas(plan: Mapping[str, Any]) -> dict[str, int]:
    deltas = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]:
        int(target["expected_after_min_count"])
        - int(target["expected_before_count"])
        for target in plan["targets"]
    }
    if set(deltas) != set(TARGET_TABLES):
        raise RuntimeError("approved target set differs from the G4 append boundary")
    if sum(deltas.values()) != int(plan["max_changes"]):
        raise RuntimeError("approved target deltas differ from max_changes")
    return deltas


def _require_plan_ancestor(plan_commit: str, current_commit: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", plan_commit, current_commit],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("reconciliation code is not descended from the approved commit")


async def _stored_result(
    values: Mapping[str, str], *, task_id: str
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=60,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT payload_json FROM recommendation_orchestration_result "
                "WHERE task_id = %s AND context_version = 1",
                (task_id,),
            )
            rows = await cursor.fetchall()
            if len(rows) != 1:
                raise RuntimeError("expected one persisted orchestration result")
            payload = _json_object(rows[0][0])
            await cursor.execute(
                "SELECT agent_name, agent_version, fallback_used "
                "FROM recommendation_agent_result "
                "WHERE task_id = %s AND context_version = 1 ORDER BY agent_name",
                (task_id,),
            )
            agent_rows = await cursor.fetchall()
        await connection.rollback()
    finally:
        connection.close()
    agents = [
        {
            "agent_name": str(row[0]),
            "agent_version": str(row[1]),
            "fallback_used": bool(row[2]),
        }
        for row in agent_rows
    ]
    if len(agents) != 7 or any(
        "llm" in str(agent["agent_version"]).lower() for agent in agents
    ):
        raise RuntimeError("persisted Agent receipts do not prove the zero-LLM path")
    return payload, agents


def _internal_graph_refs(items: Sequence[object]) -> set[str]:
    return {
        str(reference)
        for item in items
        if isinstance(item, Mapping)
        for reference in item.get("graph_path_refs", [])
    }


def _public_graph_refs(items: Sequence[object]) -> set[str]:
    refs: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        refs.update(str(reference) for reference in evidence.get("graph_path_refs", []))
    return refs


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validate_run_id(args.run_id)
    plan, _plan_raw = validate_plan(
        args.plan,
        approved_plan_id=args.plan_id,
        approved_hash=args.approved_plan_hash,
    )
    if not plan_requires_v2_graph_paths(plan):
        raise ValueError("recovery accepts only a Stage 2 v2 Graph evidence plan")
    current_commit = current_git_commit()
    plan_commit = str(plan["git_commit"])
    _require_plan_ancestor(plan_commit, current_commit)
    mysql_baseline, _ = load_pass_evidence(
        args.mysql_baseline,
        expected_hash=str(plan["input_hashes"]["mysql_baseline_readonly_evidence"]),
        label="MySQL baseline evidence",
    )
    g4_baseline, _ = load_pass_evidence(
        args.g4_baseline,
        expected_hash=str(plan["input_hashes"]["g4_baseline_readonly_evidence"]),
        label="G4 baseline evidence",
    )
    baseline_coverage = validate_v2_readonly_evidence(
        g4_baseline, require_graph_paths=True
    )
    if g4_baseline.get("git_commit") != plan_commit:
        raise RuntimeError("approved read-only evidence differs from the plan commit")
    request_payload = load_request_payload(
        plan, request_run_id=args.request_run_id
    )
    target_deltas = _target_deltas(plan)

    compose_values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secret_values = read_env(args.secrets_file.resolve(strict=True))
    values = {**compose_values, **secret_values}
    graph_values = read_env(args.graph_env_file.resolve(strict=True))
    graph_state = require_final_readonly_graph(
        merge_runtime_values({}, {}, graph_values)
    )
    graph_version, graph_port, graph_user, graph_password, graph_source = (
        load_approved_graph_runtime(g4_baseline, values, graph_values)
    )
    if values["COMPOSE_PROJECT_NAME"] != plan["environment"]["environment_id"]:
        raise RuntimeError("Compose project differs from the approved plan")

    table_names, counts_before_replay = await read_table_counts(values)
    target_before: dict[str, int] = {}
    target_after: dict[str, int] = {}
    for target in plan["targets"]:
        table = str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        before = int(target["expected_before_count"])
        after = int(target["expected_after_min_count"])
        if counts_before_replay.get(table) != after:
            raise RuntimeError(
                f"committed target count differs for {table}: "
                f"{counts_before_replay.get(table)} != {after}"
            )
        target_before[table] = before
        target_after[table] = after
    mysql_counts = mysql_baseline["before_counts"]
    g4_counts = g4_baseline["before_counts"]
    for table in SHARED_TABLES:
        expected = int(mysql_counts[table])
        if int(g4_counts[table]) != expected or counts_before_replay.get(table) != expected:
            raise RuntimeError(f"protected shared table changed: {table}")

    task_facts = await read_task_facts(
        values,
        request_payload=request_payload,
        expected_deltas=target_deltas,
    )
    stored_payload, agent_receipts = await _stored_result(
        values, task_id=str(task_facts["task_id"])
    )
    stored_items = stored_payload.get("items")
    if not isinstance(stored_items, list) or len(stored_items) != target_deltas[
        "recommendation_item"
    ]:
        raise RuntimeError("persisted result item count differs from the approved plan")
    stored_coverage = validate_v2_ranked_candidates(
        stored_items,
        graph_version=graph_version,
        require_graph_paths=True,
    )

    chromadb = load_chroma(args.chroma_site_packages.resolve(strict=True))
    collection = chromadb.PersistentClient(
        path=str(args.chroma_path.resolve(strict=True))
    ).get_collection(NAMESPACE_NAME, embedding_function=None)
    chroma_before = int(collection.count())
    if chroma_before != int(g4_baseline["chroma_count_before"]):
        raise RuntimeError("Chroma count differs from the approved baseline")
    graph = Neo4jGraphReader(
        endpoint=f"http://127.0.0.1:{graph_port}/db/neo4j/tx/commit",
        username=graph_user,
        password=graph_password,
        timeout=3,
    )
    vector = ChromaVectorReader(
        collection=collection,
        namespace_name=NAMESPACE_NAME,
        embedding_version=EMBEDDING_VERSION,
        index_version=INDEX_VERSION,
        dimension=CHROMA_DIMENSION,
        timeout=8,
    )
    settings = build_settings(
        values,
        enable_deepseek_intent=False,
        enable_deepseek_explanation=False,
        llm_settings=None,
    )
    service = build_research_g4_recommendation_service(
        settings,
        dataset_version="lib-books-v1-20260810",
        graph=graph,
        graph_version=graph_version,
        vector=vector,
        query_embedder=HashCharNgramQueryEmbedder(),
        embedding_version=EMBEDDING_VERSION,
        index_version=INDEX_VERSION,
        enable_llm_provider=False,
        enable_llm_intent_provider=False,
        enable_llm_explanation_provider=False,
        deadline_seconds=120.0,
    )
    application = build_research_g4_http_app(
        settings, recommendation_service=service
    )
    request_id = str(request_payload["request_id"])
    user_id = int(request_payload["user_id"])
    http_payload = {
        "request_id": request_id,
        "session_id": str(request_payload["session_id"]),
        "user_id": user_id,
        "scene": str(request_payload["scene"]),
        "input_text": str(request_payload["input_text"]),
        "requested_resource_types": list(request_payload["requested_resource_types"]),
        "requested_output_type": str(request_payload["requested_output_type"]),
        "source_resource_id": None,
        "source_item_id": None,
        "as_of_time": None,
        "constraints": {},
        "limit": int(request_payload["limit"]),
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": request_id,
        "X-Demo-User-Id": str(user_id),
    }
    with TestClient(application) as client:
        replay = client.post(
            "/api/v1/recommendation-tasks", json=http_payload, headers=headers
        )
        status = client.get(
            f"/api/v1/recommendation-tasks/{task_facts['task_id']}",
            headers={"X-Demo-User-Id": str(user_id)},
        )
    if replay.status_code != 200 or replay.headers.get("Idempotency-Replayed") != "true":
        raise RuntimeError("approved request did not replay the committed task")
    replay_payload = replay.json()
    replay_items = replay_payload.get("items")
    if not isinstance(replay_items, list):
        raise RuntimeError("idempotent replay omitted the public result items")
    replay_coverage = validate_v2_http_items(
        replay_items,
        graph_version=graph_version,
        require_graph_paths=True,
    )
    if _internal_graph_refs(stored_items) != _public_graph_refs(replay_items):
        raise RuntimeError("stored and replayed v2 graph path references differ")
    if status.status_code != 200:
        raise RuntimeError("task status readback failed")
    status_summary = validate_persisted_status_projection(
        replay_payload, status.json()
    )
    replay_table_names, counts_after_replay = await read_table_counts(values)
    if table_names != replay_table_names or counts_before_replay != counts_after_replay:
        raise RuntimeError("idempotent reconciliation replay changed MySQL counts")
    chroma_after = int(collection.count())
    if chroma_after != chroma_before:
        raise RuntimeError("idempotent reconciliation replay changed Chroma")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"reconciliation directory already exists: {evidence_dir}")
    evidence = {
        "schema_version": "stage2-v2-projection-postcommit-reconciliation-v1",
        "status": "PASS",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "recovery_reason": "APPEND_COMMITTED_BEFORE_STATUS_SHAPE_POSTFLIGHT",
        "approved_plan_id": args.plan_id,
        "approved_plan_hash": args.approved_plan_hash,
        "plan_path": str(resolve_inside_root(args.plan, label="ChangePlan")),
        "plan_git_commit": plan_commit,
        "reconciliation_git_commit": current_commit,
        "plan_commit_is_ancestor": True,
        "request_id": request_id,
        "task_facts": task_facts,
        "target_before_counts": target_before,
        "target_after_counts": target_after,
        "target_deltas": target_deltas,
        "approved_append_rows": sum(target_deltas.values()),
        "baseline_graph_path_coverage": baseline_coverage,
        "stored_graph_path_coverage": stored_coverage,
        "replay_graph_path_coverage": replay_coverage,
        "persisted_status_summary": status_summary,
        "agent_receipts": agent_receipts,
        "graph_version": graph_version,
        "graph_source": graph_source,
        "graph_state": graph_state,
        "chroma_count_before": chroma_before,
        "chroma_count_after": chroma_after,
        "replay_status_code": replay.status_code,
        "idempotency_replayed": True,
        "reconciliation_database_writes": 0,
        "reconciliation_neo4j_writes": 0,
        "reconciliation_chroma_writes": 0,
        "deepseek_requests": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "containers_deleted": 0,
        "volumes_deleted": 0,
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
    parser.add_argument("--mysql-baseline", type=Path, required=True)
    parser.add_argument("--g4-baseline", type=Path, required=True)
    parser.add_argument("--request-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument(
        "--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets"
    )
    parser.add_argument(
        "--graph-env-file",
        type=Path,
        default=PROJECT_ROOT / ".env.neo4j-readonly-final.local",
    )
    parser.add_argument("--chroma-path", type=Path, default=PROJECT_ROOT / "data/chroma")
    parser.add_argument(
        "--chroma-site-packages",
        type=Path,
        default=PROJECT_ROOT
        / ".venv-chroma-g6-20260811/lib/python3.11/site-packages",
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
        subprocess.SubprocessError,
    ) as exc:
        print(
            "[FAIL] Stage 2 post-commit reconciliation did not complete: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "run_id": evidence["run_id"],
                "approved_plan_id": evidence["approved_plan_id"],
                "approved_append_rows": evidence["approved_append_rows"],
                "graph_path_coverage": evidence["replay_graph_path_coverage"],
                "reconciliation_database_writes": 0,
                "deepseek_requests": 0,
                "actual_delete_count": 0,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
