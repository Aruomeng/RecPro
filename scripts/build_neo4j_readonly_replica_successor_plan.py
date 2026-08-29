#!/usr/bin/env python3
"""Build a zero-connection fail-forward Neo4j replica successor plan."""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import re
import subprocess
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from scripts.build_neo4j_readonly_replica_plan import IMAGE, PROJECT_ROOT, V1_DIR, V2_DIR, VOLUME_NAME
from scripts.execute_neo4j_readonly_replica_plan import _canonical_hash
from scripts.execute_neo4j_readonly_replica_successor import CONTAINER_NAME, dry_run_report
from scripts.import_book_graph import sha256_bytes, verify_plan


REQUIRED_INPUTS = (
    "scripts/import_book_graph.py",
    "scripts/execute_neo4j_readonly_replica_successor.py",
    "scripts/build_neo4j_readonly_replica_successor_plan.py",
    "artifacts/verification/book-graph/lib-graph-plan-20260810-002/graph-plan.json",
    "artifacts/verification/book-graph/lib-graph-plan-20260810-002/nodes.jsonl",
    "artifacts/verification/book-graph/lib-graph-plan-20260810-002/triples.jsonl",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/graph-plan.json",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/nodes.jsonl",
    "artifacts/verification/book-graph-v2/lib-books-v2-20260828/triples.jsonl",
)


def build_plan(
    *, reviewed_commit: str, created_at: str, container_id: str,
    config_sha256: str, log_volume_name: str,
) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{40}", reviewed_commit) is None:
        raise ValueError("reviewed commit must be a full lowercase Git SHA")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must include timezone")
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None or re.fullmatch(r"[0-9a-f]{64}", config_sha256) is None:
        raise ValueError("container or configuration identity is malformed")
    if re.fullmatch(r"[0-9a-f]{64}", log_volume_name) is None:
        raise ValueError("anonymous log volume identity is malformed")
    _, v1_nodes, v1_triples = verify_plan(V1_DIR)
    _, v2_nodes, v2_triples = verify_plan(V2_DIR)
    plan: dict[str, object] = {
        "schema_version": "recpro-neo4j-readonly-replica-successor-plan-v1",
        "plan_id": str(uuid5(
            NAMESPACE_URL,
            f"recpro:neo4j-replica-successor:{reviewed_commit}:{container_id}:{config_sha256}",
        )),
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S2_INFRA_APPEND_FAIL_FORWARD",
        "mode": "APPLY",
        "intent": (
            "Resume the exact Community-edition partial state without cleanup or recreation. "
            "Temporarily replace the generated configuration of the same already-created "
            "replica container, restart it writable, append only frozen v1/v2 graph facts, "
            "restore the byte-identical original configuration in a finally block, and restart "
            "read-only. The source graph and every existing container, volume, database, and "
            "historical fact remain unchanged."
        ),
        "partial_state": {
            "container_name": CONTAINER_NAME,
            "container_id": container_id,
            "container_image": IMAGE,
            "container_status": "running/healthy",
            "data_volume_name": VOLUME_NAME,
            "log_volume_name": log_volume_name,
            "credential_file": ".env.neo4j-readonly.local",
            "credential_file_mode": "0600",
            "database_status": "offline/read-only",
            "replica_graph_import_started": False,
            "config_sha256": config_sha256,
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
            "container_config_replacements": 2,
            "same_container_restarts": 2,
            "replica_nodes": len(v1_nodes) + len(v2_nodes),
            "replica_relationships": len(v1_triples) + len(v2_triples),
            "new_containers": 0, "new_volumes": 0, "new_secret_files": 0,
            "source_graph_changes": 0, "mysql_rows": 0,
            "chroma_records": 0, "deepseek_requests": 0,
        },
        "input_hashes": {
            relative: sha256_bytes((PROJECT_ROOT / relative).read_bytes())
            for relative in REQUIRED_INPUTS
        },
        "dry_run": dry_run_report(),
        "preconditions": [
            "the user approves this exact successor plan_id and plan_hash before Docker or database access",
            "the exact existing replica container, named data volume, anonymous log volume, credential file mode, image digest, and generated config hash match partial_state",
            "the source v1/v2 graph counts match source_guard immediately before apply",
            "after the first same-container restart the replica is read-write and both graph-version counts are exactly zero",
            "the finally block always restores the byte-identical original config and restarts the same container read-only",
            "acceptance requires exact replica counts, unchanged source counts, original config hash, and empty writable setting",
            "failure recovery remains forward-only; no cleanup, replacement, overwrite of graph facts, or deletion is allowed",
        ],
        "safety": {
            "file_deletions": 0, "database_deletions": 0,
            "container_deletions": 0, "volume_deletions": 0,
            "new_containers": 0, "new_volumes": 0, "new_secret_files": 0,
            "source_graph_writes": 0, "deepseek_requests": 0,
        },
    }
    plan["plan_hash"] = _canonical_hash(plan)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-commit")
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--container-id", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--log-volume-name", required=True)
    args = parser.parse_args(argv)
    reviewed = args.reviewed_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    print(json.dumps(build_plan(
        reviewed_commit=reviewed, created_at=args.created_at,
        container_id=args.container_id, config_sha256=args.config_sha256,
        log_volume_name=args.log_volume_name,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
