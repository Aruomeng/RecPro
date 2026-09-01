#!/usr/bin/env python3
"""Read-only reconciliation for a bounded synthetic demo behavior import."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import asyncmy

from scripts.evaluation_runtime import reserve_directory, write_json_exclusive
from scripts.plan_synthetic_demo_behavior_import import build_import_intent
from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def _port(values: Mapping[str, str]) -> int:
    raw = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    if raw is None or not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise ValueError("a valid MySQL host port is required")
    return int(raw)


async def reconcile(
    values: Mapping[str, str], intent: Mapping[str, Any],
) -> dict[str, Any]:
    required = ("RECPRO_MYSQL_DATABASE", "RECPRO_MYSQL_USER", "RECPRO_MYSQL_PASSWORD")
    if any(not values.get(key) for key in required):
        raise ValueError("read-only reconciliation requires configured MySQL runtime credentials")
    resources = tuple(intent["required_readonly_reconciliation"]["resource_external_ids"])
    identities = tuple(intent["required_readonly_reconciliation"]["resource_identities"])
    event_uuids = tuple(intent["required_readonly_reconciliation"]["event_uuids"])
    target_user = int(intent["target"]["user_id"])
    if not 1 <= len(resources) <= 16 or not 1 <= len(event_uuids) <= 32:
        raise ValueError("synthetic reconciliation is outside the bounded import contract")
    connection = await asyncmy.connect(
        host="127.0.0.1", port=_port(values), user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10, read_timeout=30, charset="utf8mb4", autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            placeholders = ",".join("%s" for _ in resources)
            await cursor.execute(
                f"SELECT id, external_id FROM resource_catalog WHERE external_id IN ({placeholders}) ORDER BY external_id",
                resources,
            )
            mapped = {str(row[1]): int(row[0]) for row in await cursor.fetchall()}
            unresolved = [item for item in identities if str(item["external_id"]) not in mapped]
            if unresolved:
                titles = tuple(str(item["title"]) for item in unresolved)
                await cursor.execute(
                    f"SELECT id, external_id, title, authors_json FROM resource_catalog WHERE title IN ({','.join('%s' for _ in titles)})",
                    titles,
                )
                candidates = await cursor.fetchall()
                for identity in unresolved:
                    title = str(identity["title"])
                    expected_authors = {str(value) for value in identity.get("authors", [])}
                    matches: list[int] = []
                    for candidate in candidates:
                        if str(candidate[2]) != title:
                            continue
                        try:
                            raw_authors = candidate[3]
                            authors = json.loads(raw_authors.decode("utf-8") if isinstance(raw_authors, bytes) else raw_authors)
                        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        if isinstance(authors, list) and expected_authors.intersection(str(value) for value in authors):
                            matches.append(int(candidate[0]))
                    if len(matches) == 1:
                        mapped[str(identity["external_id"])] = matches[0]
            await cursor.execute(
                f"SELECT event_uuid FROM user_behavior_event WHERE event_uuid IN ({','.join('%s' for _ in event_uuids)})",
                event_uuids,
            )
            existing = sorted(str(row[0]) for row in await cursor.fetchall())
            await cursor.execute("SELECT COUNT(*) FROM iam_user_account WHERE user_id=%s", (target_user,))
            account_count = int((await cursor.fetchone())[0])
            await cursor.execute("SELECT COUNT(*) FROM user_behavior_event WHERE user_id=%s", (target_user,))
            behavior_before = int((await cursor.fetchone())[0])
        missing = sorted(set(resources) - set(mapped))
        return {
            "resource_mappings": mapped,
            "missing_resource_external_ids": missing,
            "existing_event_uuids": existing,
            "target_authenticated_account_count": account_count,
            "target_behavior_count_before": behavior_before,
            "ready_for_append_plan": not missing and not existing and account_count == 0,
        }
    finally:
        connection.close()


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if _RUN_ID.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    output = PROJECT_ROOT / "artifacts" / "verification" / "synthetic-demo-import" / args.run_id
    if output.exists():
        raise FileExistsError("read-only evidence directory already exists")
    intent = build_import_intent(
        args.benchmark_dir, synthetic_user_id=args.synthetic_user_id, target_user_id=args.target_user_id,
    )
    reconciliation = await reconcile(read_env(args.env_file.resolve(strict=True)), intent)
    evidence = {
        "schema_version": "synthetic-demo-import-reconciliation-v1",
        "status": "PASS" if reconciliation["ready_for_append_plan"] else "BLOCKED",
        "run_id": args.run_id,
        "intent": intent,
        "reconciliation": reconciliation,
        "safety": {"database_reads": 4, "database_writes": 0, "deepseek_requests": 0, "deletions": 0},
    }
    reserve_directory(output)
    write_json_exclusive(output / "reconciliation.json", evidence)
    return evidence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--synthetic-user-id", default="synthetic-u-0001")
    parser.add_argument("--target-user-id", type=int, default=1001)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(execute(args))
    except (OSError, ValueError, KeyError, TypeError, asyncmy.Error) as exc:
        print(f"[FAIL] synthetic demo behavior reconciliation: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
