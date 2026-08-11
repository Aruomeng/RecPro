"""Preflight the opt-in G4 HTTP composition with GET/read-only operations.

This command is intentionally separate from the default backend and from all
business POST paths.  It loads an existing Chroma collection, constructs the
version-pinned Graph/Vector runtime and G4 HTTP app in memory, then calls only
``/health/live`` and ``/health/ready`` through an in-process ASGI client.  The
ready probe performs its documented MySQL SELECT/SHOW GRANTS checks.  No G4
task is created, no Neo4j recall is issued, and no DeepSeek request is sent.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

import asyncmy
from fastapi.testclient import TestClient
from pydantic import SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.catalog.runtime.g4_ports import build_g4_readonly_runtime
from backend.app.composition import build_research_g4_http_app_from_runtime
from backend.app.config import AppSettings
from scripts.g4_operator_runtime import load_existing_chroma_collection
from scripts.validate_runtime_env import read_env, validate_compose


GRAPH_VERSION = "lib-books-v1-20260810"
EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"
NAMESPACE_NAME = "library_resources__hash_char_ngram_v1"
CHROMA_DIMENSION = 384
EXPECTED_CHROMA_COUNT = 14983
COUNT_TABLES = (
    "resource_catalog",
    "resource_book_detail",
    "tag_dictionary",
    "resource_tag",
    "resource_index_state",
    "recommendation_task",
    "recommendation_item",
    "recommendation_record",
    "recommendation_agent_message",
    "recommendation_agent_result",
    "recommendation_agent_artifact",
    "recommendation_orchestration_result",
)


def _settings(values: dict[str, str]) -> AppSettings:
    """Build an in-memory demo setting without changing any env file."""

    return AppSettings(
        app_env="demo",
        app_version="g4-host-readonly-preflight",
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


async def _connect(values: dict[str, str]) -> Any:
    return await asyncmy.connect(
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


async def _counts(connection: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    async with connection.cursor() as cursor:
        for table in COUNT_TABLES:
            await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError(f"count query returned no row for {table}")
            result[table] = int(row[0])
    return result


def _required(values: dict[str, str]) -> None:
    keys = (
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
    missing = [key for key in keys if not values.get(key)]
    if missing:
        raise ValueError(f"missing required host preflight keys: {missing}")


async def execute(args: argparse.Namespace) -> int:
    if not args.confirm_readonly:
        raise ValueError("pass --confirm-readonly to run the GET/SELECT-only host preflight")
    compose_values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secret_values = read_env(args.secrets_file.resolve(strict=True))
    values = {**compose_values, **secret_values}
    _required(values)
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
        expected_count=EXPECTED_CHROMA_COUNT,
        site_packages=args.chroma_site_packages,
    )
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
    settings = _settings(values)
    application = build_research_g4_http_app_from_runtime(
        settings,
        runtime=runtime,
        enable_llm_provider=False,
        deadline_seconds=120.0,
    )

    connection = await _connect(values)
    try:
        before_counts = await _counts(connection)
    finally:
        connection.close()
    with TestClient(application) as client:
        live = client.get("/api/v1/health/live")
        ready = client.get("/api/v1/health/ready")
    connection = await _connect(values)
    try:
        after_counts = await _counts(connection)
    finally:
        connection.close()
    chroma_after = int(loaded.collection.count())

    if live.status_code != 200:
        raise RuntimeError(f"G4 host liveness returned {live.status_code}")
    if ready.status_code != 200:
        raise RuntimeError(f"G4 host readiness returned {ready.status_code}: {ready.text}")
    ready_payload = ready.json()
    if ready_payload.get("can_recommend") is not True:
        raise RuntimeError("G4 host readiness did not expose the explicit opt-in capability")
    if before_counts != after_counts:
        raise RuntimeError("G4 host health-only preflight changed MySQL counts")
    if chroma_after != loaded.count:
        raise RuntimeError("G4 host health-only preflight changed Chroma count")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / args.run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    evidence = {
        "schema_version": "g4-http-host-readonly-preflight-v1",
        "run_id": args.run_id,
        "status": "PASS",
        "created_at": datetime.now(UTC).isoformat(),
        "http": {
            "live_status": live.status_code,
            "ready_status": ready.status_code,
            "can_recommend": ready_payload.get("can_recommend"),
            "business_post_count": 0,
            "in_process_asgi": True,
        },
        "versions": {
            "graph_version": runtime.graph_version,
            "embedding_version": runtime.embedding_version,
            "index_version": runtime.index_version,
            "namespace_name": runtime.namespace_name,
            "dimension": runtime.dimension,
        },
        "chroma": {
            "path": str(loaded.path.relative_to(PROJECT_ROOT))
            if loaded.path.is_relative_to(PROJECT_ROOT)
            else str(loaded.path),
            "collection": loaded.name,
            "count_before": loaded.count,
            "count_after": chroma_after,
            "metadata": dict(loaded.metadata),
        },
        "mysql": {
            "counts_before": before_counts,
            "counts_after": after_counts,
            "counts_unchanged": before_counts == after_counts,
        },
        "safety": {
            "mysql_reads": len(COUNT_TABLES) * 2 + 2,
            "mysql_writes": 0,
            "neo4j_reads": 0,
            "neo4j_writes": 0,
            "chroma_reads": 3,
            "chroma_writes": 0,
            "external_requests": 0,
            "external_llm_requests": 0,
            "actual_delete_count": 0,
            "files_deleted": 0,
            "overwritten_inputs": 0,
        },
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "readonly.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G4 HTTP host read-only preflight evidence: {evidence_dir}")
    print(
        f"[PASS] live={live.status_code} ready={ready.status_code} "
        f"can_recommend={ready_payload.get('can_recommend')} "
        f"mysql_unchanged={before_counts == after_counts} chroma_count={chroma_after}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--confirm-readonly", action="store_true")
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
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G4 HTTP host preflight did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
