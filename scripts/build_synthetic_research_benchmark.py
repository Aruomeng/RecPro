#!/usr/bin/env python3
"""Build an immutable synthetic reader benchmark from the local catalogue.

This generator is for prototype demonstrations, integration tests, and
development-only mechanism experiments when no consented reader interactions
or human relevance labels are available.  It creates deterministic anonymous
simulated readers and metadata-derived proxy judgments.  Its manifest always
states ``SYNTHETIC`` and ``confirmation_eligible=false``.

It never opens MySQL, Neo4j, Chroma, an OIDC provider, or an LLM, and it only
creates a brand-new output directory with exclusive-create semantics.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence

try:
    from scripts.evaluation_runtime import (
        PROJECT_ROOT, reserve_directory, sha256_file, validate_safe_id,
        write_json_exclusive, write_jsonl_exclusive,
    )
    from scripts.prepare_evaluation_split import build_tasks, read_catalog
except ModuleNotFoundError:  # direct ``python scripts/...`` invocation
    from evaluation_runtime import (  # type: ignore[no-redef]
        PROJECT_ROOT, reserve_directory, sha256_file, validate_safe_id,
        write_json_exclusive, write_jsonl_exclusive,
    )
    from prepare_evaluation_split import build_tasks, read_catalog  # type: ignore[no-redef]


def _fraction(*parts: object) -> float:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int(sha256(payload).hexdigest()[:12], 16) / float(0xFFFFFFFFFFFF)


def _timestamp(index: int) -> str:
    # Fixed synthetic time window; it is deliberately unrelated to real use.
    day, minute = divmod(index, 24 * 60)
    return f"2026-01-{1 + day:02d}T{minute // 60:02d}:{minute % 60:02d}:00.000Z"


def build_benchmark(
    resources: list[dict[str, Any]], *, user_count: int, interactions_per_user: int, seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not 8 <= user_count <= 10_000:
        raise ValueError("synthetic user count must be between 8 and 10000")
    if not 3 <= interactions_per_user <= 100:
        raise ValueError("synthetic interactions per user must be between 3 and 100")
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for resource in resources:
        by_topic.setdefault(str(resource["topic"]), []).append(resource)
    topics = [topic for topic, rows in sorted(by_topic.items()) if len(rows) >= interactions_per_user]
    if len(topics) < 2:
        raise ValueError("catalogue lacks enough topic diversity for a synthetic benchmark")
    for rows in by_topic.values():
        rows.sort(key=lambda row: (str(row["external_id"]), int(row["resource_id"])))

    users: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    event_index = 0
    for index in range(user_count):
        research_id = f"synthetic-u-{index + 1:04d}"
        preference = topics[int(_fraction(seed, research_id, "topic") * len(topics)) % len(topics)]
        secondary = topics[(topics.index(preference) + 1 + int(_fraction(seed, research_id, "secondary") * (len(topics) - 1))) % len(topics)]
        users.append({
            "user_research_id": research_id,
            "origin": "SYNTHETIC_SIMULATOR",
            "preference_topics": [preference, secondary],
            "contains_personal_data": False,
        })
        rows = by_topic[preference]
        selected: list[dict[str, Any]] = []
        for offset in range(interactions_per_user):
            selected.append(rows[(index * interactions_per_user + offset) % len(rows)])
        judgments: list[dict[str, Any]] = []
        for offset, resource in enumerate(selected):
            affinity = _fraction(seed, research_id, resource["external_id"])
            positive = affinity >= 0.28
            event_type = "FAVORITE" if positive and affinity >= 0.62 else "BORROW" if positive else "NOT_INTERESTED"
            events.append({
                "event_id": f"synthetic-event-{index + 1:04d}-{offset + 1:03d}-exposure",
                "user_research_id": research_id,
                "resource_id": int(resource["resource_id"]),
                "event_type": "EXPOSURE",
                "occurred_at": _timestamp(event_index),
                "origin": "SYNTHETIC_SIMULATOR",
            })
            event_index += 1
            events.append({
                "event_id": f"synthetic-event-{index + 1:04d}-{offset + 1:03d}-outcome",
                "user_research_id": research_id,
                "resource_id": int(resource["resource_id"]),
                "event_type": event_type,
                "occurred_at": _timestamp(event_index),
                "origin": "SYNTHETIC_SIMULATOR",
            })
            event_index += 1
            judgments.append({
                "resource_id": int(resource["resource_id"]),
                "relevance": 3 if positive else 0,
                "graph_hops": 1,
                "label_origin": "SYNTHETIC_METADATA_PROXY",
            })
        tasks.append({
            "task_id": f"synthetic-task-{index + 1:04d}",
            "user_research_id": research_id,
            "query": f"{preference} 主题的入门阅读与进阶资源",
            "entity_type": "TOPIC",
            "entity_key": preference,
            "expected_output_type": "READING_PATH" if index % 3 == 0 else "TOPIC_RESOURCES",
            "expected_delivery_strategy": "CLARIFY" if index % 7 == 0 else "DIRECT",
            "evaluation_at": _timestamp(event_index),
            "judgments": judgments,
            "label_origin": "SYNTHETIC_METADATA_PROXY",
        })
    return users, events, tasks


def execute(
    catalog_root: Path, output: Path, *, dataset_version: str, user_count: int,
    interactions_per_user: int, seed: int, write: bool,
) -> dict[str, Any]:
    resources, source_files = read_catalog(catalog_root.resolve())
    users, events, tasks = build_benchmark(
        resources, user_count=user_count, interactions_per_user=interactions_per_user, seed=seed,
    )
    plan = {
        "schema_version": "synthetic-research-benchmark-v1",
        "classification": "SYNTHETIC_DEVELOPMENT_ONLY",
        "confirmation_eligible": False,
        "dataset_version": validate_safe_id(dataset_version, label="dataset version"),
        "seed": seed,
        "source": {"kind": "curated_catalogue_metadata", "contains_personal_data": False},
        "assumptions": [
            "reader preferences are deterministic simulated topic affinities",
            "outcome events are not observed reader behavior",
            "relevance is metadata-derived proxy labeling, not human annotation",
        ],
        "counts": {"resources": len(resources), "anonymous_users": len(users), "events": len(events), "tasks": len(tasks)},
        "input_catalogue_sha256": sha256_file(catalog_root.resolve() / "T-工业技术" / "推荐系统.csv") if (catalog_root.resolve() / "T-工业技术" / "推荐系统.csv").is_file() else None,
        "source_files": [
            {"path": str(item["path"]), "sha256": item["sha256"], "bytes": item["bytes"]}
            for item in source_files
        ],
        "database_reads": 0,
        "database_writes": 0,
        "deepseek_requests": 0,
        "deletions": 0,
    }
    if not write:
        return plan
    reserve_directory(output)
    outputs = {}
    for name, rows in (("resources", resources), ("synthetic_users", users), ("synthetic_events", events), ("synthetic_tasks", tasks)):
        count, digest = write_jsonl_exclusive(output / f"{name}.jsonl", rows)
        outputs[name] = {"path": f"{name}.jsonl", "count": count, "sha256": digest}
    manifest = {**plan, "output": ".", "frozen": True, "files": outputs}
    write_json_exclusive(output / "manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-root", type=Path, default=PROJECT_ROOT / "Lib")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-version", default="lib-synthetic-research-v1")
    parser.add_argument("--users", type=int, default=120)
    parser.add_argument("--interactions-per-user", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument("--write", action="store_true", help="create one new immutable output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute(
            args.catalog_root, args.output, dataset_version=args.dataset_version,
            user_count=args.users, interactions_per_user=args.interactions_per_user,
            seed=args.seed, write=args.write,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[FAIL] synthetic benchmark was not built: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
