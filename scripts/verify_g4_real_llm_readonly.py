#!/usr/bin/env python3
"""Run one explicitly approved G4 read-only orchestration with real Intent LLM.

The verifier proves the configured DeepSeek provider is actually selected by
the port-backed G4 Agent graph.  It sends one fixed, non-sensitive fixture to
``intent.classify``; Explanation remains the deterministic evidence template
so this probe cannot multiply external requests over the ranked items.  The
catalog, profile, graph, and vector dependencies are read-only and the
MySQL transaction is always rolled back before the connection closes.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Sequence

import asyncmy

from backend.app.config import AppSettings
from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from backend.app.llm.factory import build_llm_provider
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g4_readonly_fusion_runtime import (
    CHROMA_DIMENSION,
    EMBEDDING_VERSION,
    GRAPH_VERSION,
    INDEX_VERSION,
    NAMESPACE_NAME,
    build_request,
    connect_mysql,
    load_chromadb,
    read_counts,
    validate_run_id,
)
from backend.app.catalog.adapters.chroma import ChromaVectorReader
from backend.app.catalog.adapters.embedding import HashCharNgramQueryEmbedder
from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.catalog.adapters.neo4j import Neo4jGraphReader
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ID = "g4-real-llm-intent-readonly-v1"
FIXTURE_TEXT = "多智能体 智慧图书馆"
CONFIRMATION = "YES_REAL_EXTERNAL_LLM"
LIMIT = 8
USER_ID = 1001
OUTPUT_TYPE = "TOPIC_RESOURCES"


def _write_report(run_id: str, report: dict[str, Any]) -> Path:
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output_path = evidence_dir / "real-llm-readonly.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return output_path


def _settings(path: Path) -> AppSettings:
    settings = AppSettings(_env_file=str(path.resolve()))
    if settings.app_env == "production":
        raise ValueError("real LLM read-only probe cannot run with production app_env")
    if settings.llm_provider != "deepseek":
        raise ValueError("real LLM read-only probe requires RECPRO_LLM_PROVIDER=deepseek")
    return settings


def _tool_call_counts(dispatches: Sequence[Any]) -> dict[str, int]:
    counts = {"mysql": 0, "neo4j": 0, "chroma": 0}
    for dispatch in dispatches:
        for call in dispatch.result.tool_calls:
            operation = str(call.get("operation", ""))
            if operation.startswith("catalog.graph_"):
                counts["neo4j"] += 1
            elif operation.startswith("catalog.vector_"):
                counts["chroma"] += 1
            elif operation.startswith("catalog.") or operation.startswith("profile."):
                counts["mysql"] += 1
    return counts


async def execute(
    *,
    run_id: str,
    confirmation: str,
    compose_env_file: Path,
    secrets_file: Path,
    llm_env_file: Path,
    chroma_path: Path,
    chroma_site_packages: Path | None,
) -> dict[str, Any]:
    if confirmation != CONFIRMATION:
        raise ValueError("an exact confirmation is required for the external call")
    run_id = validate_run_id(run_id)

    compose_values = read_env(compose_env_file.resolve())
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secret_values = read_env(secrets_file.resolve())
    values = {**compose_values, **secret_values}
    required = (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT",
        "RECPRO_NEO4J_ADMIN_USER",
        "RECPRO_NEO4J_ADMIN_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required read-only runtime keys: {missing}")

    settings = _settings(llm_env_file)
    provider = build_llm_provider(settings)
    if not isinstance(provider, DeepSeekLLMProvider):
        raise ValueError("configured provider was not DeepSeekLLMProvider")

    chromadb = load_chromadb(chroma_site_packages.resolve() if chroma_site_packages else None)
    resolved_chroma_path = chroma_path.resolve(strict=True)
    if not resolved_chroma_path.is_dir():
        raise ValueError("Chroma path must be an existing directory")

    connection = await connect_mysql(values)
    before_counts: dict[str, int] | None = None
    after_counts: dict[str, int] | None = None
    chroma_before: int | None = None
    chroma_after: int | None = None
    result: Any | None = None
    started = time.monotonic()
    try:
        before_counts = await read_counts(connection)
        chroma_client = chromadb.PersistentClient(path=str(resolved_chroma_path))
        collection = chroma_client.get_collection(NAMESPACE_NAME, embedding_function=None)
        chroma_before = int(collection.count())
        graph = Neo4jGraphReader(
            endpoint=(
                f"http://127.0.0.1:{values['RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT']}"
                "/db/neo4j/tx/commit"
            ),
            username=values["RECPRO_NEO4J_ADMIN_USER"],
            password=values["RECPRO_NEO4J_ADMIN_PASSWORD"],
            timeout=8,
        )
        vector = ChromaVectorReader(
            collection=collection,
            namespace_name=NAMESPACE_NAME,
            embedding_version=EMBEDDING_VERSION,
            index_version=INDEX_VERSION,
            dimension=CHROMA_DIMENSION,
            timeout=8,
        )
        orchestrator = build_port_orchestrator(
            MySQLCatalogRepository(connection),
            MySQLProfileSnapshotReader(connection),
            graph=graph,
            graph_version=GRAPH_VERSION,
            vector=vector,
            query_embedder=HashCharNgramQueryEmbedder(),
            embedding_version=EMBEDDING_VERSION,
            index_version=INDEX_VERSION,
            retry_policy=RetryPolicy(max_attempts=2),
            llm_intent_provider=provider,
        )
        request = build_request(
            run_id,
            user_id=USER_ID,
            now=datetime.now(UTC),
            input_text=FIXTURE_TEXT,
            resource_types=("BOOK",),
            output_type=OUTPUT_TYPE,
            limit=LIMIT,
            deadline_seconds=180.0,
        )
        # Exactly one orchestration is intentional: a second run would be a
        # second external model call and is outside this probe's budget.
        result = await orchestrator.run(request)
        chroma_after = int(collection.count())
        after_counts = await read_counts(connection)
    finally:
        # The adapters expose only SELECT/query operations, but rollback is an
        # additional guard against accidental session state changes.
        await connection.rollback()
        connection.close()

    if result is None or before_counts is None or after_counts is None or chroma_before is None or chroma_after is None:
        raise RuntimeError("G4 real LLM read-only probe did not produce a result")
    if result.status.value not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise ValueError(f"G4 real LLM orchestration returned {result.status.value}")
    if len(result.dispatches) != 7:
        raise ValueError("G4 real LLM orchestration did not dispatch seven Agents")
    if before_counts != after_counts:
        raise ValueError("G4 real LLM orchestration changed MySQL row counts")
    if chroma_before != chroma_after:
        raise ValueError("G4 real LLM orchestration changed Chroma count")
    if chroma_before <= 0:
        raise ValueError("versioned Chroma collection is empty")

    intent_dispatch = next(
        item for item in result.dispatches if item.message.receiver == "IntentUnderstandingAgent"
    )
    if intent_dispatch.result.agent_version != "intent-llm-prompt-v1":
        raise ValueError("G4 Intent Agent did not use the real LLM provider")
    if intent_dispatch.result.fallback_used:
        raise ValueError("G4 Intent Agent unexpectedly used the rule fallback")
    intent_payload = intent_dispatch.result.payload
    intent = intent_payload.get("intent_type")
    if intent not in {"TOPIC_RECOMMENDATION", "GENERAL_RECOMMENDATION"}:
        raise ValueError("G4 Intent Agent returned an unexpected normalized intent")
    llm_attempts = int(intent_payload.get("llm_attempts", 0))
    if not 1 <= llm_attempts <= 2:
        raise ValueError("G4 Intent Agent returned an invalid bounded attempt count")

    recall = next(item for item in result.dispatches if item.message.receiver == "CandidateRecallAgent")
    recall_payload = recall.result.payload if isinstance(recall.result.payload, dict) else {}
    candidates = recall_payload.get("candidates", [])
    if not isinstance(candidates, list) or len(candidates) != LIMIT:
        raise ValueError("G4 real LLM orchestration returned an unexpected candidate count")
    channels = recall_payload.get("channels")
    if channels != ["MYSQL", "GRAPH", "VECTOR"]:
        raise ValueError(f"G4 real LLM orchestration returned invalid channels: {channels!r}")
    tool_counts = _tool_call_counts(result.dispatches)
    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    evidence = {
        "schema_version": "g4-real-llm-readonly-v1",
        "status": "PASS",
        "run_id": run_id,
        "checked_at": datetime.now(UTC).isoformat(),
        "fixture": {
            "fixture_id": FIXTURE_ID,
            "input_sha256": hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest(),
            "input_chars": len(FIXTURE_TEXT),
            "sensitive_user_data": False,
        },
        "orchestration": {
            "task_id": str(result.task_id),
            "trace_id": str(result.trace_id),
            "status": result.status.value,
            "dispatch_count": len(result.dispatches),
            "candidate_count": len(candidates),
            "channels": channels,
            "intent_agent_version": intent_dispatch.result.agent_version,
            "intent_type": intent,
            "intent_fallback_used": intent_dispatch.result.fallback_used,
            "explanation_agent_version": next(
                item.result.agent_version
                for item in result.dispatches
                if item.message.receiver == "ExplanationAgent"
            ),
        },
        "provider": {
            "provider": intent_payload.get("llm_provider"),
            "model": settings.llm_model,
            "base_url_origin": settings.llm_base_url,
            "prompt_id": intent_payload.get("prompt_id"),
            "prompt_version": intent_payload.get("prompt_version"),
            "prompt_sha256": intent_payload.get("prompt_sha256"),
            "attempts": llm_attempts,
            "latency_ms": elapsed_ms,
        },
        "storage": {
            "mysql_before_counts": before_counts,
            "mysql_after_counts": after_counts,
            "chroma_count_before": chroma_before,
            "chroma_count_after": chroma_after,
            "tool_call_counts": tool_counts,
        },
        "safety": {
            "external_llm_requests": llm_attempts,
            "network_requests": llm_attempts,
            "database_reads": len(before_counts) * 2 + tool_counts["mysql"],
            "database_writes": 0,
            "neo4j_reads": tool_counts["neo4j"],
            "neo4j_writes": 0,
            "chroma_reads": 2 + tool_counts["chroma"],
            "chroma_writes": 0,
            "outbox_claims": 0,
            "files_deleted": 0,
            "database_physical_deletions": 0,
            "artifact_overwrites": 0,
        },
    }
    output_path = _write_report(run_id, evidence)
    evidence["artifact_path"] = output_path.relative_to(PROJECT_ROOT).as_posix()
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--compose-env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    parser.add_argument("--llm-env-file", type=Path, default=PROJECT_ROOT / ".env.host")
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
        report = asyncio.run(
            execute(
                run_id=args.run_id,
                confirmation=args.confirm,
                compose_env_file=args.compose_env_file,
                secrets_file=args.secrets_file,
                llm_env_file=args.llm_env_file,
                chroma_path=args.chroma_path,
                chroma_site_packages=args.chroma_site_packages,
            )
        )
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
