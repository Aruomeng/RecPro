#!/usr/bin/env python3
"""Read-only preflight for the formal reader feedback/profile boundary.

This command deliberately does not log in, send a business POST, claim an
Outbox row, or call an external model.  It inspects the selected authenticated
reader, recommendation item, current consent and profile projection so a
later append-only ChangePlan can be generated only after the reader has
explicitly granted ``BEHAVIOR_LEARNING``.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, date
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import asyncmy

from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def _row(columns: Sequence[str], values: Sequence[Any]) -> dict[str, Any]:
    return {name: _json_value(value) for name, value in zip(columns, values, strict=True)}


def _resolve_inside_root(path: Path) -> Path:
    candidate = path if path.is_absolute() else PROJECT_ROOT / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("output must stay inside the repository") from exc
    return resolved


async def _connect(values: Mapping[str, str]) -> Any:
    host = values.get("RECPRO_MYSQL_HOST", "127.0.0.1")
    port = int(values.get("RECPRO_MYSQL_PORT", "3306"))
    return await asyncmy.connect(
        host=host,
        port=port,
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=60,
        charset="utf8mb4",
        autocommit=True,
    )


async def _snapshot(connection: Any) -> tuple[tuple[str, ...], dict[str, int]]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() ORDER BY table_name"
        )
        names = tuple(str(row[0]) for row in await cursor.fetchall())
        if any(TABLE_PATTERN.fullmatch(name) is None for name in names):
            raise ValueError("database returned an unsafe table identifier")
        counts: dict[str, int] = {}
        for name in names:
            await cursor.execute(f"SELECT COUNT(*) FROM `{name}`")
            counts[name] = int((await cursor.fetchone())[0])
    return names, counts


async def _read_target(
    connection: Any, *, user_id: int, task_id: str, record_id: int, item_id: int, resource_id: int,
) -> dict[str, Any]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT id, user_id, trigger_scene, status, context_version "
            "FROM recommendation_task WHERE id = %s",
            (task_id,),
        )
        task_row = await cursor.fetchone()
        await cursor.execute(
            "SELECT id, task_id, user_id, context_version, output_type "
            "FROM recommendation_record WHERE id = %s",
            (record_id,),
        )
        record_row = await cursor.fetchone()
        await cursor.execute(
            "SELECT ri.id, ri.record_id, ri.resource_id, ri.rank_no, rc.resource_type, rc.title, "
            "rr.task_id, rr.user_id FROM recommendation_item ri "
            "JOIN recommendation_record rr ON rr.id = ri.record_id "
            "JOIN resource_catalog rc ON rc.id = ri.resource_id WHERE ri.id = %s",
            (item_id,),
        )
        item_row = await cursor.fetchone()
        await cursor.execute(
            "SELECT tag_id, weight, confidence, source FROM resource_tag "
            "WHERE resource_id = %s ORDER BY tag_id, source",
            (resource_id,),
        )
        tag_columns = tuple(item[0] for item in cursor.description)
        tags = tuple(_row(tag_columns, row) for row in await cursor.fetchall())
        await cursor.execute(
            "SELECT state_type, state_version, suppress_until FROM user_resource_state "
            "WHERE user_id = %s AND resource_id = %s ORDER BY state_type",
            (user_id, resource_id),
        )
        state_columns = tuple(item[0] for item in cursor.description)
        states = tuple(_row(state_columns, row) for row in await cursor.fetchall())
        await cursor.execute(
            "SELECT user_id, display_name, status, auth_version, role_version "
            "FROM iam_user_account WHERE user_id = %s",
            (user_id,),
        )
        account_row = await cursor.fetchone()
        await cursor.execute(
            "SELECT scope, action FROM user_effective_personalization_consent_v "
            "WHERE user_id = %s ORDER BY scope",
            (user_id,),
        )
        consents = {str(scope): str(action) == "GRANT" for scope, action in await cursor.fetchall()}
        await cursor.execute("SELECT COUNT(*) FROM user_profile WHERE user_id = %s", (user_id,))
        profile_count = int((await cursor.fetchone())[0])
        await cursor.execute("SELECT tag_id FROM user_interest_tag WHERE user_id = %s ORDER BY tag_id", (user_id,))
        interests = {int(row[0]) for row in await cursor.fetchall()}
        await cursor.execute(
            "SELECT tag_id, reason_code FROM user_negative_preference WHERE user_id = %s "
            "ORDER BY tag_id, reason_code",
            (user_id,),
        )
        negatives = {(int(row[0]), str(row[1])) for row in await cursor.fetchall()}
        await cursor.execute(
            "SELECT status, COUNT(*) FROM profile_update_outbox GROUP BY status ORDER BY status"
        )
        outbox_statuses = {str(row[0]): int(row[1]) for row in await cursor.fetchall()}

    if task_row is None or record_row is None or item_row is None:
        raise ValueError("the selected task, record or recommendation item does not exist")
    task = {
        "id": str(task_row[0]), "user_id": int(task_row[1]), "trigger_scene": str(task_row[2]),
        "status": str(task_row[3]), "context_version": int(task_row[4]),
    }
    record = {
        "id": int(record_row[0]), "task_id": str(record_row[1]), "user_id": int(record_row[2]),
        "context_version": int(record_row[3]), "output_type": str(record_row[4]),
    }
    item = {
        "id": int(item_row[0]), "record_id": int(item_row[1]), "resource_id": int(item_row[2]),
        "rank_no": int(item_row[3]), "resource_type": str(item_row[4]), "title": str(item_row[5]),
        "task_id": str(item_row[6]), "user_id": int(item_row[7]),
    }
    account = None if account_row is None else {
        "user_id": int(account_row[0]), "display_name": str(account_row[1]),
        "status": str(account_row[2]), "auth_version": int(account_row[3]),
        "role_version": int(account_row[4]),
    }
    if task["id"] != task_id or task["user_id"] != user_id or task["status"] != "COMPLETED":
        raise ValueError("target task is not a completed task owned by the selected user")
    if record["task_id"] != task_id or record["user_id"] != user_id:
        raise ValueError("target record is not owned by the selected task/user")
    if item["record_id"] != record_id or item["resource_id"] != resource_id or item["user_id"] != user_id:
        raise ValueError("target recommendation item does not match the selected task/user/resource")
    if item["resource_type"] != "BOOK":
        raise ValueError("formal reader feedback preflight only accepts BOOK resources")
    tag_ids = {int(tag["tag_id"]) for tag in tags}
    return {
        "account": account,
        "consents": consents,
        "task": task,
        "record": record,
        "item": item,
        "resource_tags": tags,
        "resource_states": states,
        "profile_count": profile_count,
        "outbox_statuses": outbox_statuses,
        "expected_future_projection_delta": {
            "user_profile": 1 if profile_count == 0 else 0,
            "user_interest_tag": len(tag_ids - interests),
            "user_negative_preference": len(
                {(tag_id, "TOPIC_NOT_INTERESTED") for tag_id in tag_ids} - negatives
            ),
        },
    }


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run_id must use safe characters")
    output_dir = _resolve_inside_root(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing preflight directory: {output_dir}")
    values = read_env(_resolve_inside_root(args.env_file))
    required = ("RECPRO_MYSQL_USER", "RECPRO_MYSQL_PASSWORD", "RECPRO_MYSQL_DATABASE")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing runtime MySQL keys: {missing}")
    connection = await _connect(values)
    try:
        names_before, counts_before = await _snapshot(connection)
        target = await _read_target(
            connection,
            user_id=args.user_id,
            task_id=args.task_id,
            record_id=args.record_id,
            item_id=args.item_id,
            resource_id=args.resource_id,
        )
        names_after, counts_after = await _snapshot(connection)
    finally:
        connection.close()
    if names_before != names_after or counts_before != counts_after:
        raise RuntimeError("read-only preflight changed database table names or counts")
    account = target["account"]
    if account is None:
        raise ValueError("selected formal reader account does not exist")
    if account["status"] != "ACTIVE":
        raise ValueError("selected formal reader account is not ACTIVE")
    behavior_consent = bool(target["consents"].get("BEHAVIOR_LEARNING", False))
    status = "READY_FOR_SUCCESSOR_CHANGEPLAN" if behavior_consent else "BLOCKED_CONSENT_REQUIRED"
    evidence = {
        "schema_version": "formal-reader-feedback-preflight-v1",
        "status": status,
        "run_id": args.run_id,
        "target": {
            "user_id": args.user_id,
            "task_id": args.task_id,
            "record_id": args.record_id,
            "recommendation_item_id": args.item_id,
            "resource_id": args.resource_id,
            "resource_type": target["item"]["resource_type"],
            "resource_title": target["item"]["title"],
        },
        "account": account,
        "effective_consents": target["consents"],
        "profile_projection": {
            "current_row_count": target["profile_count"],
            "first_worker_replay_would_create_row": target["profile_count"] == 0,
        },
        "expected_future_projection_delta": target["expected_future_projection_delta"],
        "outbox_statuses": target["outbox_statuses"],
        "database_counts_before": counts_before,
        "database_counts_after": counts_after,
        "database_writes": 0,
        "business_posts": 0,
        "outbox_claims": 0,
        "external_llm_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "notes": [
            "Formal feedback routes require explicit BEHAVIOR_LEARNING consent; no consent was granted by this command.",
            "The target reader has no current user_profile row; a future approved Worker replay must create it through the existing upsert boundary.",
            "No password, token, prompt, model output, full identifier or database credential is stored in this artifact.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "preflight.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"status": status, "run_id": args.run_id, "path": str((output_dir / "preflight.json").relative_to(PROJECT_ROOT)), "database_writes": 0, "business_posts": 0, "external_llm_requests": 0, "files_deleted": 0, "actual_delete_count": 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, default=10001)
    parser.add_argument("--task-id", default="fd7f985b-4470-56ee-9f6f-3091e5e92054")
    parser.add_argument("--record-id", type=int, default=62)
    parser.add_argument("--item-id", type=int, default=403)
    parser.add_argument("--resource-id", type=int, default=2)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] formal reader feedback preflight did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
