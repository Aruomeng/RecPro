"""Run the real G4 Agent graph against isolated stores using reads only.

This verifier exercises the full port-backed orchestrator with the imported
MySQL catalog/profile projection, the isolated Neo4j graph, and the versioned
Chroma collection.  It never migrates, seeds, inserts, updates, deletes,
upserts, or commits a database transaction; the MySQL session is rolled back
after the orchestration read path completes.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.catalog.adapters.chroma import ChromaVectorReader
from backend.app.catalog.adapters.embedding import HashCharNgramQueryEmbedder
from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.catalog.adapters.neo4j import Neo4jGraphReader
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from scripts.validate_runtime_env import read_env, validate_compose


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
GRAPH_VERSION = "lib-books-v1-20260810"
EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"
NAMESPACE_NAME = "library_resources__hash_char_ngram_v1"
CHROMA_DIMENSION = 384
COUNT_TABLES = (
    "resource_catalog",
    "resource_book_detail",
    "tag_dictionary",
    "resource_tag",
    "resource_index_state",
    "recommendation_agent_message",
    "recommendation_agent_result",
    "recommendation_agent_artifact",
    "recommendation_orchestration_result",
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def load_chromadb(site_packages: Path | None) -> Any:
    if site_packages is not None:
        resolved = site_packages.resolve(strict=True)
        if str(resolved) not in sys.path:
            sys.path.insert(0, str(resolved))
    try:
        import chromadb
    except ModuleNotFoundError as exc:  # pragma: no cover - operator setup
        raise RuntimeError(
            "chromadb is unavailable; pass --chroma-site-packages for the locked operator venv"
        ) from exc
    return chromadb


async def connect_mysql(values: dict[str, str]) -> Any:
    if not values.get("RECPRO_MYSQL_USER") or not values.get("RECPRO_MYSQL_PASSWORD"):
        raise ValueError("G4 read-only fusion requires runtime MySQL credentials")
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=90,
        charset="utf8mb4",
        autocommit=False,
    )


async def read_counts(connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in COUNT_TABLES:
            await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError(f"count query returned no row for {table}")
            counts[table] = int(row[0])
    return counts


def build_request(
    run_id: str,
    *,
    user_id: int,
    now: datetime,
    input_text: str,
    resource_types: tuple[str, ...],
    output_type: str,
    limit: int,
) -> OrchestrationRequest:
    task_id = uuid5(NAMESPACE_URL, f"g4-readonly-fusion-task:{run_id}")
    trace_id = uuid5(NAMESPACE_URL, f"g4-readonly-fusion-trace:{run_id}")
    session_id = uuid5(NAMESPACE_URL, f"g4-readonly-fusion-session:{run_id}")
    return OrchestrationRequest(
        task_id=task_id,
        trace_id=trace_id,
        session_id=session_id,
        user_id=user_id,
        input_text=input_text,
        resource_types=resource_types,
        output_type=output_type,
        limit=limit,
        constraints={},
        evaluation_at=now,
        deadline_at=now + timedelta(seconds=90),
    )


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    compose_values = read_env(args.env_file.resolve())
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secrets_values = read_env(args.secrets_file.resolve())
    values = {**compose_values, **secrets_values}
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
    chromadb = load_chromadb(
        args.chroma_site_packages.resolve() if args.chroma_site_packages else None
    )
    chroma_path = args.chroma_path.resolve(strict=True)
    if not chroma_path.is_dir():
        raise ValueError("Chroma path must be an existing directory")

    connection = await connect_mysql(values)
    try:
        before_counts = await read_counts(connection)
        chroma_client = chromadb.PersistentClient(path=str(chroma_path))
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
        )
        now = datetime.now(UTC)
        resource_types = tuple(args.resource_type or ("BOOK",))
        request = build_request(
            run_id,
            user_id=args.user_id,
            now=now,
            input_text=args.input_text,
            resource_types=resource_types,
            output_type=args.output_type,
            limit=args.limit,
        )
        first = await orchestrator.run(request)
        second = await orchestrator.run(request)
        chroma_after = int(collection.count())
        after_counts = await read_counts(connection)
        await connection.rollback()
    finally:
        connection.close()

    if first.status.value not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise ValueError(f"G4 read-only orchestration returned {first.status.value}")
    if len(first.dispatches) != 7:
        raise ValueError("G4 read-only orchestration did not dispatch seven Agents")
    if first.payload != second.payload or first.trace != second.trace:
        raise ValueError("G4 read-only orchestration was not deterministic")
    if before_counts != after_counts:
        raise ValueError("G4 read-only orchestration changed MySQL row counts")
    if chroma_before != chroma_after:
        raise ValueError("G4 read-only orchestration changed Chroma count")
    if chroma_before <= 0:
        raise ValueError("versioned Chroma collection is empty")

    recall = next(item for item in first.dispatches if item.message.receiver == "CandidateRecallAgent")
    recall_payload = recall.result.payload if isinstance(recall.result.payload, dict) else {}
    candidates = recall_payload.get("candidates", [])
    if not isinstance(candidates, list) or len(candidates) != args.limit:
        raise ValueError("G4 read-only orchestration returned an unexpected candidate count")
    channels = recall_payload.get("channels")
    if channels != ["MYSQL", "GRAPH", "VECTOR"]:
        raise ValueError(f"G4 read-only orchestration channels are not fully enabled: {channels!r}")
    required_projection_fields = {
        "channel_scores",
        "channel_ranks",
        "primary_channel",
        "evidence_confidence",
    }
    if any(
        not isinstance(candidate, dict)
        or not required_projection_fields.issubset(candidate)
        for candidate in candidates
    ):
        raise ValueError(
            "G4 read-only candidates are missing the projection fields required by MySQL writer"
        )
    candidate_channel_counts: Counter[str] = Counter()
    candidate_persistence_rows = 0
    for candidate in candidates:
        channel = candidate.get("channel")
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("G4 read-only candidate channel is invalid")
        parts = tuple(part.strip().upper() for part in channel.split("+"))
        if not parts or any(not part for part in parts) or len(set(parts)) != len(parts):
            raise ValueError("G4 read-only candidate channel components are invalid")
        candidate_channel_counts.update(parts)
        candidate_persistence_rows += len(parts)

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    dispatch_summary = [
        {
            "receiver": item.message.receiver,
            "agent_version": item.result.agent_version,
            "status": item.result.status.value,
            "confidence": item.result.confidence,
            "warnings": list(item.result.warnings),
            "fallback_used": item.result.fallback_used,
        }
        for item in first.dispatches
    ]
    evidence = {
        "schema_version": "g4-real-readonly-fusion-runtime-v1",
        "run_id": run_id,
        "status": "PASS",
        "task_id": str(first.task_id),
        "trace_id": str(first.trace_id),
        "orchestration_status": first.status.value,
        "dispatch_count": len(first.dispatches),
        "candidate_count": len(candidates),
        "channels": channels,
        "query_spec": {
            "input_text": args.input_text,
            "resource_types": list(resource_types),
            "output_type": args.output_type,
            "limit": args.limit,
        },
        "candidate_channel_counts": dict(sorted(candidate_channel_counts.items())),
        "candidate_persistence_rows": candidate_persistence_rows,
        "candidate_enrichment": {
            "channel_scores": True,
            "channel_ranks": True,
            "primary_channel": True,
            "evidence_confidence": True,
        },
        "versions": {
            "graph_version": GRAPH_VERSION,
            "embedding_version": EMBEDDING_VERSION,
            "index_version": INDEX_VERSION,
            "namespace_name": NAMESPACE_NAME,
            "dimension": CHROMA_DIMENSION,
        },
        "dispatches": dispatch_summary,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "chroma_count_before": chroma_before,
        "chroma_count_after": chroma_after,
        "safety": {
            "mysql_mode": "SELECT_ONLY_ROLLBACK",
            "mysql_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "external_requests": 0,
            "actual_delete_count": 0,
            "files_deleted": 0,
            "overwritten_inputs": 0,
        },
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "readonly.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G4 real read-only fusion evidence: {evidence_dir}")
    print(
        f"[PASS] dispatches={len(first.dispatches)} candidates={len(candidates)} "
        f"channels={'+'.join(channels)} mysql_unchanged={before_counts == after_counts} "
        f"chroma_count={chroma_before}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--input-text", default="多智能体 智慧图书馆")
    parser.add_argument("--resource-type", action="append", default=None)
    parser.add_argument("--output-type", default="TOPIC_RESOURCES")
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
    if not 1 <= args.limit <= 20:
        raise SystemExit("--limit must be between 1 and 20")
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G4 real read-only fusion verification did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
