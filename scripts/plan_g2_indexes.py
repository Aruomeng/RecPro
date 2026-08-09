"""Create an insert-only, versioned index build plan for optional stores."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import asyncmy

from backend.app.catalog.application.public import plan_index_builds
from backend.app.catalog.domain.models import ResourceSummary
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def _json_array(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


async def read_resources(connection: Any) -> tuple[ResourceSummary, ...]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT id, resource_type, external_id, title, authors_json, abstract_text, "
            "keywords_json, category_code, publication_year, availability_status, "
            "available_from, access_url, metadata_quality, is_classic, metadata_version, "
            "language, difficulty_level FROM resource_catalog "
            "WHERE availability_status <> 'REMOVED' ORDER BY id"
        )
        rows = await cursor.fetchall()
    return tuple(
        ResourceSummary(
            id=int(row[0]),
            resource_type=str(row[1]),
            external_id=str(row[2]),
            title=str(row[3]),
            authors=_json_array(row[4]),
            abstract_text=str(row[5]) if row[5] is not None else None,
            keywords=_json_array(row[6]),
            category_code=str(row[7]) if row[7] is not None else None,
            publication_year=int(row[8]) if row[8] is not None else None,
            availability_status=str(row[9]),
            available_from=row[10],
            access_url=str(row[11]) if row[11] is not None else None,
            metadata_quality=float(row[12]),
            is_classic=bool(row[13]),
            metadata_version=int(row[14]),
            language=str(row[15]) if row[15] is not None else None,
            difficulty_level=int(row[16]) if row[16] is not None else None,
        )
        for row in rows
    )


async def plan_and_apply(
    *,
    host_port: int,
    database: str,
    migration_user: str,
    migration_password: str,
    index_version: str = "g2-index-v1",
    apply: bool = True,
) -> dict[str, object]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=host_port,
        user=migration_user,
        password=migration_password,
        db=database,
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=not apply,
    )
    try:
        resources = await read_resources(connection)
        plans = plan_index_builds(resources, index_version=index_version)
        now = datetime.now(UTC).replace(tzinfo=None)
        inserted_builds = 0
        inserted_outbox = 0
        if apply:
            async with connection.cursor() as cursor:
                if not plans:
                    await connection.commit()
                    return {
                        "index_version": index_version,
                        "resource_count": len(resources),
                        "plan_count": 0,
                        "target_counts": {"VECTOR": 0, "GRAPH": 0},
                        "plan_sha256": hashlib.sha256(b"[]").hexdigest(),
                        "applied": False,
                        "inserted_build_count": 0,
                        "inserted_outbox_count": 0,
                        "destructive_actions": 0,
                        "external_store_writes": 0,
                    }
                build_placeholders = ",".join("%s" for _ in plans)
                await cursor.execute(
                    f"SELECT id FROM resource_index_build WHERE id IN ({build_placeholders})",
                    tuple(plan.build_id for plan in plans),
                )
                existing_build_ids = {str(row[0]) for row in await cursor.fetchall()}
                resource_ids = tuple(sorted({plan.resource_id for plan in plans}))
                resource_placeholders = ",".join("%s" for _ in resource_ids)
                await cursor.execute(
                    "SELECT resource_id, target, operation, metadata_version "
                    "FROM resource_index_outbox WHERE resource_id IN ("
                    + resource_placeholders
                    + ") AND operation = 'UPSERT'",
                    resource_ids,
                )
                existing_outbox_keys = {
                    (int(row[0]), str(row[1]), str(row[2]), int(row[3]))
                    for row in await cursor.fetchall()
                }
                for plan in plans:
                    if plan.build_id not in existing_build_ids:
                        await cursor.execute(
                            "INSERT IGNORE INTO resource_index_build "
                            "(id, resource_id, target, index_version, metadata_version, content_hash, namespace_name, status, created_at, state_version) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'PLANNED', %s, 1)",
                            (plan.build_id, plan.resource_id, plan.target, plan.index_version, plan.metadata_version, plan.content_hash, plan.namespace_name, now),
                        )
                        inserted_builds += 1
                    outbox_key = (plan.resource_id, plan.target, "UPSERT", plan.metadata_version)
                    if outbox_key not in existing_outbox_keys:
                        await cursor.execute(
                            "INSERT IGNORE INTO resource_index_outbox "
                            "(resource_id, target, operation, metadata_version, status, attempts, created_at, updated_at) "
                            "VALUES (%s, %s, 'UPSERT', %s, 'PENDING', 0, %s, %s)",
                            (plan.resource_id, plan.target, plan.metadata_version, now, now),
                        )
                        inserted_outbox += 1
            await connection.commit()
        return {
            "index_version": index_version,
            "resource_count": len(resources),
            "plan_count": len(plans),
            "target_counts": {
                "VECTOR": sum(1 for item in plans if item.target == "VECTOR"),
                "GRAPH": sum(1 for item in plans if item.target == "GRAPH"),
            },
            "plan_sha256": hashlib.sha256(
                json.dumps([plan.__dict__ if hasattr(plan, "__dict__") else {
                    "build_id": plan.build_id,
                    "resource_id": plan.resource_id,
                    "target": plan.target,
                    "index_version": plan.index_version,
                    "metadata_version": plan.metadata_version,
                    "content_hash": plan.content_hash,
                    "namespace_name": plan.namespace_name,
                } for plan in plans], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "applied": bool(apply and (inserted_builds or inserted_outbox)),
            "inserted_build_count": inserted_builds,
            "inserted_outbox_count": inserted_outbox,
            "destructive_actions": 0,
            "external_store_writes": 0,
        }
    except Exception:
        if apply:
            await connection.rollback()
        raise
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--index-version", default="g2-index-v1")
    parser.add_argument("--apply", action="store_true")
    return parser


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not user or not password:
        raise ValueError("G2 migration credentials are required")
    result = await plan_and_apply(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        migration_user=user,
        migration_password=password,
        index_version=args.index_version,
        apply=args.apply,
    )
    path = PROJECT_ROOT / "artifacts" / "verification" / "g2" / run_id / "index-plan.json"
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps({"schema_version": "g2-index-plan-evidence-v1", "run_id": run_id, **result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] G2 index plan: {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G2 index plan did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
