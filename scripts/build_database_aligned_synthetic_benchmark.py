#!/usr/bin/env python3
"""Create a synthetic development benchmark from the current MySQL catalogue.

Only catalogue metadata is read.  No user data, behavior, profile, feedback,
MySQL write, graph write, or model request is involved.  Resulting records use
the live ``resource_catalog.id`` values, so a later approved demo import does
not need to guess how a local CSV snapshot maps to the running catalogue.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import asyncmy

from scripts.build_synthetic_research_benchmark import build_benchmark
from scripts.evaluation_runtime import PROJECT_ROOT, reserve_directory, write_json_exclusive, write_jsonl_exclusive
from scripts.validate_runtime_env import read_env


def _port(values: Mapping[str, str]) -> int:
    raw = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    if raw is None or not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise ValueError("a valid MySQL host port is required")
    return int(raw)


async def read_resources(values: Mapping[str, str], *, per_topic: int) -> list[dict[str, Any]]:
    if not 8 <= per_topic <= 128:
        raise ValueError("resources per topic must be between 8 and 128")
    connection = await asyncmy.connect(
        host="127.0.0.1", port=_port(values), user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10, read_timeout=30, charset="utf8mb4", autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, external_id, title, authors_json, COALESCE(category_code, 'UNCATEGORIZED') "
                "FROM resource_catalog WHERE resource_type='BOOK' ORDER BY category_code, id"
            )
            rows = await cursor.fetchall()
    finally:
        connection.close()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        try:
            authors_raw = raw[3].decode("utf-8") if isinstance(raw[3], bytes) else raw[3]
            authors = json.loads(authors_raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            authors = []
        if not isinstance(authors, list):
            authors = []
        topic = str(raw[4])[:120]
        bucket = grouped.setdefault(topic, [])
        if len(bucket) < per_topic:
            bucket.append({
                "resource_id": int(raw[0]), "external_id": str(raw[1]), "title": str(raw[2])[:240],
                "authors": [str(item)[:120] for item in authors[:8]], "topic": topic,
                "category_code": topic, "category_label": topic, "subject_codes": [], "keywords": [],
            })
    return [item for topic in sorted(grouped) for item in grouped[topic] if len(grouped[topic]) >= 8]


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("synthetic benchmark output already exists")
    values = read_env(args.env_file.resolve(strict=True))
    resources = await read_resources(values, per_topic=args.resources_per_topic)
    users, events, tasks = build_benchmark(
        resources, user_count=args.users, interactions_per_user=args.interactions_per_user, seed=args.seed,
    )
    reserve_directory(output)
    files = {}
    for name, rows in (("resources", resources), ("synthetic_users", users), ("synthetic_events", events), ("synthetic_tasks", tasks)):
        count, digest = write_jsonl_exclusive(output / f"{name}.jsonl", rows)
        files[name] = {"path": f"{name}.jsonl", "count": count, "sha256": digest}
    manifest = {
        "schema_version": "synthetic-research-benchmark-v1",
        "classification": "SYNTHETIC_DEVELOPMENT_ONLY", "confirmation_eligible": False,
        "dataset_version": args.dataset_version, "seed": args.seed, "frozen": True, "output": ".",
        "source": {"kind": "mysql_catalogue_metadata_readonly", "contains_personal_data": False},
        "counts": {"resources": len(resources), "anonymous_users": len(users), "events": len(events), "tasks": len(tasks)},
        "assumptions": ["simulated preferences", "simulated outcomes", "metadata proxy labels"],
        "files": files,
        "database_reads": 1, "database_writes": 0, "deepseek_requests": 0, "deletions": 0,
    }
    write_json_exclusive(output / "manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-version", default="mysql-synthetic-research-v1")
    parser.add_argument("--users", type=int, default=120)
    parser.add_argument("--interactions-per-user", type=int, default=8)
    parser.add_argument("--resources-per-topic", type=int, default=64)
    parser.add_argument("--seed", type=int, default=20260901)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(execute(args))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, asyncmy.Error) as exc:
        print(f"[FAIL] database-aligned synthetic benchmark: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
