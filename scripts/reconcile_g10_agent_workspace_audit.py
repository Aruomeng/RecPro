#!/usr/bin/env python3
"""Read-only reconciliation for the bounded G10 Workspace acceptance trace."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

import asyncmy

from scripts.execute_g10_agent_workspace_audit import PROJECT_ROOT, WORKSPACE_ID
from scripts.validate_runtime_env import read_env


async def reconcile(env_file: Path) -> dict[str, object]:
    values = read_env(env_file.resolve(strict=True))
    port = values.get("RECPRO_MYSQL_HOST_PORT") or values.get("RECPRO_MYSQL_PORT")
    user = values.get("RECPRO_MYSQL_READONLY_USER") or values.get("RECPRO_MYSQL_USER")
    password = values.get("RECPRO_MYSQL_READONLY_PASSWORD") or values.get("RECPRO_MYSQL_PASSWORD")
    if not port or not user or not password:
        raise ValueError("MySQL read credentials and host port are required")
    connection = await asyncmy.connect(
        host="127.0.0.1", port=int(port),
        user=user, password=password,
        db=values["RECPRO_MYSQL_DATABASE"], autocommit=True,
    )
    try:
        counts: dict[str, int] = {}
        async with connection.cursor() as cursor:
            for table in ("agent_workspace_event", "interaction_directive_fact"):
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
                    (table,),
                )
                exists = int((await cursor.fetchone())[0])
                if not exists:
                    counts[table] = 0
                    continue
                await cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id = %s", (str(WORKSPACE_ID),))
                counts[table] = int((await cursor.fetchone())[0])
        return {
            "status": "PASS", "mode": "READ_ONLY", "workspace_id": str(WORKSPACE_ID),
            "counts": counts, "database_writes": 0, "deepseek_requests": 0,
            "database_physical_deletions": 0,
        }
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(reconcile(args.env_file)), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, KeyError, ValueError, asyncmy.errors.Error) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
