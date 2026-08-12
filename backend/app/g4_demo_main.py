"""Explicit local G4 HTTP entrypoint for the research workbench.

The module-level ``backend.app.main:app`` and the Compose backend remain
health-only.  This entrypoint is deliberately separate and fail-closed: it
requires the demo environment, the G4 switch, an existing operator-validated
Chroma collection, and the isolated library Neo4j credentials before it
constructs the version-pinned Graph/Vector runtime.  DeepSeek intent
classification requires its own validated capability switch.
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.app.catalog.runtime.g4_ports import build_g4_readonly_runtime
from backend.app.composition import build_research_g4_http_app_from_runtime
from backend.app.config import load_configuration
from scripts.g4_operator_runtime import load_existing_chroma_collection


GRAPH_VERSION = "lib-books-v1-20260810"
EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"
NAMESPACE_NAME = "library_resources__hash_char_ngram_v1"
CHROMA_DIMENSION = 384
DEFAULT_CHROMA_PATH = Path("data/chroma")
DEFAULT_CHROMA_SITE_PACKAGES = Path(
    ".venv-chroma-g6-20260811/lib/python3.11/site-packages"
)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"G4 HTTP entrypoint requires {name}")
    return value


def _bounded_deadline() -> float:
    raw = os.environ.get("RECPRO_G4_DEADLINE_SECONDS", "120")
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("RECPRO_G4_DEADLINE_SECONDS must be numeric") from exc
    if not 30.0 <= value <= 300.0:
        raise RuntimeError("RECPRO_G4_DEADLINE_SECONDS must be between 30 and 300")
    return value


def create_g4_app():
    if os.environ.get("RECPRO_APP_ENV", "").strip().lower() != "demo":
        raise RuntimeError("G4 HTTP entrypoint requires RECPRO_APP_ENV=demo")
    if os.environ.get("RECPRO_G4_HTTP_ENABLED", "").strip().lower() != "true":
        raise RuntimeError("G4 HTTP entrypoint requires RECPRO_G4_HTTP_ENABLED=true")

    state = load_configuration()
    if not state.is_valid:
        raise RuntimeError(
            f"G4 HTTP entrypoint rejected invalid configuration: {state.error_code}"
        )
    settings = state.settings
    if not settings.g4_http_enabled:
        raise RuntimeError("G4 HTTP entrypoint requires the validated G4 switch")

    chroma_path = Path(
        os.environ.get("RECPRO_G4_CHROMA_PATH", str(DEFAULT_CHROMA_PATH))
    )
    site_packages = Path(
        os.environ.get(
            "RECPRO_G4_CHROMA_SITE_PACKAGES", str(DEFAULT_CHROMA_SITE_PACKAGES)
        )
    )
    loaded = load_existing_chroma_collection(
        chroma_path=chroma_path,
        collection_name=NAMESPACE_NAME,
        expected_metadata={
            "recpro_namespace_name": NAMESPACE_NAME,
            "recpro_graph_version": GRAPH_VERSION,
            "recpro_embedding_version": EMBEDDING_VERSION,
            "recpro_index_version": INDEX_VERSION,
            "hnsw:space": "cosine",
        },
        expected_count=None,
        site_packages=site_packages,
    )

    graph_port = _required("RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT")
    runtime = build_g4_readonly_runtime(
        graph_endpoint=f"http://127.0.0.1:{graph_port}/db/neo4j/tx/commit",
        graph_username=_required("RECPRO_NEO4J_ADMIN_USER"),
        graph_password=_required("RECPRO_NEO4J_ADMIN_PASSWORD"),
        chroma_collection=loaded.collection,
        graph_version=GRAPH_VERSION,
        embedding_version=EMBEDDING_VERSION,
        index_version=INDEX_VERSION,
        namespace_name=NAMESPACE_NAME,
        dimension=CHROMA_DIMENSION,
        timeout=8.0,
    )
    return build_research_g4_http_app_from_runtime(
        settings,
        runtime=runtime,
        enable_llm_provider=False,
        enable_llm_intent_provider=settings.g4_llm_intent_enabled,
        deadline_seconds=_bounded_deadline(),
    )


app = create_g4_app()


__all__ = ["app", "create_g4_app"]
