#!/usr/bin/env python3
"""Build a read-only, bounded G5 feedback/behavior/Outbox ChangePlan.

The builder reads a previously captured PASS baseline and the live isolated
MySQL database.  It validates the selected recommendation item, derives stable
interaction UUIDs, and writes one ``S2_CONTROLLED_UPDATE``/``DRY_RUN`` plan.
It never runs migrations, sends HTTP business POSTs, claims Outbox work, or
changes a database row.
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
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

G5_TABLES = (
    "recommendation_impression",
    "recommendation_feedback",
    "user_behavior_event",
    "profile_update_outbox",
    "user_resource_state",
    "profile_replay_run",
    "profile_change_log",
    "user_profile",
    "user_interest_tag",
    "user_negative_preference",
)
PROTECTED_TABLES = (
    "resource_catalog",
    "resource_book_detail",
    "resource_paper_detail",
    "resource_tag",
    "tag_dictionary",
    "resource_index_state",
    "resource_index_build",
    "resource_index_outbox",
    "user_declared_profile",
    "user_declared_profile_history",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def target_snapshot_from_facts(target_facts: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical mutable facts frozen by a G5 plan.

    The snapshot intentionally contains the recommendation ownership chain,
    the complete imported tag rows, user/resource state, Outbox status and
    deterministic-id/latest-behavior guards.  Both the DRY_RUN builder and
    the fail-closed executor use this helper so the hash cannot silently
    describe different facts at review and apply time.
    """

    return {
        "task": target_facts["task"],
        "record": target_facts["record"],
        "item": target_facts["item"],
        "resource_tags": target_facts["resource_tags"],
        "resource_states": target_facts["resource_states"],
        "outbox_statuses": target_facts["outbox_statuses"],
        "uuid_absence": target_facts["uuid_absence"],
        "latest_behavior_at": target_facts["latest_behavior_at"],
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


def parse_utc(value: str, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be an ISO-8601 datetime")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    parsed = parsed.astimezone(UTC)
    return parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
        raise ValueError("git HEAD is not a full commit hash")
    return commit


def load_pass_baseline(path: Path) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label="G5 read-only baseline")
    raw = resolved.read_bytes()
    try:
        evidence = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("G5 read-only baseline is not valid JSON") from exc
    if not isinstance(evidence, dict) or evidence.get("status") != "PASS":
        raise ValueError("G5 read-only baseline must be a PASS object")
    before = evidence.get("before_counts")
    after = evidence.get("after_counts")
    if not isinstance(before, dict) or not isinstance(after, dict) or before != after:
        raise ValueError("G5 read-only baseline must have identical before/after counts")
    g5_before = evidence.get("g5_before_counts")
    g5_after = evidence.get("g5_after_counts")
    if not isinstance(g5_before, dict) or not isinstance(g5_after, dict) or g5_before != g5_after:
        raise ValueError("G5 read-only baseline must contain unchanged G5 counts")
    for table in G5_TABLES:
        if table not in before or int(before[table]) != int(g5_before.get(table, -1)):
            raise ValueError(f"G5 baseline is missing or inconsistent for {table}")
    for key in ("database_writes", "business_posts", "outbox_claims", "external_llm_requests", "actual_delete_count", "files_deleted"):
        if int(evidence.get(key, -1)) != 0:
            raise ValueError(f"G5 baseline is not zero-write for {key}")
    return evidence, raw


async def connect_runtime(values: Mapping[str, str], *, autocommit: bool = True) -> Any:
    return await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=60,
        charset="utf8mb4",
        autocommit=autocommit,
    )


async def read_snapshot(connection: Any) -> tuple[tuple[str, ...], dict[str, int]]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() ORDER BY table_name"
        )
        table_names = tuple(str(row[0]) for row in await cursor.fetchall())
        if any(TABLE_PATTERN.fullmatch(table) is None for table in table_names):
            raise ValueError("database returned an unsafe table identifier")
        counts: dict[str, int] = {}
        for table in table_names:
            await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"count query returned no row for {table}")
            counts[table] = int(row[0])
    return table_names, counts


