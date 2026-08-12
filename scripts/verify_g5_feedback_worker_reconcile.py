#!/usr/bin/env python3
"""Reconcile one attempted G5 feedback/behavior/Worker plan with SELECT only.

This verifier is intentionally post-write and read-only.  It records whether
the approved interaction chain is complete even when an executor's final
count assertion rejected a plan after its append-only commits.  It never
updates, deletes, claims Outbox work, calls HTTP business routes, or invokes
Neo4j/Chroma/DeepSeek.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import asyncmy

from scripts.build_g5_feedback_http_plan import (
    connect_runtime,
    load_pass_baseline,
    read_identity_and_grants,
    read_snapshot,
)
from scripts.execute_g5_feedback_worker_plan import validate_plan
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_inside_root(value: Path, *, label: str, strict: bool = True) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=strict)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def validate_run_id(value: str) -> str:
    if not value or len(value) > 64 or not value[0].isalnum():
        raise ValueError("run id must start with an alphanumeric character and be at most 64 characters")
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for char in value):
        raise ValueError("run id contains unsafe characters")
    return value


def parse_db_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("interaction timestamp must include a timezone")
    return parsed.astimezone(UTC).replace(tzinfo=None, microsecond=(parsed.microsecond // 1000) * 1000)


def table_deltas(
    before: Mapping[str, int], after: Mapping[str, int]
) -> dict[str, int]:
    return {table: int(after[table]) - int(before[table]) for table in before}


async def read_post_apply_facts(
    values: Mapping[str, str], *, payload: Mapping[str, Any]
) -> dict[str, Any]:
    connection = await connect_runtime(values)
    try:
        async with connection.cursor() as cursor:
            impression_uuid = str(payload["impression_uuid"])
            feedback_uuid = str(payload["feedback_uuid"])
            behavior_uuid = str(payload["behavior_uuid"])
            await cursor.execute(
                "SELECT id, recommendation_item_id, user_id, impression_uuid "
                "FROM recommendation_impression WHERE impression_uuid = %s",
                (impression_uuid,),
            )
            impressions = tuple(await cursor.fetchall())
            await cursor.execute(
                "SELECT id, feedback_uuid, recommendation_item_id, user_id, impression_uuid, "
                "feedback_type, reason_code FROM recommendation_feedback WHERE feedback_uuid = %s",
                (feedback_uuid,),
            )
            feedback = tuple(await cursor.fetchall())
            await cursor.execute(
                "SELECT id, event_uuid, user_id, event_type, resource_id, recommendation_item_id, "
                "task_id, impression_uuid FROM user_behavior_event "
                "WHERE event_uuid IN (%s, %s, %s) ORDER BY id",
                (impression_uuid, feedback_uuid, behavior_uuid),
            )
            events = tuple(await cursor.fetchall())
            event_ids = {str(row[1]): int(row[0]) for row in events}
            source_ids = tuple(event_ids[name] for name in (feedback_uuid, behavior_uuid) if name in event_ids)
            outbox: tuple[tuple[Any, ...], ...] = ()
            if source_ids:
                placeholders = ",".join("%s" for _ in source_ids)
                await cursor.execute(
                    "SELECT id, source_event_id, status, attempts, locked_by, last_error "
                    f"FROM profile_update_outbox WHERE source_event_id IN ({placeholders}) ORDER BY id",
                    source_ids,
                )
                outbox = tuple(await cursor.fetchall())
            await cursor.execute(
                "SELECT status, COUNT(*) FROM profile_update_outbox GROUP BY status ORDER BY status"
            )
            outbox_statuses = {str(row[0]): int(row[1]) for row in await cursor.fetchall()}
            await cursor.execute(
                "SELECT user_id, resource_id, state_type, state_version, source_event_id, "
                "suppress_until, last_feedback_at FROM user_resource_state "
                "WHERE user_id = %s AND resource_id = %s ORDER BY state_type",
                (int(payload["user_id"]), int(payload["resource_id"])),
            )
            resource_states = tuple(await cursor.fetchall())
            feedback_event_id = event_ids.get(feedback_uuid)
            behavior_event_id = event_ids.get(behavior_uuid)
            if feedback_event_id is None or behavior_event_id is None:
                replay: tuple[tuple[Any, ...], ...] = ()
                change_log: tuple[tuple[Any, ...], ...] = ()
            else:
                await cursor.execute(
                    "SELECT id, as_of, formula_version, profile_version, event_count "
                    "FROM profile_replay_run WHERE user_id = %s AND formula_version = %s "
                    "AND as_of IN (%s, %s) ORDER BY id",
                    (
                        int(payload["user_id"]),
                        str(payload["formula_version"]),
                        parse_db_datetime(str(payload["feedback_occurred_at"])),
                        parse_db_datetime(str(payload["behavior_occurred_at"])),
                    ),
                )
                replay = tuple(await cursor.fetchall())
                await cursor.execute(
                    "SELECT id, source_event_id, source_type, profile_version_before, profile_version_after "
                    "FROM profile_change_log WHERE source_event_id IN (%s, %s, %s) "
                    "AND source_type = 'REPLAY' ORDER BY id",
                    tuple(event_ids.get(name, -1) for name in (impression_uuid, feedback_uuid, behavior_uuid)),
                )
                change_log = tuple(await cursor.fetchall())
            await cursor.execute(
                "SELECT profile_version FROM user_profile WHERE user_id = %s",
                (int(payload["user_id"]),),
            )
            profile = tuple(await cursor.fetchall())
            await cursor.execute(
                "SELECT COUNT(*) FROM domain_state_transition WHERE module_name = 'profile'"
            )
            profile_transition_count = int((await cursor.fetchone())[0])
        return {
            "impressions": impressions,
            "feedback": feedback,
            "events": events,
            "event_ids": event_ids,
            "outbox": outbox,
            "outbox_statuses": outbox_statuses,
            "resource_states": resource_states,
            "replay": replay,
            "change_log": change_log,
            "profile": profile,
            "profile_transition_count": profile_transition_count,
        }
    finally:
        connection.close()


def assess(
    *,
    plan: Mapping[str, Any],
    baseline_counts: Mapping[str, int],
    after_counts: Mapping[str, int],
    facts: Mapping[str, Any],
) -> tuple[str, list[str], dict[str, Any]]:
    payload = plan["interaction_payload"]
    errors: list[str] = []
    observed = table_deltas(baseline_counts, after_counts)
    planned = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: int(target["expected_after_min_count"])
        - int(target["expected_before_count"])
        for target in plan["targets"]
    }
    target_tables = set(planned)
    changed_non_targets = {
        table: delta for table, delta in observed.items() if table not in target_tables and delta != 0
    }
    if changed_non_targets:
        errors.append(f"protected/non-target tables changed: {changed_non_targets}")
    for table, expected in (
        ("recommendation_impression", 1),
        ("recommendation_feedback", 1),
        ("user_behavior_event", 3),
        ("profile_update_outbox", 2),
        ("user_resource_state", 1),
        ("profile_replay_run", 2),
        ("profile_change_log", 3),
        ("domain_state_transition", 9),
        ("user_profile", 0),
    ):
        if observed.get(table) != expected:
            errors.append(f"{table} delta expected {expected}, observed {observed.get(table)}")
    variable_drift = {
        table: {"planned": planned.get(table), "observed": observed.get(table)}
        for table in ("user_interest_tag", "user_negative_preference")
        if planned.get(table) != observed.get(table)
    }
    if len(facts["impressions"]) != 1:
        errors.append("deterministic impression UUID is not unique")
    if len(facts["feedback"]) != 1:
        errors.append("deterministic feedback UUID is not unique")
    if len(facts["events"]) != 3:
        errors.append("the three deterministic behavior event UUIDs are not unique")
    if len(facts["outbox"]) != 2 or any(str(row[2]) != "DONE" for row in facts["outbox"]):
        errors.append("the two Worker outbox rows are not both DONE")
    if facts["outbox_statuses"].get("PENDING", 0) or facts["outbox_statuses"].get("PROCESSING", 0):
        errors.append(f"live Outbox still has work: {facts['outbox_statuses']}")
    if not any(str(row[2]) == "HIDDEN" and int(row[4]) == facts["event_ids"].get(str(payload["feedback_uuid"]), -1) for row in facts["resource_states"]):
        errors.append("feedback did not produce the expected HIDDEN resource state")
    if len(facts["replay"]) != 2:
        errors.append("Worker did not produce exactly two replay rows for feedback/behavior as_of values")
    if len(facts["change_log"]) != 3:
        errors.append("Worker did not produce exactly three replay change-log rows")
    if len(facts["profile"]) != 1:
        errors.append("target user does not have exactly one current profile row")
    status = "RECONCILIATION_FAILED" if errors else (
        "PARTIAL_APPLY_RECONCILED" if variable_drift else "PASS"
    )
    return status, errors, {
        "observed_deltas": observed,
        "planned_deltas": planned,
        "projection_delta_drift": variable_drift,
        "changed_non_targets": changed_non_targets,
    }


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validate_run_id(args.run_id)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"reconciliation evidence directory already exists: {evidence_dir}")
    plan_path = resolve_inside_root(args.plan, label="G5 ChangePlan")
    baseline_path = resolve_inside_root(args.baseline, label="G5 baseline")
    plan, _ = validate_plan(
        plan_path,
        approved_plan_id=args.plan_id,
        approved_plan_hash=args.approved_plan_hash,
    )
    baseline, baseline_raw = load_pass_baseline(baseline_path)
    compose_values = read_env(args.env_file.resolve(strict=True))
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secret_values = read_env(args.secrets_file.resolve(strict=True))
    values = {**compose_values, **secret_values}
    required = (
        "COMPOSE_PROJECT_NAME",
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_PERSISTENCE_PROBE_ID",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")
    if str(baseline.get("compose_project")) != values["COMPOSE_PROJECT_NAME"]:
        raise ValueError("baseline Compose project does not match the current environment")
    before_names = tuple(sorted(str(key) for key in baseline["after_counts"]))
    connection = await connect_runtime(values)
    try:
        after_names, after_counts = await read_snapshot(connection)
    finally:
        connection.close()
    if after_names != before_names:
        raise ValueError("live table set differs from the supplied baseline")
    identity = await read_identity_and_grants(values)
    facts = await read_post_apply_facts(values, payload=plan["interaction_payload"])
    status, errors, count_summary = assess(
        plan=plan,
        baseline_counts={str(key): int(value) for key, value in baseline["after_counts"].items()},
        after_counts=after_counts,
        facts=facts,
    )
    evidence = {
        "schema_version": "g5-feedback-worker-reconciliation-v1",
        "status": status,
        "run_id": run_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "plan_git_commit": plan["git_commit"],
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_database": values["RECPRO_MYSQL_DATABASE"],
        "target": {
            "task_id": plan["interaction_payload"]["recommendation_task_id"],
            "record_id": int(plan["interaction_payload"]["recommendation_record_id"]),
            "recommendation_item_id": int(plan["interaction_payload"]["recommendation_item_id"]),
            "resource_id": int(plan["interaction_payload"]["resource_id"]),
            "user_id": int(plan["interaction_payload"]["user_id"]),
        },
        "count_summary": count_summary,
        "interaction": {
            "impression_uuid": plan["interaction_payload"]["impression_uuid"],
            "feedback_uuid": plan["interaction_payload"]["feedback_uuid"],
            "behavior_uuid": plan["interaction_payload"]["behavior_uuid"],
            "event_ids": facts["event_ids"],
            "outbox": [
                {"id": int(row[0]), "source_event_id": int(row[1]), "status": str(row[2]), "attempts": int(row[3])}
                for row in facts["outbox"]
            ],
            "replay_rows": [
                {"id": int(row[0]), "as_of": row[1].isoformat(), "profile_version": int(row[3]), "event_count": int(row[4])}
                for row in facts["replay"]
            ],
            "change_log_count": len(facts["change_log"]),
            "resource_states": [
                {"state_type": str(row[2]), "state_version": int(row[3]), "source_event_id": int(row[4])}
                for row in facts["resource_states"]
            ],
            "outbox_statuses": facts["outbox_statuses"],
        },
        "errors": errors,
        "identity": identity,
        "baseline_sha256": __import__("hashlib").sha256(baseline_raw).hexdigest(),
        "database_writes": 0,
        "outbox_claims": 0,
        "external_requests": 0,
        "external_llm_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "reconciliation.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G5 Worker reconciliation did not complete: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
