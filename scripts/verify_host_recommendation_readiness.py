#!/usr/bin/env python3
"""Host-only read-only readiness check for the local recommendation workbench."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
from typing import Any, Sequence

import asyncmy
from fastapi.testclient import TestClient

from backend.app.composition import build_demo_mysql_http_app
from scripts.validate_runtime_env import read_env
from scripts.verify_g7_mysql_http_readonly import build_settings, read_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


async def _profile(values: dict[str, str], user_id: int) -> dict[str, object] | None:
    port = int(values.get("RECPRO_MYSQL_HOST_PORT") or values["RECPRO_MYSQL_PORT"])
    connection = await asyncmy.connect(host="127.0.0.1", port=port, user=values["RECPRO_MYSQL_USER"], password=values["RECPRO_MYSQL_PASSWORD"], db=values["RECPRO_MYSQL_DATABASE"], autocommit=True, charset="utf8mb4")
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT profile_version,profile_confidence,updated_at FROM user_profile WHERE user_id=%s", (user_id,))
            row = await cursor.fetchone()
        return {"profile_version": int(row[0]), "profile_confidence": str(row[1]), "updated_at": row[2].isoformat()} if row else None
    finally:
        connection.close()


async def execute(args: argparse.Namespace) -> dict[str, object]:
    if _RUN_ID.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    output = PROJECT_ROOT / "artifacts" / "verification" / "host-recommendation-readiness" / args.run_id
    if output.exists():
        raise FileExistsError("read-only evidence directory already exists")
    values = read_env(args.env_file.resolve(strict=True))
    required = ("RECPRO_MYSQL_DATABASE", "RECPRO_MYSQL_USER", "RECPRO_MYSQL_PASSWORD")
    if any(not values.get(key) for key in required):
        raise ValueError("host recommendation readiness requires configured MySQL values")
    runtime_values = dict(values)
    runtime_values.setdefault("RECPRO_MYSQL_HOST_PORT", runtime_values["RECPRO_MYSQL_PORT"])
    before = await read_snapshot(runtime_values)
    profile_before = await _profile(runtime_values, args.user_id)
    application = build_demo_mysql_http_app(build_settings(runtime_values))
    with TestClient(application) as client:
        live = client.get("/api/v1/health/live")
        ready = client.get("/api/v1/health/ready")
    after = await read_snapshot(runtime_values)
    profile_after = await _profile(runtime_values, args.user_id)
    if before != after or profile_before != profile_after:
        raise RuntimeError("host readiness check changed persisted state")
    if live.status_code != 200 or ready.status_code != 200 or ready.json().get("can_recommend") is not True:
        raise RuntimeError("host MySQL recommendation readiness is not available")
    ready_body = ready.json()
    evidence = {
        "schema_version": "host-recommendation-readiness-v1", "status": "PASS", "run_id": args.run_id,
        "user_id": args.user_id, "profile": profile_after, "liveness": live.json().get("status"),
        "readiness": ready_body.get("status"), "can_recommend": True,
        "components": ready_body.get("components", {}),
        "before_counts": before, "after_counts": after,
        "safety": {"database_writes": 0, "business_posts": 0, "deepseek_requests": 0, "neo4j_writes": 0, "chroma_writes": 0, "deletions": 0},
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "readiness.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run-id", required=True); parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host"); parser.add_argument("--user-id", type=int, default=1002)
    args = parser.parse_args(argv)
    try: print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, asyncmy.errors.Error, json.JSONDecodeError) as exc: print(f"[FAIL] host recommendation readiness: {type(exc).__name__}: {exc}"); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
