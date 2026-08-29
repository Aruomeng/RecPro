#!/usr/bin/env python3
"""Build a zero-connection ChangePlan for an additive read-only Neo4j replica."""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from scripts.import_book_graph import (
    PROJECT_ROOT,
    canonical_json,
    sha256_bytes,
    verify_plan,
)


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
V1_DIR = PROJECT_ROOT / "artifacts/verification/book-graph/lib-graph-plan-20260810-002"
V2_DIR = PROJECT_ROOT / "artifacts/verification/book-graph-v2/lib-books-v2-20260828"
COMPOSE_FILE = PROJECT_ROOT / "compose.neo4j-readonly.yaml"
EXECUTOR = PROJECT_ROOT / "scripts/execute_neo4j_readonly_replica_plan.py"
IMAGE = "neo4j:5.26.28-community@sha256:362542416de6c09a971484d1893878016cc3b5cdec166e54b1c824a220ecd6b9"
PROJECT_NAME = "recpro-neo4j-readonly-20260829"
VOLUME_NAME = "recpro_neo4j_readonly_20260829_data"
HTTP_PORT = 62748
BOLT_PORT = 62768


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _input_hashes() -> dict[str, str]:
    paths = (
        COMPOSE_FILE,
        PROJECT_ROOT / "scripts/import_book_graph.py",
        PROJECT_ROOT / "scripts/build_neo4j_readonly_replica_plan.py",
        EXECUTOR,
        V1_DIR / "graph-plan.json",
        V1_DIR / "nodes.jsonl",
        V1_DIR / "triples.jsonl",
        V2_DIR / "graph-plan.json",
        V2_DIR / "nodes.jsonl",
        V2_DIR / "triples.jsonl",
    )
    return {
        path.relative_to(PROJECT_ROOT).as_posix(): sha256_bytes(path.read_bytes())
        for path in paths
    }


def build_plan(*, reviewed_commit: str, created_at: str) -> dict[str, object]:
    if COMMIT_PATTERN.fullmatch(reviewed_commit) is None:
        raise ValueError("reviewed commit must be a full lowercase Git SHA")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must include an explicit timezone")
    v1_plan, v1_nodes, v1_triples = verify_plan(V1_DIR)
    v2_plan, v2_nodes, v2_triples = verify_plan(V2_DIR)
    if v1_plan.get("graph_version") != "lib-books-v1-20260810":
        raise ValueError("unexpected frozen v1 graph version")
    if v2_plan.get("graph_version") != "lib-books-v2-20260828":
        raise ValueError("unexpected frozen v2 graph version")
    input_hashes = _input_hashes()
    identity = f"{PROJECT_NAME}:{VOLUME_NAME}:{HTTP_PORT}:{BOLT_PORT}"
    plan: dict[str, object] = {
        "schema_version": "recpro-neo4j-readonly-replica-plan-v1",
        "plan_id": str(uuid5(
            NAMESPACE_URL,
            f"recpro:neo4j-readonly-replica:{reviewed_commit}:{identity}",
        )),
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S2_INFRA_APPEND",
        "mode": "APPLY",
        "intent": (
            "Create one new isolated Neo4j Community container and one new volume, "
            "append the frozen v1 and v2 graph artifacts, then enforce data-database "
            "read-only mode before the endpoint may be used by the research runtime. "
            "The existing library Neo4j container, volume, users, nodes, relationships, "
            "constraints, ports, and configuration remain unchanged."
        ),
        "replica": {
            "project_name": PROJECT_NAME,
            "service_name": "neo4j-readonly",
            "volume_name": VOLUME_NAME,
            "image": IMAGE,
            "http_host": "127.0.0.1",
            "http_port": HTTP_PORT,
            "bolt_port": BOLT_PORT,
            "database": "neo4j",
            "credential_user": "neo4j",
            "credential_file": ".env.neo4j-readonly.local",
            "normal_start_mode": "READ_ONLY",
        },
        "graph_append": {
            "v1": {"nodes": len(v1_nodes), "relationships": len(v1_triples)},
            "v2": {"nodes": len(v2_nodes), "relationships": len(v2_triples)},
            "total_nodes": len(v1_nodes) + len(v2_nodes),
            "total_relationships": len(v1_triples) + len(v2_triples),
            "schema_statements_max": 18,
        },
        "source_guard": {
            "v1_nodes": 63388,
            "v1_relationships": 191865,
            "v2_nodes": 78129,
            "v2_relationships": 206848,
            "must_remain_unchanged": True,
        },
        "input_hashes": dict(sorted(input_hashes.items())),
        "maximum_changes": {
            "new_containers": 1,
            "new_volumes": 1,
            "new_secret_files": 1,
            "replica_nodes": len(v1_nodes) + len(v2_nodes),
            "replica_relationships": len(v1_triples) + len(v2_triples),
            "runtime_configuration_changes": 2,
            "existing_graph_changes": 0,
            "deepseek_requests": 0,
            "mysql_rows": 0,
            "chroma_records": 0,
        },
        "preconditions": [
            f"reviewed commit is exactly {reviewed_commit} and the tracked worktree is clean",
            "the user approves this exact plan_id and canonical plan_hash before Docker, credentials, or any network connection is used",
            "the replica project, container, volume, ports, and secret file are all absent before the first action",
            "the existing source graph contains the exact frozen v1 and v2 counts immediately before apply",
            "all tracked executor, Compose, and graph artifact hashes match input_hashes",
            "the replica starts read-only and is made temporarily writable only through the system database after identity checks",
            "the temporary writable exception is removed in a fail-safe finally block and normal-start read-only configuration remains enabled",
            "the endpoint is accepted only after v1/v2 counts match and the writable exception is empty",
            "failure recovery is forward-only; no container, volume, file, graph fact, or constraint is deleted or replaced",
        ],
        "safety": {
            "file_deletions": 0,
            "database_deletions": 0,
            "container_deletions": 0,
            "volume_deletions": 0,
            "existing_container_changes": 0,
            "existing_volume_changes": 0,
            "source_graph_writes": 0,
            "deepseek_requests": 0,
        },
    }
    plan["plan_hash"] = sha256(canonical_json(plan).encode()).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-commit")
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args(argv)
    plan = build_plan(
        reviewed_commit=args.reviewed_commit or git_commit(),
        created_at=args.created_at,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
