#!/usr/bin/env python3
"""Build the exact, zero-connection ChangePlan for the additive graph v2 import."""

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

from scripts.import_book_graph import PROJECT_ROOT, canonical_json, load_json, sha256_bytes, verify_plan


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TARGET_VERSION = "lib-books-v2-20260828"
SOURCE_VERSION = "lib-books-v1-20260810"
SOURCE_NODE_COUNT = 63_388
SOURCE_RELATIONSHIP_COUNT = 191_865


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def build_plan(
    *,
    reviewed_commit: str,
    created_at: str,
    graph_dir: Path,
) -> dict[str, object]:
    if COMMIT_PATTERN.fullmatch(reviewed_commit) is None:
        raise ValueError("reviewed commit must be a full lowercase Git SHA")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must include an explicit timezone")
    resolved_graph_dir = graph_dir.resolve(strict=True)
    try:
        graph_relative = resolved_graph_dir.relative_to(PROJECT_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("graph artifacts must be inside the repository") from exc
    graph_plan, nodes, triples = verify_plan(resolved_graph_dir)
    if graph_plan.get("schema_version") != "book-graph-plan-v2":
        raise ValueError("ChangePlan requires a verified v2 graph plan")
    if graph_plan.get("graph_version") != TARGET_VERSION:
        raise ValueError("unexpected graph v2 version")
    graph_plan_path = resolved_graph_dir / "graph-plan.json"
    graph_plan_hash = sha256_bytes(graph_plan_path.read_bytes())
    input_hashes = {
        "scripts/build_book_graph_v2.py": sha256_bytes((PROJECT_ROOT / "scripts/build_book_graph_v2.py").read_bytes()),
        "scripts/build_book_graph_v2_change_plan.py": sha256_bytes((PROJECT_ROOT / "scripts/build_book_graph_v2_change_plan.py").read_bytes()),
        "scripts/import_book_graph.py": sha256_bytes((PROJECT_ROOT / "scripts/import_book_graph.py").read_bytes()),
        f"{graph_relative}/graph-plan.json": graph_plan_hash,
        f"{graph_relative}/nodes.jsonl": sha256_bytes((resolved_graph_dir / "nodes.jsonl").read_bytes()),
        f"{graph_relative}/triples.jsonl": sha256_bytes((resolved_graph_dir / "triples.jsonl").read_bytes()),
        f"{graph_relative}/review-proposals.jsonl": sha256_bytes((resolved_graph_dir / "review-proposals.jsonl").read_bytes()),
    }
    plan_id = str(uuid5(
        NAMESPACE_URL,
        f"recpro:neo4j-v2:{reviewed_commit}:{graph_plan_hash}",
    ))
    plan: dict[str, object] = {
        "schema_version": "recpro-neo4j-v2-change-plan-v1",
        "plan_id": plan_id,
        "created_at": parsed.isoformat().replace("+00:00", "Z"),
        "git_commit": reviewed_commit,
        "classification": "S1_APPEND",
        "mode": "APPLY",
        "intent": (
            "Append the independently versioned lib-books-v2 graph into the existing isolated "
            "RecPro Neo4j database. Preserve every v1 node, relationship, and constraint; create "
            "no Item nodes and persist no knowledge-review proposals."
        ),
        "graph_append": {
            "graph_version": TARGET_VERSION,
            "source_graph_version": SOURCE_VERSION,
            "graph_plan_path": f"{graph_relative}/graph-plan.json",
            "graph_plan_sha256": graph_plan_hash,
            "nodes": len(nodes),
            "relationships": len(triples),
            "works": int(graph_plan["target"]["works"]),
            "instance_of": int(graph_plan["target"]["instance_of"]),
            "items": 0,
            "review_proposals_persisted": 0,
        },
        "source_v1_guard": {
            "graph_version": SOURCE_VERSION,
            "nodes": SOURCE_NODE_COUNT,
            "relationships": SOURCE_RELATIONSHIP_COUNT,
        },
        "input_hashes": dict(sorted(input_hashes.items())),
        "maximum_changes": {
            "nodes": len(nodes),
            "relationships": len(triples),
            "schema_statements": 9,
            "deepseek_requests": 0,
            "mysql_rows": 0,
            "chroma_records": 0,
        },
        "preconditions": [
            f"reviewed implementation commit {reviewed_commit} remains an ancestor of execution and the tracked working tree is clean",
            "the user approves this unchanged plan_id and canonical plan_hash before credentials are read or a network client is created",
            "all graph artifact and executor hashes match input_hashes",
            "the live immutable v1 graph contains exactly 63388 nodes and 191865 relationships before the first write",
            "the target lib-books-v2-20260828 version contains exactly zero nodes and zero relationships before the first write",
            "only CREATE CONSTRAINT IF NOT EXISTS plus MERGE/ON CREATE append statements are allowed",
            "post-import v2 counts must be exactly 78129 nodes and 206848 relationships",
            "post-import v1 counts must equal their pre-import counts exactly",
            "failure recovery is forward-only; no compensating delete, drop, detach, remove, or overwrite is allowed",
        ],
        "safety": {
            "v1_node_delta": 0,
            "v1_relationship_delta": 0,
            "database_deletions": 0,
            "file_deletions": 0,
            "deepseek_requests": 0,
            "container_changes": 0,
            "volume_changes": 0,
        },
    }
    plan["plan_hash"] = sha256(canonical_json(plan).encode()).hexdigest()
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-commit")
    parser.add_argument("--created-at", required=True)
    parser.add_argument(
        "--graph-dir", type=Path,
        default=PROJECT_ROOT / "artifacts/verification/book-graph-v2/lib-books-v2-20260828",
    )
    args = parser.parse_args(argv)
    try:
        plan = build_plan(
            reviewed_commit=args.reviewed_commit or git_commit(),
            created_at=args.created_at,
            graph_dir=args.graph_dir,
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
