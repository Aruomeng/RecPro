#!/usr/bin/env python3
"""Apply one explicitly approved G5 feedback/behavior/Outbox ChangePlan.

The executor is deliberately fail-closed.  It accepts only the exact approved
``S2_CONTROLLED_UPDATE``/``DRY_RUN`` plan identity, rechecks the isolated
MySQL baseline and target ownership, appends one bounded interaction chain, and
consumes exactly the two Outbox rows produced by that chain.  It has no
migration, seed, delete, graph/vector write, or external-LLM capability.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import UUID

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.composition import (
    build_profile_outbox_worker,
    build_research_behavior_service,
    build_research_feedback_service,
)
from backend.app.feedback.domain.public import (
    BehaviorAppendCommand,
    FeedbackCommand,
    ImpressionCommand,
)
from backend.app.shared_kernel.contracts.enums import (
    BehaviorEventType,
    FeedbackType,
    NegativeReasonCode,
)
from scripts.build_g5_feedback_http_plan import (
    G5_FIXED_FINAL_DELTAS,
    G5_TABLES,
    MAX_G5_CHANGES,
    SCHEMA_PATH,
    canonical,
    connect_runtime,
    expected_final_deltas,
    load_pass_baseline,
    read_identity_and_grants,
    read_snapshot,
    read_target_facts,
    sha256_bytes,
    target_snapshot_from_facts,
)
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g7_mysql_http_readonly import build_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

INTERACTION_DELTAS = {
    "recommendation_impression": 1,
    "recommendation_feedback": 1,
    "user_behavior_event": 3,
    "profile_update_outbox": 2,
    "user_resource_state": 1,
    "domain_state_transition": 3,
}
FINAL_DELTAS = {
    **INTERACTION_DELTAS,
    "domain_state_transition": 9,
    "profile_replay_run": 2,
    "profile_change_log": 3,
    "user_interest_tag": 2,
    "user_negative_preference": 2,
    "user_profile": 0,
}


def resolve_inside_root(value: Path, *, label: str, strict: bool = True) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=strict)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("current Git HEAD is not a full commit hash")
    return commit


def parse_utc(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label=label)
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, raw


def validate_plan(
    path: Path, *, approved_plan_id: str, approved_plan_hash: str
) -> tuple[dict[str, Any], bytes]:
    plan, raw = load_json(path, label="G5 ChangePlan")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan)
    )
    if errors:
        locations = ", ".join(
            ".".join(str(item) for item in error.absolute_path) for error in errors
        )
        raise ValueError(f"ChangePlan violates schema: {locations}")
    if plan.get("classification") != "S2_CONTROLLED_UPDATE" or plan.get("mode") != "DRY_RUN":
        raise ValueError("only an S2_CONTROLLED_UPDATE DRY_RUN plan may be applied")
    if str(plan.get("plan_id")) != approved_plan_id:
        raise ValueError("approved plan id does not match the ChangePlan")
    if not HASH_PATTERN.fullmatch(approved_plan_hash) or str(plan.get("plan_hash")) != approved_plan_hash:
        raise ValueError("approved plan hash does not match the ChangePlan")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if hashlib.sha256(canonical(unsigned)).hexdigest() != approved_plan_hash:
        raise ValueError("ChangePlan canonical hash does not match plan_hash")
    expected_safety = {
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "overwrite_existing": False,
        "destructive_capabilities_required": False,
        "counts_must_not_decrease": True,
    }
    if plan.get("safety_assertions") != expected_safety:
        raise ValueError("ChangePlan safety assertions are not zero-destructive")
    targets = plan.get("targets")
    if not isinstance(targets, list):
        raise ValueError("ChangePlan targets are not an array")
    target_tables: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict) or target.get("kind") != "MYSQL":
            raise ValueError("ChangePlan contains a non-MySQL target")
        identifier = str(target.get("identifier", ""))
        table = identifier.rsplit(".", maxsplit=1)[-1]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", table):
            raise ValueError("ChangePlan contains an unsafe table identifier")
        if table in target_tables:
            raise ValueError(f"duplicate target table: {table}")
        target_tables[table] = target
    if set(target_tables) != set(FINAL_DELTAS):
        raise ValueError("ChangePlan target set does not match the bounded G5 write set")
    observed_deltas = {
        table: int(target["expected_after_min_count"])
        - int(target["expected_before_count"])
        for table, target in target_tables.items()
    }
    for table, expected in G5_FIXED_FINAL_DELTAS.items():
        if table in {"user_interest_tag", "user_negative_preference"}:
            if observed_deltas[table] < 0:
                raise ValueError(f"ChangePlan contains a negative projection delta for {table}")
        elif observed_deltas[table] != expected:
            raise ValueError(
                f"ChangePlan delta for {table} does not match the bounded G5 contract: "
                f"expected {expected}, observed {observed_deltas[table]}"
            )
    if int(plan.get("max_changes", -1)) != sum(observed_deltas.values()):
        raise ValueError("G5 ChangePlan max_changes must equal the sum of its bounded table deltas")
    if int(plan.get("max_changes", -1)) > MAX_G5_CHANGES:
        raise ValueError("G5 ChangePlan max_changes exceeds the bounded safety cap")
    payload = plan.get("interaction_payload")
    if not isinstance(payload, Mapping):
        raise ValueError("ChangePlan interaction_payload is missing")
    for name in ("impression_uuid", "feedback_uuid", "behavior_uuid", "behavior_session_id", "recommendation_task_id"):
        try:
            UUID(str(payload[name]))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"interaction_payload.{name} is not a UUID") from exc
    return plan, raw


async def read_outbox_statuses(values: Mapping[str, str]) -> dict[str, int]:
    connection = await connect_runtime(values)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT status, COUNT(*) FROM profile_update_outbox GROUP BY status ORDER BY status"
            )
            return {str(row[0]): int(row[1]) for row in await cursor.fetchall()}
    finally:
        connection.close()


async def read_interaction_state(
    values: Mapping[str, str], *, payload: Mapping[str, Any]
) -> dict[str, Any]:
    interaction_uuids = (
        str(payload["impression_uuid"]),
        str(payload["feedback_uuid"]),
        str(payload["behavior_uuid"]),
    )
    connection = await connect_runtime(values)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, event_uuid, event_type, resource_id, recommendation_item_id "
                "FROM user_behavior_event WHERE event_uuid IN (%s, %s, %s) ORDER BY id",
                interaction_uuids,
            )
            events = tuple(
                {
                    "id": int(row[0]),
                    "event_uuid": str(row[1]),
                    "event_type": str(row[2]),
                    "resource_id": int(row[3]) if row[3] is not None else None,
                    "recommendation_item_id": int(row[4]) if row[4] is not None else None,
                }
                for row in await cursor.fetchall()
            )
            source_ids = tuple(
                row["id"] for row in events if row["event_type"] in {"NOT_INTERESTED", "CLICK_RECOMMENDATION"}
            )
            if len(source_ids) != 2:
                raise ValueError("interaction must produce exactly two profile source events")
            placeholders = ",".join("%s" for _ in source_ids)
            await cursor.execute(
                "SELECT id, source_event_id, status, attempts, locked_by, last_error "
                f"FROM profile_update_outbox WHERE source_event_id IN ({placeholders}) "
                "AND source_type = 'BEHAVIOR' ORDER BY id",
                source_ids,
            )
            outbox = tuple(
                {
                    "id": int(row[0]),
                    "source_event_id": int(row[1]),
                    "status": str(row[2]),
                    "attempts": int(row[3]),
                    "locked_by": str(row[4]) if row[4] is not None else None,
                    "last_error": str(row[5]) if row[5] is not None else None,
                }
                for row in await cursor.fetchall()
            )
            await cursor.execute(
                "SELECT state_type, source_event_id, state_version FROM user_resource_state "
                "WHERE user_id = %s AND resource_id = %s ORDER BY state_type",
                (int(payload["user_id"]), int(payload["resource_id"])),
            )
            states = tuple(
                {
                    "state_type": str(row[0]),
                    "source_event_id": int(row[1]),
                    "state_version": int(row[2]),
                }
                for row in await cursor.fetchall()
            )
        return {"events": events, "outbox": outbox, "states": states}
    finally:
        connection.close()


def build_commands(payload: Mapping[str, Any]) -> tuple[ImpressionCommand, FeedbackCommand, BehaviorAppendCommand]:
    impression_uuid = UUID(str(payload["impression_uuid"]))
    feedback_uuid = UUID(str(payload["feedback_uuid"]))
    behavior_uuid = UUID(str(payload["behavior_uuid"]))
    task_uuid = UUID(str(payload["recommendation_task_id"]))
    return (
        ImpressionCommand(
            impression_uuid=impression_uuid,
            recommendation_item_id=int(payload["recommendation_item_id"]),
            user_id=int(payload["user_id"]),
            position=int(payload["position"]),
            rendered_at=parse_utc(str(payload["impression_rendered_at"]), label="impression_rendered_at"),
            visible_started_at=parse_utc(str(payload["impression_visible_started_at"]), label="impression_visible_started_at"),
            visible_ms=int(payload["impression_visible_ms"]),
            max_visible_ratio=float(payload["impression_max_visible_ratio"]),
        ),
        FeedbackCommand(
            feedback_uuid=feedback_uuid,
            recommendation_item_id=int(payload["recommendation_item_id"]),
            user_id=int(payload["user_id"]),
            feedback_type=FeedbackType.NOT_INTERESTED,
            occurred_at=parse_utc(str(payload["feedback_occurred_at"]), label="feedback_occurred_at"),
            impression_uuid=impression_uuid,
            reason_code=NegativeReasonCode.TOPIC_NOT_INTERESTED,
        ),
        BehaviorAppendCommand(
            event_uuid=behavior_uuid,
            user_id=int(payload["user_id"]),
            session_id=UUID(str(payload["behavior_session_id"])),
            event_type=BehaviorEventType.CLICK_RECOMMENDATION,
            occurred_at=parse_utc(str(payload["behavior_occurred_at"]), label="behavior_occurred_at"),
            resource_id=int(payload["resource_id"]),
            recommendation_item_id=int(payload["recommendation_item_id"]),
            task_id=task_uuid,
            impression_uuid=impression_uuid,
            query_text=str(payload["query_text"]),
            dwell_ms=int(payload["direct_behavior_dwell_ms"]),
            visible_ratio=float(payload["direct_behavior_visible_ratio"]),
            position=int(payload["position"]),
            enqueue_profile_update=True,
        ),
    )


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validate_run_id(args.run_id)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    plan_path = resolve_inside_root(args.plan, label="G5 ChangePlan")
    baseline_path = resolve_inside_root(args.baseline, label="G5 baseline")
    plan, _plan_raw = validate_plan(
        plan_path,
        approved_plan_id=args.plan_id,
        approved_plan_hash=args.approved_plan_hash,
    )
    reviewed_git = str(plan["git_commit"])
    if current_git_commit() != reviewed_git:
        raise ValueError("runtime code changed after the reviewed plan; regenerate the plan")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise ValueError("working tree must be clean when applying an approved plan")
    compose_values = read_env(args.env_file.resolve(strict=True))
    secret_values = read_env(args.secrets_file.resolve(strict=True))
    values = {**compose_values, **secret_values}
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    required = (
        "COMPOSE_PROJECT_NAME",
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_MYSQL_MIGRATION_USER",
        "RECPRO_MYSQL_MIGRATION_PASSWORD",
        "RECPRO_PERSISTENCE_PROBE_ID",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")
    baseline, baseline_raw = load_pass_baseline(baseline_path)
    if hashlib.sha256(baseline_raw).hexdigest() != plan["input_hashes"]["g5_feedback_http_readonly_baseline"]:
        raise ValueError("approved read-only baseline hash changed")
    if baseline.get("compose_project") != values["COMPOSE_PROJECT_NAME"]:
        raise ValueError("baseline Compose project does not match runtime")
    payload = plan["interaction_payload"]
    before_names, before_counts = await _snapshot(values)
    baseline_counts = {str(key): int(value) for key, value in baseline["after_counts"].items()}
    if before_names != tuple(sorted(baseline_counts)) or before_counts != baseline_counts:
        raise ValueError("live full counts differ from the approved baseline")
    for target in plan["targets"]:
        table = str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        if int(target["expected_before_count"]) != baseline_counts[table]:
            raise ValueError(f"plan expected_before_count does not match baseline for {table}")
    target_facts_connection = await connect_runtime(values)
    try:
        target_facts = await read_target_facts(
            target_facts_connection,
            task_id=str(payload["recommendation_task_id"]),
            record_id=int(payload["recommendation_record_id"]),
            item_id=int(payload["recommendation_item_id"]),
            user_id=int(payload["user_id"]),
            resource_id=int(payload["resource_id"]),
            uuids={
                "impression_uuid": UUID(str(payload["impression_uuid"])),
                "feedback_uuid": UUID(str(payload["feedback_uuid"])),
                "behavior_uuid": UUID(str(payload["behavior_uuid"])),
            },
        )
    finally:
        target_facts_connection.close()
    target_snapshot_hash = sha256_bytes(canonical(target_snapshot_from_facts(target_facts)))
    if target_snapshot_hash != str(plan["input_hashes"].get("target_snapshot", "")):
        raise ValueError("live recommendation ownership/tag/state snapshot differs from the approved plan")
    planned_deltas = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: int(target["expected_after_min_count"])
        - int(target["expected_before_count"])
        for target in plan["targets"]
    }
    expected_deltas = expected_final_deltas(target_facts)
    if planned_deltas != expected_deltas:
        raise ValueError(
            "approved ChangePlan projection deltas do not match the live target key sets: "
            f"planned={planned_deltas}, expected={expected_deltas}"
        )
    identity = await read_identity_and_grants(values)
    if not identity.get("grants_safe"):
        raise ValueError("runtime grants failed the least-privilege guard")
    statuses_before = await read_outbox_statuses(values)
    if statuses_before.get("PENDING", 0) or statuses_before.get("PROCESSING", 0):
        raise ValueError(f"pre-existing live Outbox work is not allowed: {statuses_before}")

    settings = build_settings(dict(values))
    feedback_service = build_research_feedback_service(settings)
    behavior_service = build_research_behavior_service(settings)
    impression_command, feedback_command, behavior_command = build_commands(payload)
    impression_receipt = await feedback_service.record_impression(impression_command)
    feedback_receipt = await feedback_service.record_feedback(feedback_command)
    behavior_receipt = await behavior_service.append(behavior_command)
    after_interaction_names, after_interaction_counts = await _snapshot(values)
    _assert_delta(before_counts, after_interaction_counts, INTERACTION_DELTAS)
    if after_interaction_names != before_names:
        raise ValueError("interaction changed the database table set")
    for table in before_counts:
        if table not in INTERACTION_DELTAS and after_interaction_counts[table] != before_counts[table]:
            raise ValueError(f"interaction changed a non-target table: {table}")
    if feedback_receipt.outbox_id is None or behavior_receipt.outbox_id is None:
        raise ValueError("feedback and direct behavior must each create one Outbox row")
    replay_impression = await feedback_service.record_impression(impression_command)
    replay_feedback = await feedback_service.record_feedback(feedback_command)
    replay_behavior = await behavior_service.append(behavior_command)
    replay_names, replay_counts = await _snapshot(values)
    if replay_names != after_interaction_names or replay_counts != after_interaction_counts:
        raise ValueError("same-UUID interaction replay changed database counts")
    if not (replay_impression.replayed and replay_feedback.replayed and replay_behavior.replayed):
        raise ValueError("same-UUID interaction replay was not reported as replayed")

    async def worker_connection_factory() -> Any:
        return await asyncmy.connect(
            host="127.0.0.1",
            port=int(values["RECPRO_MYSQL_HOST_PORT"]),
            user=values["RECPRO_MYSQL_MIGRATION_USER"],
            password=values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
            db=values["RECPRO_MYSQL_DATABASE"],
            connect_timeout=10,
            read_timeout=60,
            charset="utf8mb4",
            autocommit=False,
        )

    worker = build_profile_outbox_worker(
        settings,
        connection_factory=worker_connection_factory,
        worker_id=str(payload["worker_id"]),
        formula_version=str(payload["formula_version"]),
    )
    receipts = await worker.run_once(limit=int(payload["worker_limit"]))
    replay_receipts = await worker.run_once(limit=int(payload["worker_limit"]))
    if len(receipts) != 2 or replay_receipts:
        raise ValueError("Worker must return two first-pass receipts and zero on the second pass")
    expected_source_ids = {int(feedback_receipt.behavior_event_id), int(behavior_receipt.event_id)}
    if {int(receipt.source_event_id) for receipt in receipts} != expected_source_ids:
        raise ValueError("Worker consumed an unexpected source-event set")
    after_names, after_counts = await _snapshot(values)
    _assert_delta(baseline_counts, after_counts, planned_deltas)
    if after_names != before_names:
        raise ValueError("approved interaction changed the database table set")
    for table in baseline_counts:
        if table not in planned_deltas and after_counts[table] != baseline_counts[table]:
            raise ValueError(f"approved interaction changed a protected/non-target table: {table}")
    statuses_after = await read_outbox_statuses(values)
    if statuses_after.get("PENDING", 0) or statuses_after.get("PROCESSING", 0):
        raise ValueError(f"Worker left live Outbox work: {statuses_after}")
    evidence = {
        "schema_version": "g5-feedback-worker-apply-evidence-v2",
        "status": "PASS",
        "run_id": run_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "git_commit": reviewed_git,
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_database": values["RECPRO_MYSQL_DATABASE"],
        "target": {
            "task_id": payload["recommendation_task_id"],
            "record_id": int(payload["recommendation_record_id"]),
            "recommendation_item_id": int(payload["recommendation_item_id"]),
            "resource_id": int(payload["resource_id"]),
            "user_id": int(payload["user_id"]),
            "resource_type": payload["resource_type"],
        },
        "interaction": {
            "impression_uuid": payload["impression_uuid"],
            "feedback_uuid": payload["feedback_uuid"],
            "behavior_uuid": payload["behavior_uuid"],
            "impression_id": int(impression_receipt.impression_id),
            "feedback_id": int(feedback_receipt.feedback_id),
            "impression_behavior_event_id": int(impression_receipt.behavior_event_id),
            "feedback_behavior_event_id": int(feedback_receipt.behavior_event_id),
            "direct_behavior_event_id": int(behavior_receipt.event_id),
            "outbox_ids": [int(feedback_receipt.outbox_id), int(behavior_receipt.outbox_id)],
            "replay_receipts_replayed": {
                "impression": bool(replay_impression.replayed),
                "feedback": bool(replay_feedback.replayed),
                "behavior": bool(replay_behavior.replayed),
            },
        },
        "worker": {
            "worker_id": payload["worker_id"],
            "formula_version": payload["formula_version"],
            "limit": int(payload["worker_limit"]),
            "first_receipt_count": len(receipts),
            "second_receipt_count": len(replay_receipts),
            "outbox_statuses_after": statuses_after,
        },
        "before_counts": baseline_counts,
        "after_interaction_counts": after_interaction_counts,
        "after_worker_counts": after_counts,
        "expected_total_delta": planned_deltas,
        "observed_total_delta": {
            table: after_counts[table] - baseline_counts[table] for table in planned_deltas
        },
        "database_writes": sum(planned_deltas.values()),
        "business_posts": 0,
        "outbox_claims": 2,
        "external_requests": 0,
        "external_llm_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
        "identity": identity,
        "target_snapshot": target_facts,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence_path = evidence_dir / "g5-feedback-worker-apply.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


async def _snapshot(values: Mapping[str, str]) -> tuple[tuple[str, ...], dict[str, int]]:
    connection = await connect_runtime(values)
    try:
        return await read_snapshot(connection)
    finally:
        connection.close()


def _assert_delta(
    before: Mapping[str, int], after: Mapping[str, int], expected: Mapping[str, int]
) -> None:
    for table, delta in expected.items():
        observed = int(after[table]) - int(before[table])
        if observed != delta:
            raise ValueError(f"count delta mismatch for {table}: expected {delta}, observed {observed}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G5 feedback/behavior/Worker apply was not completed: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
