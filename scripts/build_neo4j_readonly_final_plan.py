#!/usr/bin/env python3
"""Build the zero-connection clean final Neo4j replica ChangePlan."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import subprocess
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from scripts.build_neo4j_readonly_replica_plan import IMAGE, PROJECT_ROOT, V1_DIR, V2_DIR
from scripts.execute_neo4j_readonly_final_plan import (
    BOLT_PORT,
    COMPOSE_FILE,
    DATA_VOLUME,
    HTTP_PORT,
    LOG_VOLUME,
    PROJECT_NAME,
    dry_run_report,
)
from scripts.execute_neo4j_readonly_replica_plan import _canonical_hash
from scripts.import_book_graph import sha256_bytes, verify_plan


REQUIRED_INPUTS = (
    "compose.neo4j-readonly-final.yaml",
    "scripts/import_book_graph.py",
    "scripts/execute_neo4j_readonly_final_plan.py",
    "scripts/build_neo4j_readonly_final_plan.py",
    "artifacts/verification/book-graph/lib-graph-plan-20260810-002/graph-plan.json",
    "artifacts/verification/book-graph/lib-graph-plan-20260810-002/nodes.jsonl",
    "artifacts/verification/book-graph/lib-graph-plan-20260810-002/triples.jsonl",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/graph-plan.json",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/nodes.jsonl",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/triples.jsonl",
)


def build_plan(*, reviewed_commit: str, created_at: str) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{40}", reviewed_commit) is None:
        raise ValueError("reviewed commit must be a full lowercase Git SHA")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must include timezone")
    _, v1_nodes, v1_triples = verify_plan(V1_DIR)
    _, v2_nodes, v2_triples = verify_plan(V2_DIR)
    identity = f"{PROJECT_NAME}:{DATA_VOLUME}:{LOG_VOLUME}:{HTTP_PORT}:{BOLT_PORT}"
    plan: dict[str, object] = {
        "schema_version": "recpro-neo4j-readonly-final-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"recpro:neo4j-readonly-final:{reviewed_commit}:{identity}")),
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S2_INFRA_APPEND_CLEAN_REBUILD",
        "mode": "APPLY",
        "intent": (
            "Retain the failed replica and all of its files, containers, and volumes unchanged. "
            "Create one new isolated Community replica with explicit data and log volumes, append "
            "the frozen v1/v2 graph, use a bounded 600-second graceful stop with exit-code validation, "
            "restore the original read-only config, and accept only exact counts and unchanged source."
        ),
        "replica": {
            "project_name": PROJECT_NAME,
            "image": IMAGE,
            "data_volume": DATA_VOLUME,
            "log_volume": LOG_VOLUME,
            "http_port": HTTP_PORT,
            "bolt_port": BOLT_PORT,
            "credential_file": ".env.neo4j-readonly-final.local",
            "normal_start_mode": "READ_ONLY",
        },
        "retained_failed_replica": {
            "container": "recpro-neo4j-readonly-20260829-neo4j-readonly-1",
            "data_volume": "recpro_neo4j_readonly_20260829_data",
            "log_volume": "d598518033332e76743170202e1e62e93ab98525f4b98ca5099add056177dc8a",
            "allowed_changes": 0,
        },
        "graph_append": {
            "v1": {"nodes": len(v1_nodes), "relationships": len(v1_triples)},
            "v2": {"nodes": len(v2_nodes), "relationships": len(v2_triples)},
            "total_nodes": len(v1_nodes) + len(v2_nodes),
            "total_relationships": len(v1_triples) + len(v2_triples),
            "schema_statements_max": 18,
        },
        "source_guard": {
            "v1_nodes": 63388, "v1_relationships": 191865,
            "v2_nodes": 78129, "v2_relationships": 206848,
            "must_remain_unchanged": True,
        },
        "maximum_changes": {
            "new_containers": 1,
            "new_volumes": 2,
            "new_secret_files": 1,
            "controlled_container_stops": 2,
            "controlled_container_starts_after_create": 2,
            "container_config_replacements": 2,
            "replica_nodes": len(v1_nodes) + len(v2_nodes),
            "replica_relationships": len(v1_triples) + len(v2_triples),
            "source_graph_changes": 0,
            "failed_replica_changes": 0,
            "mysql_rows": 0,
            "chroma_records": 0,
            "deepseek_requests": 0,
        },
        "input_hashes": {
            relative: sha256_bytes((PROJECT_ROOT / relative).read_bytes())
            for relative in REQUIRED_INPUTS
        },
        "dry_run": dry_run_report(),
        "preconditions": [
            "the user approves this exact plan_id and plan_hash before Docker or database access",
            "the new project, ports, named volumes, and credential file are absent",
            "the failed replica and both of its volumes remain unchanged",
            "the source v1/v2 counts match source_guard immediately before apply",
            "the new container has exactly two explicit named mounts and no anonymous volume",
            "the graph is exactly empty before append and matches frozen counts before final stop",
            "the post-import stop waits up to 600 seconds and requires exit code zero without OOM",
            "the endpoint is accepted only after original config restoration, read-only online state, exact replica counts, and unchanged source counts",
            "failure recovery is forward-only; no container, volume, file, database, log, graph fact, or constraint is deleted or replaced",
        ],
        "safety": {
            "file_deletions": 0,
            "database_deletions": 0,
            "container_deletions": 0,
            "volume_deletions": 0,
            "failed_replica_changes": 0,
            "source_graph_writes": 0,
            "deepseek_requests": 0,
        },
    }
    plan["plan_hash"] = _canonical_hash(plan)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-commit")
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args(argv)
    reviewed = args.reviewed_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    print(json.dumps(build_plan(reviewed_commit=reviewed, created_at=args.created_at), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
