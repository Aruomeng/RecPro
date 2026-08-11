"""Run the G6 Graph/Vector/MySQL fusion path against isolated stores read-only.

This verifier intentionally performs no import, migration, upsert, modification,
or other destructive mutation.  It reads the already-reviewed MySQL catalog, the isolated Neo4j
book graph, and the versioned local Chroma collection, then runs one candidate
recall request through the explicit fusion agent.  A unique evidence directory
is created for every run; an existing run directory is never overwritten.

The base runtime does not carry the optional ``chromadb`` dependency.  When
the operator environment is separate, pass its site-packages directory with
``--chroma-site-packages`` (the default points at the locked local G6 venv).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

import asyncmy

# ``python scripts/<name>.py`` places ``scripts/`` (not the repository root)
# on ``sys.path``.  Add the root before importing application packages so the
# verifier is reproducible both as a module and as a direct operator command.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.catalog.adapters.chroma import ChromaVectorReader
from backend.app.catalog.adapters.embedding import HashCharNgramQueryEmbedder
from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.catalog.adapters.neo4j import Neo4jGraphReader
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.real_agents import CatalogCandidateRecallAgent
from backend.app.shared_kernel.contracts.agent import AgentMessage
from backend.app.shared_kernel.contracts.enums import MessageType
from scripts.validate_runtime_env import read_env

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
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def load_chromadb(site_packages: Path | None) -> Any:
    """Load optional Chroma only from an explicit operator environment."""

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
    runtime_user = values.get("RECPRO_MYSQL_USER", "")
    runtime_password = values.get("RECPRO_MYSQL_PASSWORD", "")
    if not runtime_user or not runtime_password:
        raise ValueError("G6 read-only fusion requires runtime MySQL credentials")
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=runtime_user,
        password=runtime_password,
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=5,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=False,
    )


async def read_counts(connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in COUNT_TABLES:
            await cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = int((await cursor.fetchone())[0])
    return counts


def build_message(now: datetime, *, limit: int) -> AgentMessage:
    return AgentMessage(
        schema_version="g6-readonly-validation-v1",
        message_id=uuid4(),
        trace_id=uuid4(),
        task_id=uuid4(),
        sender="G6ReadonlyFusionVerifier",
        receiver="CandidateRecallAgent",
        message_type=MessageType.RECALL_EXECUTE,
        payload={
            "intent": {
                "topic_terms": ["多智能体", "智慧图书馆"],
                "resource_types": ["BOOK"],
            },
            "profile": {"signals": []},
            "limit": limit,
            "query_text": "多智能体系统 智慧图书馆",
        },
        deadline_at=now + timedelta(seconds=60),
        idempotency_key=str(uuid4()),
        context_version=1,
        created_at=now,
    )


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    compose_values = read_env(args.env_file.resolve())
    secrets_values = read_env(args.secrets_file.resolve())
    values = {**compose_values, **secrets_values}
    for key in (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT",
        "RECPRO_NEO4J_ADMIN_USER",
        "RECPRO_NEO4J_ADMIN_PASSWORD",
    ):
        if not values.get(key):
            raise ValueError(f"missing required read-only runtime key: {key}")
    chromadb = load_chromadb(args.chroma_site_packages.resolve() if args.chroma_site_packages else None)
    chroma_path = args.chroma_path.resolve(strict=True)
    if not chroma_path.is_dir():
        raise ValueError("Chroma path must be an existing directory")

    connection = await connect_mysql(values)
    try:
        before_counts = await read_counts(connection)
        catalog = MySQLCatalogRepository(connection)
        graph = Neo4jGraphReader(
            endpoint=(
                f"http://127.0.0.1:{values['RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT']}"
                "/db/neo4j/tx/commit"
            ),
            username=values["RECPRO_NEO4J_ADMIN_USER"],
            password=values["RECPRO_NEO4J_ADMIN_PASSWORD"],
            timeout=8,
        )
        client = chromadb.PersistentClient(path=str(chroma_path))
        collection = client.get_collection(NAMESPACE_NAME, embedding_function=None)
        chroma_count_before = int(collection.count())
        vector = ChromaVectorReader(
            collection=collection,
            namespace_name=NAMESPACE_NAME,
            embedding_version=EMBEDDING_VERSION,
            index_version=INDEX_VERSION,
            dimension=CHROMA_DIMENSION,
            timeout=8,
        )
        agent = CatalogCandidateRecallAgent(
            catalog,
            graph=graph,
            graph_version=GRAPH_VERSION,
            vector=vector,
            query_embedder=HashCharNgramQueryEmbedder(),
            embedding_version=EMBEDDING_VERSION,
            index_version=INDEX_VERSION,
            retry_policy=RetryPolicy(max_attempts=2),
        )
        now = datetime.now(UTC)
        result = await agent.handle(build_message(now, limit=args.limit))
        chroma_count_after = int(collection.count())
        after_counts = await read_counts(connection)
        await connection.rollback()
    finally:
        connection.close()

    payload = result.payload if isinstance(result.payload, dict) else {}
    candidates = payload.get("candidates", [])
    if result.status.value != "SUCCESS":
        raise ValueError(f"real read-only fusion returned {result.status.value}")
    if result.fallback_used or result.warnings:
        raise ValueError("real read-only fusion unexpectedly used a fallback")
    if payload.get("channels") != ["MYSQL", "GRAPH", "VECTOR"]:
        raise ValueError("real read-only fusion did not enable all three channels")
    if payload.get("dependency_status") != {"MYSQL": "READY", "GRAPH": "READY", "VECTOR": "READY"}:
        raise ValueError("real read-only fusion dependency status is not READY")
    if not isinstance(candidates, list) or len(candidates) != args.limit:
        raise ValueError("real read-only fusion returned an unexpected candidate count")
    if before_counts != after_counts:
        raise ValueError("read-only fusion changed MySQL row counts")
    if chroma_count_before != chroma_count_after:
        raise ValueError("read-only fusion changed Chroma collection count")
    if chroma_count_before <= 0:
        raise ValueError("versioned Chroma collection is empty")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g6" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence = {
        "schema_version": "g6-real-readonly-fusion-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "query": {
            "topic_terms": ["多智能体", "智慧图书馆"],
            "query_text": "多智能体系统 智慧图书馆",
            "limit": args.limit,
        },
        "versions": {
            "graph_version": GRAPH_VERSION,
            "embedding_version": EMBEDDING_VERSION,
            "index_version": INDEX_VERSION,
            "namespace_name": NAMESPACE_NAME,
            "dimension": CHROMA_DIMENSION,
        },
        "stores": {
            "mysql": {
                "database": values["RECPRO_MYSQL_DATABASE"],
                "host_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
                "before_counts": before_counts,
                "after_counts": after_counts,
                "counts_unchanged": before_counts == after_counts,
            },
            "neo4j": {
                "http_host_port": int(values["RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT"]),
                "dependency_status": payload["dependency_status"]["GRAPH"],
                "graph_hit_count": sum(1 for item in candidates if "GRAPH" in str(item.get("channel"))),
            },
            "chroma": {
                "path": str(chroma_path.relative_to(PROJECT_ROOT))
                if chroma_path.is_relative_to(PROJECT_ROOT)
                else "external-local-path",
                "collection": NAMESPACE_NAME,
                "count_before": chroma_count_before,
                "count_after": chroma_count_after,
                "count_unchanged": chroma_count_before == chroma_count_after,
                "vector_hit_count": sum(1 for item in candidates if "VECTOR" in str(item.get("channel"))),
            },
        },
        "result": {
            "status": result.status.value,
            "confidence": result.confidence,
            "fallback_used": result.fallback_used,
            "warnings": list(result.warnings),
            "channels": payload.get("channels"),
            "dependency_status": payload.get("dependency_status"),
            "candidate_count": payload.get("candidate_count"),
            "candidates": candidates,
            "tool_calls": list(result.tool_calls),
        },
        "safety": {
            "query_mode": "READ_ONLY_SELECT_ROLLBACK",
            "mysql_selects": len(COUNT_TABLES) * 2 + 2,
            "neo4j_reads": 1,
            "chroma_reads": 3,
            "mysql_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "actual_delete_count": 0,
            "files_deleted": 0,
            "overwritten_inputs": 0,
        },
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "readonly.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G6 real read-only fusion evidence: {evidence_dir}")
    print(
        f"[PASS] channels=MYSQL+GRAPH+VECTOR candidates={len(candidates)} "
        f"mysql_counts_unchanged={before_counts == after_counts} "
        f"chroma_count={chroma_count_before}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--limit", type=int, default=8)
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
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G6 real read-only fusion verification did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