async def read_identity_and_grants(values: Mapping[str, str]) -> dict[str, Any]:
    connection = await connect_runtime(values)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT probe_id, DATABASE(), CURRENT_USER() "
                "FROM recpro_runtime_probe WHERE probe_id = %s",
                (values["RECPRO_PERSISTENCE_PROBE_ID"],),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("runtime probe identity was not found")
            await cursor.execute("SHOW GRANTS")
            grants = tuple(str(item[0]) for item in await cursor.fetchall() if item)
        if str(row[1]) != values["RECPRO_MYSQL_DATABASE"]:
            raise ValueError("database identity does not match the environment")
        if not GrantSafetyEvaluator(values["RECPRO_MYSQL_DATABASE"]).grants_are_safe(grants):
            raise ValueError("runtime grants failed the least-privilege guard")
        return {
            "probe_id": str(row[0]),
            "database": str(row[1]),
            "current_user": str(row[2]),
            "grants_safe": True,
        }
    finally:
        connection.close()


async def read_target_facts(
    connection: Any,
    *,
    task_id: str,
    record_id: int,
    item_id: int,
    user_id: int,
    resource_id: int,
    uuids: Mapping[str, UUID],
) -> dict[str, Any]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT id, request_id, user_id, trigger_scene, status, context_version "
            "FROM recommendation_task WHERE id = %s",
            (task_id,),
        )
        task = await cursor.fetchone()
        await cursor.execute(
            "SELECT id, task_id, user_id, context_version, output_type "
            "FROM recommendation_record WHERE id = %s",
            (record_id,),
        )
        record = await cursor.fetchone()
        await cursor.execute(
            "SELECT ri.id, ri.record_id, ri.resource_id, ri.rank_no, rc.resource_type, "
            "rc.title, rr.task_id, rr.user_id "
            "FROM recommendation_item AS ri "
            "JOIN recommendation_record AS rr ON rr.id = ri.record_id "
            "JOIN resource_catalog AS rc ON rc.id = ri.resource_id "
            "WHERE ri.id = %s",
            (item_id,),
        )
        item = await cursor.fetchone()
        await cursor.execute(
            "SELECT tag_id, weight, confidence, source FROM resource_tag "
            "WHERE resource_id = %s ORDER BY tag_id, source",
            (resource_id,),
        )
        tags = tuple(
            {
                "tag_id": int(row[0]),
                "weight": float(row[1]),
                "confidence": float(row[2]),
                "source": str(row[3]),
            }
            for row in await cursor.fetchall()
        )
        await cursor.execute(
            "SELECT user_id, resource_id, state_type, state_version "
            "FROM user_resource_state WHERE user_id = %s AND resource_id = %s "
            "ORDER BY state_type",
            (user_id, resource_id),
        )
        resource_states = tuple(
            {
                "user_id": int(row[0]),
                "resource_id": int(row[1]),
                "state_type": str(row[2]),
                "state_version": int(row[3]),
            }
            for row in await cursor.fetchall()
        )
        await cursor.execute(
            "SELECT status, COUNT(*) FROM profile_update_outbox "
            "GROUP BY status ORDER BY status"
        )
        outbox_statuses = {str(row[0]): int(row[1]) for row in await cursor.fetchall()}
        uuid_absence: dict[str, int] = {}
        for name, table, column in (
            ("impression_uuid", "recommendation_impression", "impression_uuid"),
            ("feedback_uuid", "recommendation_feedback", "feedback_uuid"),
            ("behavior_uuid", "user_behavior_event", "event_uuid"),
        ):
            await cursor.execute(f"SELECT COUNT(*) FROM `{table}` WHERE `{column}` = %s", (str(uuids[name]),))
            uuid_absence[name] = int((await cursor.fetchone())[0])
        await cursor.execute(
            "SELECT MAX(occurred_at) FROM user_behavior_event WHERE user_id = %s",
            (user_id,),
        )
        latest_behavior = (await cursor.fetchone())[0]
        await cursor.execute(
            "SELECT COUNT(*) FROM user_profile WHERE user_id = %s",
            (user_id,),
        )
        profile_count = int((await cursor.fetchone())[0])
        await cursor.execute(
            "SELECT COUNT(*) FROM user_interest_tag WHERE user_id = %s",
            (user_id,),
        )
        interest_count = int((await cursor.fetchone())[0])
        await cursor.execute(
            "SELECT COUNT(*) FROM user_negative_preference WHERE user_id = %s",
            (user_id,),
        )
        negative_count = int((await cursor.fetchone())[0])
    if task is None:
        raise ValueError(f"recommendation task does not exist: {task_id}")
    if record is None:
        raise ValueError(f"recommendation record does not exist: {record_id}")
    if item is None:
        raise ValueError(f"recommendation item does not exist: {item_id}")
    task_facts = {
        "id": str(task[0]),
        "request_id": str(task[1]),
        "user_id": int(task[2]),
        "trigger_scene": str(task[3]),
        "status": str(task[4]),
        "context_version": int(task[5]),
    }
    record_facts = {
        "id": int(record[0]),
        "task_id": str(record[1]),
        "user_id": int(record[2]),
        "context_version": int(record[3]),
        "output_type": str(record[4]),
    }
    item_facts = {
        "id": int(item[0]),
        "record_id": int(item[1]),
        "resource_id": int(item[2]),
        "rank_no": int(item[3]),
        "resource_type": str(item[4]),
        "title": str(item[5]),
        "task_id": str(item[6]),
        "user_id": int(item[7]),
    }
    if task_facts["id"] != task_id or task_facts["user_id"] != user_id:
        raise ValueError("task identity or user ownership does not match the plan request")
    if task_facts["status"] != "COMPLETED" or task_facts["context_version"] != 1:
        raise ValueError("target task must be COMPLETED at context_version=1")
    if record_facts["task_id"] != task_id or record_facts["user_id"] != user_id:
        raise ValueError("record identity or user ownership does not match the task")
    if item_facts["record_id"] != record_id or item_facts["resource_id"] != resource_id:
        raise ValueError("recommendation item identity does not match the plan request")
    if item_facts["task_id"] != task_id or item_facts["user_id"] != user_id:
        raise ValueError("recommendation item ownership does not match the task")
    if item_facts["resource_type"] != "BOOK":
        raise ValueError("G5 interaction target must be a BOOK")
    if not tags:
        raise ValueError("target resource must have at least one imported resource_tag row")
    if any(
        tag["tag_id"] < 1
        or not 0 <= tag["weight"] <= 1
        or not 0 <= tag["confidence"] <= 1
        or tag["source"] != "IMPORT"
        for tag in tags
    ):
        raise ValueError("target resource tags must be valid imported rows with bounded weights/confidence")
    if any(state["state_type"] == "HIDDEN" for state in resource_states):
        raise ValueError("target resource already has a HIDDEN user_resource_state")
    if outbox_statuses.get("PENDING", 0) or outbox_statuses.get("PROCESSING", 0):
        raise ValueError(f"existing live profile outbox work would make the bounded worker ambiguous: {outbox_statuses}")
    if any(value != 0 for value in uuid_absence.values()):
        raise ValueError(f"one or more deterministic interaction UUIDs already exist: {uuid_absence}")
    if profile_count != 1:
        raise ValueError("target user must have exactly one current user_profile row")
    return {
        "task": task_facts,
        "record": record_facts,
        "item": item_facts,
        "resource_tags": tags,
        "resource_states": resource_states,
        "outbox_statuses": outbox_statuses,
        "uuid_absence": uuid_absence,
        "latest_behavior_at": latest_behavior.isoformat() if latest_behavior is not None else None,
        "user_profile_count": profile_count,
        "user_interest_count": interest_count,
        "user_negative_count": negative_count,
    }


