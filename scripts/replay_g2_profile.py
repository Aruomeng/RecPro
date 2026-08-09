"""Replay one user's MySQL behavior facts into a versioned profile projection."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import asyncmy

from backend.app.profile.replay import (
    BehaviorForReplay,
    ResourceTagEvidence,
    compute_profile_snapshot,
)
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


async def read_events(connection: Any, *, user_id: int, as_of: datetime) -> tuple[BehaviorForReplay, ...]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT id, event_uuid, event_type, resource_id, occurred_at, reason_code "
            "FROM user_behavior_event WHERE user_id = %s AND occurred_at <= %s "
            "ORDER BY occurred_at, id, event_uuid",
            (user_id, as_of),
        )
        rows = await cursor.fetchall()
        resource_ids = tuple(sorted({int(row[3]) for row in rows if row[3] is not None}))
        tag_map: dict[int, list[ResourceTagEvidence]] = {resource_id: [] for resource_id in resource_ids}
        if resource_ids:
            placeholders = ",".join("%s" for _ in resource_ids)
            await cursor.execute(
                "SELECT resource_id, tag_id, weight, confidence FROM resource_tag "
                f"WHERE resource_id IN ({placeholders}) ORDER BY resource_id, tag_id, source",
                resource_ids,
            )
            for resource_id, tag_id, weight, confidence in await cursor.fetchall():
                tag_map[int(resource_id)].append(
                    ResourceTagEvidence(int(tag_id), float(weight), float(confidence))
                )
    return tuple(
        BehaviorForReplay(
            event_id=int(row[0]),
            event_uuid=str(row[1]),
            event_type=str(row[2]),
            resource_id=int(row[3]) if row[3] is not None else None,
            occurred_at=row[4],
            reason_code=str(row[5]) if row[5] is not None else None,
            tags=tuple(tag_map.get(int(row[3]), ())) if row[3] is not None else (),
        )
        for row in rows
    )


async def apply_replay(
    *,
    host_port: int,
    database: str,
    root_password: str,
    user_id: int,
    as_of: datetime,
    formula_version: str,
) -> dict[str, object]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=host_port,
        user="root",
        password=root_password,
        db=database,
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        events = await read_events(connection, user_id=user_id, as_of=as_of)
        snapshot = compute_profile_snapshot(
            user_id=user_id,
            as_of=as_of,
            events=events,
            formula_version=formula_version,
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT profile_version FROM profile_replay_run "
                "WHERE user_id = %s AND as_of = %s AND formula_version = %s AND input_hash = %s",
                (user_id, as_of, formula_version, snapshot.input_hash),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                await connection.rollback()
                return {
                    "applied": False,
                    "profile_version": int(existing[0]),
                    "event_count": snapshot.event_count,
                    "input_hash": snapshot.input_hash,
                    "interest_count": len(snapshot.interests),
                    "negative_count": len(snapshot.negatives),
                }
            await cursor.execute(
                "SELECT COALESCE(MAX(profile_version), 0) FROM profile_replay_run WHERE user_id = %s",
                (user_id,),
            )
            row = await cursor.fetchone()
            profile_version = int(row[0]) + 1
            await cursor.execute(
                "INSERT INTO profile_replay_run "
                "(user_id, as_of, formula_version, input_hash, profile_version, event_count, applied_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, as_of, formula_version, snapshot.input_hash, profile_version, snapshot.event_count, now),
            )
            await cursor.execute(
                "INSERT INTO user_profile "
                "(user_id, profile_version, profile_confidence, recent_focus_tag_id, topic_focus_strength, "
                "reading_stage, reading_stage_confidence, updated_at) VALUES (%s, %s, %s, %s, %s, NULL, 0, %s) "
                "ON DUPLICATE KEY UPDATE profile_version = VALUES(profile_version), profile_confidence = VALUES(profile_confidence), "
                "recent_focus_tag_id = VALUES(recent_focus_tag_id), topic_focus_strength = VALUES(topic_focus_strength), "
                "reading_stage = VALUES(reading_stage), reading_stage_confidence = VALUES(reading_stage_confidence), updated_at = VALUES(updated_at)",
                (user_id, profile_version, snapshot.profile_confidence, snapshot.recent_focus_tag_id, snapshot.topic_focus_strength, now),
            )
            for signal in snapshot.interests:
                await cursor.execute(
                    "INSERT INTO user_interest_tag "
                    "(user_id, tag_id, positive_weight, raw_positive_signal, source_count, last_event_at, profile_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE "
                    "positive_weight = VALUES(positive_weight), raw_positive_signal = VALUES(raw_positive_signal), "
                    "source_count = VALUES(source_count), last_event_at = VALUES(last_event_at), profile_version = VALUES(profile_version)",
                    (user_id, signal.tag_id, signal.weight, signal.raw_signal, signal.source_count, signal.last_event_at, profile_version),
                )
            for signal in snapshot.negatives:
                await cursor.execute(
                    "INSERT INTO user_negative_preference "
                    "(user_id, tag_id, reason_code, negative_weight, raw_negative_signal, source_count, expires_at, last_event_at, profile_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s) ON DUPLICATE KEY UPDATE "
                    "negative_weight = VALUES(negative_weight), raw_negative_signal = VALUES(raw_negative_signal), "
                    "source_count = VALUES(source_count), last_event_at = VALUES(last_event_at), profile_version = VALUES(profile_version)",
                    (user_id, signal.tag_id, signal.reason_code, signal.weight, signal.raw_signal, signal.source_count, signal.last_event_at, profile_version),
                )
            for event in events:
                delta = {
                    "event_type": event.event_type,
                    "resource_id": event.resource_id,
                    "tag_ids": [tag.tag_id for tag in event.tags],
                    "as_of": as_of.isoformat(),
                }
                await cursor.execute(
                    "INSERT IGNORE INTO profile_change_log "
                    "(user_id, source_event_id, source_type, profile_version_before, profile_version_after, delta_json, formula_version, created_at) "
                    "VALUES (%s, %s, 'REPLAY', %s, %s, %s, %s, %s)",
                    (user_id, event.event_id, max(0, profile_version - 1), profile_version, json.dumps(delta, ensure_ascii=False, separators=(",", ":")), formula_version, now),
                )
        await connection.commit()
        return {
            "applied": True,
            "profile_version": profile_version,
            "event_count": snapshot.event_count,
            "input_hash": snapshot.input_hash,
            "interest_count": len(snapshot.interests),
            "negative_count": len(snapshot.negatives),
        }
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--formula-version", default="profile-g2-v1")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    return parser


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    if args.user_id <= 0:
        raise ValueError("user id must be positive")
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    root_password = values.get("RECPRO_MYSQL_ROOT_PASSWORD", "")
    if not root_password:
        raise ValueError("RECPRO_MYSQL_ROOT_PASSWORD is required for profile replay")
    as_of = parse_utc(args.as_of)
    result = await apply_replay(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        root_password=root_password,
        user_id=args.user_id,
        as_of=as_of,
        formula_version=args.formula_version,
    )
    evidence_path = PROJECT_ROOT / "artifacts" / "verification" / "g2" / run_id / f"profile-{args.user_id}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=False)
    evidence_path.write_text(json.dumps({"schema_version": "g2-profile-replay-evidence-v1", "run_id": run_id, "user_id": args.user_id, "as_of": as_of.isoformat(), "formula_version": args.formula_version, **result, "destructive_actions": 0}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] G2 profile replay: {evidence_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.Error) as exc:
        print(f"[FAIL] G2 profile replay did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