def target_specs(
    counts: Mapping[str, int], *, project: str, database: str
) -> tuple[dict[str, Any], ...]:
    operations = (
        ("recommendation_impression", "APPEND", 1),
        ("recommendation_feedback", "APPEND", 1),
        ("user_behavior_event", "APPEND", 3),
        ("profile_update_outbox", "APPEND", 2),
        ("user_resource_state", "CREATE", 1),
        ("profile_replay_run", "APPEND", 2),
        ("profile_change_log", "APPEND", 3),
        ("user_interest_tag", "APPEND", 2),
        ("user_negative_preference", "APPEND", 2),
        ("domain_state_transition", "APPEND", 9),
        ("user_profile", "UPDATE_STATUS", 0),
    )
    targets: list[dict[str, Any]] = []
    for table, operation, delta in operations:
        if table not in counts:
            raise ValueError(f"live database snapshot is missing target table: {table}")
        before = int(counts[table])
        targets.append(
            {
                "kind": "MYSQL",
                "identifier": f"{project}.{database}.{table}",
                "operation": operation,
                "expected_before_count": before,
                "expected_after_min_count": before + delta,
            }
        )
    return tuple(targets)


def build_plan(
    *,
    run_id: str,
    baseline_path: Path,
    values: Mapping[str, str],
    task_id: str,
    record_id: int,
    item_id: int,
    user_id: int,
    impression_rendered_at: datetime,
    feedback_occurred_at: datetime,
    behavior_occurred_at: datetime,
    worker_id: str,
    worker_limit: int,
    query_text: str,
    position: int,
    impression_visible_ms: int,
    impression_max_visible_ratio: float,
    direct_behavior_dwell_ms: int,
    direct_behavior_visible_ratio: float,
    baseline: Mapping[str, Any],
    baseline_raw: bytes,
    current_counts: Mapping[str, int],
    target_facts: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    task_uuid = UUID(task_id)
    if isinstance(user_id, bool) or user_id < 1:
        raise ValueError("user id must be positive")
    if not 1 <= worker_limit <= 100:
        raise ValueError("worker limit must be between 1 and 100")
    if not worker_id.strip() or len(worker_id) > 64:
        raise ValueError("worker id must be 3-64 characters")
    if not query_text.strip() or len(query_text) > 2000:
        raise ValueError("query text must contain 1-2000 characters")
    if position < 1 or impression_visible_ms < 1000:
        raise ValueError("position must be positive and impression visible time must be at least 1000ms")
    if not 0.5 <= impression_max_visible_ratio <= 1:
        raise ValueError("impression max visible ratio must be between 0.5 and 1")
    if direct_behavior_dwell_ms < 0 or not 0 <= direct_behavior_visible_ratio <= 1:
        raise ValueError("direct behavior visibility values are out of range")
    if not impression_rendered_at <= feedback_occurred_at <= behavior_occurred_at:
        raise ValueError("interaction timestamps must be ordered impression <= feedback <= behavior")
    interaction_namespace = f"g5-feedback-interaction:{run_id}"
    impression_uuid = uuid5(NAMESPACE_URL, f"{interaction_namespace}:impression")
    feedback_uuid = uuid5(NAMESPACE_URL, f"{interaction_namespace}:feedback")
    behavior_uuid = uuid5(NAMESPACE_URL, f"{interaction_namespace}:behavior")
    behavior_session_id = uuid5(NAMESPACE_URL, f"{interaction_namespace}:session")
    interaction_payload = {
        "user_id": user_id,
        "recommendation_task_id": str(task_uuid),
        "recommendation_record_id": record_id,
        "recommendation_item_id": item_id,
        "resource_id": int(target_facts["item"]["resource_id"]),
        "resource_type": "BOOK",
        "impression_uuid": str(impression_uuid),
        "feedback_uuid": str(feedback_uuid),
        "behavior_uuid": str(behavior_uuid),
        "behavior_session_id": str(behavior_session_id),
        "feedback_type": "NOT_INTERESTED",
        "reason_code": "TOPIC_NOT_INTERESTED",
        "impression_rendered_at": iso_z(impression_rendered_at),
        "impression_visible_started_at": iso_z(impression_rendered_at),
        "feedback_occurred_at": iso_z(feedback_occurred_at),
        "behavior_occurred_at": iso_z(behavior_occurred_at),
        "direct_behavior_type": "CLICK_RECOMMENDATION",
        "query_text": query_text.strip(),
        "position": position,
        "impression_visible_ms": impression_visible_ms,
        "impression_max_visible_ratio": impression_max_visible_ratio,
        "direct_behavior_dwell_ms": direct_behavior_dwell_ms,
        "direct_behavior_visible_ratio": direct_behavior_visible_ratio,
        "worker_id": worker_id,
        "worker_limit": worker_limit,
        "formula_version": "profile-g2-v1",
    }
    commit = current_git_commit()
    project = str(baseline.get("compose_project") or values.get("COMPOSE_PROJECT_NAME") or "")
    database = str(values["RECPRO_MYSQL_DATABASE"])
    if project != str(values.get("COMPOSE_PROJECT_NAME")):
        raise ValueError("baseline Compose project does not match the current environment")
    merged_counts = {str(key): int(value) for key, value in current_counts.items()}
    target_list = list(target_specs(merged_counts, project=project, database=database))
    max_changes = sum(
        int(target["expected_after_min_count"]) - int(target["expected_before_count"])
        for target in target_list
    )
    target_snapshot = target_snapshot_from_facts(target_facts)
    config_path = PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
    interaction_hash = sha256_bytes(canonical(interaction_payload))
    host_fingerprint = "sha256:" + sha256_bytes(
        f"{project}:{database}:{PROJECT_ROOT}:{commit}".encode("utf-8")
    )
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"g5-feedback-worker-plan:{run_id}")),
        "created_at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S2_CONTROLLED_UPDATE",
        "mode": "DRY_RUN",
        "intent": (
            "Prepare one bounded G5 interaction chain for explicit review: append one recommendation "
            "impression, one NOT_INTERESTED/TOPIC_NOT_INTERESTED feedback, one direct CLICK_RECOMMENDATION "
            "behavior, and consume exactly two newly-created profile outbox rows with a limit-2 Worker. "
            "This DRY_RUN plan authorizes no database write."
        ),
        "environment": {
            "environment_id": project,
            "workspace": str(PROJECT_ROOT),
            "host_fingerprint": host_fingerprint,
            "database_identity": f"mysql://{project}/{database}",
            "index_namespace": None,
        },
        "targets": target_list,
        "input_hashes": {
            "g5_feedback_http_readonly_baseline": sha256_bytes(baseline_raw),
            "config_bundle": sha256_bytes(config_path.read_bytes()),
            "interaction_payload": interaction_hash,
            "target_snapshot": sha256_bytes(canonical(target_snapshot)),
            "current_full_counts": sha256_bytes(canonical(dict(sorted(merged_counts.items())))),
        },
        "idempotency_key": str(feedback_uuid),
        "request_run_id": run_id,
        "interaction_payload": interaction_payload,
        "max_changes": max_changes,
        "preconditions": [
            "the supplied G5 feedback HTTP read-only evidence is PASS, hash-identical, zero-write, and its full before/after table counts remain unchanged",
            "the reviewed Git commit and isolated Compose project/database identity remain unchanged immediately before apply",
            "all full information_schema table names and exact expected_before_count values are re-read immediately before apply and match this plan",
            "runtime probe identity and least-privilege grant guard remain PASS; the runtime user is not a migration/root user",
            f"task {task_id}, record {record_id}, item {item_id}, resource {int(target_facts['item']['resource_id'])}, and user {user_id} remain owned and linked exactly as frozen; task is COMPLETED/context_version=1 and resource_type=BOOK",
            f"the target resource retains the exact frozen imported resource_tag rows (tag_ids={','.join(str(tag['tag_id']) for tag in target_facts['resource_tags'])}) and target_snapshot hash {sha256_bytes(canonical(target_snapshot))}, with no HIDDEN user_resource_state for this user/resource",
            "the three deterministic interaction UUIDs are absent, or a retry is accepted only when every persisted payload field is byte-for-byte replay-identical",
            "profile_update_outbox has no pre-existing PENDING or PROCESSING row; feedback and direct behavior each enqueue exactly one new outbox row, while the impression-derived behavior enqueues none",
            "only the eleven MySQL targets in this plan may be touched; recommendation/resource/catalog/declared-profile facts, Neo4j, Chroma, migrations, seed data, and external LLM/network calls are outside the plan",
            "allowed controlled updates are limited to profile_update_outbox status/attempts/lease/error timestamps, user_resource_state suppress_until/source_event_id/last_feedback_at/state_version, and current user_profile/user_interest_tag/user_negative_preference projection columns; all other facts are append-only",
            "the Worker uses the frozen worker_id, formula_version profile-g2-v1, and limit=2, returns exactly two receipts, leaves both new outbox rows DONE, and a second run returns zero receipts without reclaiming DONE or changing row counts",
            "any failure is fail-closed with no destructive table operation, migration, compensating write, Neo4j/Chroma write, or unapproved update; apply requires explicit approval of this unchanged plan_id and plan_hash",
        ],
        "safety_assertions": {
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "overwrite_existing": False,
            "destructive_capabilities_required": False,
            "counts_must_not_decrease": True,
        },
    }
    plan["plan_hash"] = sha256_bytes(canonical(plan))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan)
    )
    if errors:
        locations = ", ".join(
            ".".join(str(item) for item in error.absolute_path) for error in errors
        )
        raise ValueError(f"generated ChangePlan violates schema: {locations}")
    if max_changes != 26:
        raise ValueError(f"bounded G5 delta unexpectedly changed: max_changes={max_changes}")
    return plan


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validate_run_id(args.run_id)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"plan evidence directory already exists: {evidence_dir}")
    baseline_path = resolve_inside_root(args.baseline, label="G5 read-only baseline")
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
    uuids = {
        name: uuid5(NAMESPACE_URL, f"g5-feedback-interaction:{run_id}:{name.removesuffix('_uuid')}")
        for name in ("impression_uuid", "feedback_uuid", "behavior_uuid")
    }
    impression_rendered_at = parse_utc(args.impression_rendered_at, label="impression-rendered-at")
    feedback_occurred_at = parse_utc(args.feedback_occurred_at, label="feedback-occurred-at")
    behavior_occurred_at = parse_utc(args.behavior_occurred_at, label="behavior-occurred-at")
    if not impression_rendered_at <= feedback_occurred_at <= behavior_occurred_at:
        raise ValueError("interaction timestamps must be ordered impression <= feedback <= behavior")
    connection = await connect_runtime(values)
    try:
        table_names, current_counts = await read_snapshot(connection)
        baseline_counts = {str(key): int(value) for key, value in baseline["after_counts"].items()}
        if table_names != tuple(sorted(baseline_counts)):
            raise ValueError("live table set differs from the approved read-only baseline")
        if current_counts != baseline_counts:
            raise ValueError("live full table counts differ from the approved read-only baseline")
        target_facts = await read_target_facts(
            connection,
            task_id=args.task_id,
            record_id=args.record_id,
            item_id=args.item_id,
            user_id=args.user_id,
            resource_id=args.resource_id,
            uuids=uuids,
        )
    finally:
        connection.close()
    identity = await read_identity_and_grants(values)
    worker_id = args.worker_id or f"g5-{run_id}"
    plan = build_plan(
        run_id=run_id,
        baseline_path=baseline_path,
        values=values,
        task_id=args.task_id,
        record_id=args.record_id,
        item_id=args.item_id,
        user_id=args.user_id,
        impression_rendered_at=impression_rendered_at,
        feedback_occurred_at=feedback_occurred_at,
        behavior_occurred_at=behavior_occurred_at,
        worker_id=worker_id,
        worker_limit=args.worker_limit,
        query_text=args.query_text,
        position=args.position,
        impression_visible_ms=args.impression_visible_ms,
        impression_max_visible_ratio=args.impression_max_visible_ratio,
        direct_behavior_dwell_ms=args.direct_behavior_dwell_ms,
        direct_behavior_visible_ratio=args.direct_behavior_visible_ratio,
        baseline=baseline,
        baseline_raw=baseline_raw,
        current_counts=current_counts,
        target_facts=target_facts,
        identity=identity,
    )
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output = evidence_dir / "g5-feedback-worker-change-plan.json"
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "PLAN_PENDING_APPROVAL",
        "run_id": run_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "plan_path": str(output),
        "git_commit": plan["git_commit"],
        "target": {
            "task_id": args.task_id,
            "record_id": args.record_id,
            "recommendation_item_id": args.item_id,
            "resource_id": int(target_facts["item"]["resource_id"]),
            "resource_title": target_facts["item"]["title"],
            "user_id": args.user_id,
        },
        "interaction_uuids": plan["interaction_payload"],
        "max_changes": plan["max_changes"],
        "database_writes": 0,
        "outbox_claims": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "identity": identity,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--task-id", default="b476b901-b78e-5c3e-afd9-6fc880f20623")
    parser.add_argument("--record-id", type=int, default=24)
    parser.add_argument("--item-id", type=int, default=128)
    parser.add_argument("--resource-id", type=int, default=6452)
    parser.add_argument("--user-id", type=int, default=1001)
    parser.add_argument("--impression-rendered-at", default="2026-08-12T00:55:00Z")
    parser.add_argument("--feedback-occurred-at", default="2026-08-12T00:55:00Z")
    parser.add_argument("--behavior-occurred-at", default="2026-08-12T00:56:00Z")
    parser.add_argument("--worker-id")
    parser.add_argument("--worker-limit", type=int, default=2)
    parser.add_argument("--query-text", default="多智能体系统与智慧图书馆")
    parser.add_argument("--position", type=int, default=1)
    parser.add_argument("--impression-visible-ms", type=int, default=1500)
    parser.add_argument("--impression-max-visible-ratio", type=float, default=0.8)
    parser.add_argument("--direct-behavior-dwell-ms", type=int, default=2000)
    parser.add_argument("--direct-behavior-visible-ratio", type=float, default=0.9)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(execute(args))
    except (OSError, RuntimeError, ValueError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] G5 feedback/behavior DRY_RUN plan was not generated: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
