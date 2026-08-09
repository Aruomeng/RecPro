"""Run the deterministic G3 recommendation slice against the MySQL fact layer."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy

from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.recommendation.application.public import execute_recommendation
from backend.app.recommendation.domain.public import ProfileSignal, RecommendationRequest
from scripts.build_g2_dataset_report import build_reports
from scripts.seed_g2 import DEFAULT_SEED, validate_seed
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
DECIMAL_6 = Decimal("0.000001")


def db_decimal(value: float | int) -> Decimal:
    return Decimal(str(value)).quantize(DECIMAL_6, rounding=ROUND_HALF_UP)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def public_payload(*, task_id: str, trace_id: str, evaluation_at: datetime, execution: Any, versions: dict[str, str], record_id: int | None) -> dict[str, object]:
    return {
        "task_id": task_id,
        "record_id": record_id,
        "trace_id": trace_id,
        "status": "COMPLETED",
        "context_version": 1,
        "evaluation_at": evaluation_at.isoformat() + "Z",
        "decision": {
            "output_type": "TOPIC_RESOURCES",
            "delivery_strategy": "DIRECT",
            "explanation_level": "EVIDENCE",
            "adaptation_state": "NORMAL",
            "decision_reason_codes": list(execution.decision_reason_codes),
            "decision_reason": "；".join(execution.decision_reason_codes),
            "policy_version": versions["policy"],
        },
        "items": [
            {
                "item_id": item.rank_no,
                "resource": {
                    "resource_id": item.feature.resource.id,
                    "resource_type": item.feature.resource.resource_type,
                    "title": item.feature.resource.title,
                    "authors": list(item.feature.resource.authors),
                    "publication_year": item.feature.resource.publication_year,
                    "availability_status": item.feature.resource.availability_status,
                },
                "rank_no": item.rank_no,
                "reason_summary": item.explanation,
                "evidence_confidence": item.feature.evidence_confidence,
            }
            for item in execution.items
        ],
        "warnings": list(execution.warnings),
        "versions": versions,
        "trace_steps": list(execution.trace_steps),
    }


async def _read_inputs(connection: Any, *, user_id: int, evaluation_at: datetime) -> tuple[Any, tuple[Any, ...], tuple[ProfileSignal, ...], tuple[tuple[int, str], ...]]:
    repository = MySQLCatalogRepository(connection)
    resources = await repository.list_resources(available_at=evaluation_at)
    tags = await repository.list_resource_tags(resource_ids=tuple(resource.id for resource in resources))
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT tag_id, positive_weight FROM user_interest_tag WHERE user_id = %s ORDER BY tag_id",
            (user_id,),
        )
        positive = [ProfileSignal(int(row[0]), float(row[1]), False) for row in await cursor.fetchall()]
        await cursor.execute(
            "SELECT tag_id, negative_weight FROM user_negative_preference WHERE user_id = %s ORDER BY tag_id",
            (user_id,),
        )
        negative = [ProfileSignal(int(row[0]), float(row[1]), True) for row in await cursor.fetchall()]
        await cursor.execute(
            "SELECT resource_id, event_type FROM user_behavior_event "
            "WHERE user_id = %s AND occurred_at <= %s AND resource_id IS NOT NULL "
            "ORDER BY occurred_at, id",
            (user_id, evaluation_at),
        )
        events = tuple((int(row[0]), str(row[1])) for row in await cursor.fetchall())
    return resources, tags, tuple(positive + negative), events


async def run_demo(
    *,
    host_port: int,
    database: str,
    migration_user: str,
    migration_password: str,
    user_id: int,
    input_text: str,
    evaluation_at: datetime,
    limit: int,
    apply: bool,
) -> dict[str, object]:
    seed_bytes = DEFAULT_SEED.read_bytes()
    seed = validate_seed(json.loads(seed_bytes.decode("utf-8")))
    manifest, quality = build_reports(seed, seed_path=DEFAULT_SEED, seed_bytes=seed_bytes)
    versions = {
        "config_bundle": "rec-1.0.0",
        "policy": "policy-g3-v1",
        "ranking": "ranking-g3-v1",
        "behavior_formula": "profile-g2-v1",
        "embedding": "disabled-g3-mysql-only-v1",
        "graph": "disabled-g3-mysql-only-v1",
        "prompt": "template-g3-v1",
        "dataset": str(manifest["dataset_version"]),
    }
    request_id = uuid5(NAMESPACE_URL, f"g3:{user_id}:{input_text}:{evaluation_at.isoformat()}:{limit}")
    task_id = uuid5(NAMESPACE_URL, f"task:{request_id}")
    trace_id = uuid5(NAMESPACE_URL, f"trace:{request_id}")
    session_id = uuid5(NAMESPACE_URL, f"session:{user_id}:{evaluation_at.date().isoformat()}")
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=host_port,
        user=migration_user,
        password=migration_password,
        db=database,
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT id FROM recommendation_task WHERE user_id = %s AND request_id = %s", (user_id, str(request_id)))
            existing = await cursor.fetchone()
        if existing is not None:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT id FROM recommendation_record WHERE task_id = %s", (str(existing[0]),))
                existing_record = await cursor.fetchone()
                existing_record_id = int(existing_record[0]) if existing_record is not None else None
                existing_item_count = 0
                existing_candidate_count = 0
                if existing_record_id is not None:
                    await cursor.execute("SELECT COUNT(*) FROM recommendation_item WHERE record_id = %s", (existing_record_id,))
                    existing_item_count = int((await cursor.fetchone())[0])
                    await cursor.execute("SELECT COUNT(*) FROM recommendation_candidate WHERE task_id = %s", (str(existing[0]),))
                    existing_candidate_count = int((await cursor.fetchone())[0])
            await connection.rollback()
            return {
                "applied": False,
                "idempotent_replay": True,
                "task_id": str(task_id),
                "trace_id": str(trace_id),
                "record_id": existing_record_id,
                "item_count": existing_item_count,
                "candidate_count": existing_candidate_count,
                "versions": versions,
                "destructive_actions": 0,
            }
        resources, tags, profile_signals, events = await _read_inputs(connection, user_id=user_id, evaluation_at=evaluation_at)
        request = RecommendationRequest(user_id, input_text, ("BOOK", "PAPER"), limit, evaluation_at)
        execution = execute_recommendation(
            request,
            resources=resources,
            tags=tags,
            profile_signals=profile_signals,
            behavior_events=events,
        )
        if not apply:
            await connection.rollback()
            return {
                "applied": False,
                "idempotent_replay": False,
                "task_id": str(task_id),
                "trace_id": str(trace_id),
                "record_id": None,
                "item_count": len(execution.items),
                "candidate_count": len(execution.items) * 3,
                "result": public_payload(task_id=str(task_id), trace_id=str(trace_id), evaluation_at=evaluation_at, execution=execution, versions=versions, record_id=None),
                "data_quality": quality,
                "destructive_actions": 0,
            }
        now = datetime.now(UTC).replace(tzinfo=None)
        request_json = {
            "user_id": user_id,
            "input_text": input_text,
            "resource_types": ["BOOK", "PAPER"],
            "limit": limit,
            "evaluation_at": evaluation_at.isoformat(),
        }
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO recommendation_task "
                "(id, request_id, trace_id, user_id, session_id, trigger_scene, input_text, request_json, intent_type, intent_confidence, status, context_version, profile_version, config_bundle_version, policy_version, ranking_version, behavior_formula_version, dataset_version, replan_count, evaluation_at, started_at, finished_at, created_at) "
                "VALUES (%s, %s, %s, %s, %s, 'SEARCH_AFTER', %s, %s, %s, %s, 'COMPLETED', 1, NULL, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s)",
                (str(task_id), str(request_id), str(trace_id), user_id, str(session_id), input_text, canonical_json(request_json), execution.intent.intent_type, db_decimal(execution.intent.confidence), versions["config_bundle"], versions["policy"], versions["ranking"], versions["behavior_formula"], versions["dataset"], evaluation_at, now, now, now),
            )
            for item in execution.items:
                for channel, score in item.feature.channel_scores.items():
                    await cursor.execute(
                        "INSERT INTO recommendation_candidate "
                        "(task_id, plan_version, resource_id, channel, channel_rank, raw_score, normalized_score, rrf_contribution, evidence_json, created_at) "
                        "VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (str(task_id), item.feature.resource.id, channel, item.feature.channel_ranks[channel], db_decimal(score), db_decimal(score), db_decimal(score / (60 + item.feature.channel_ranks[channel])), canonical_json({"resource_id": item.feature.resource.id, "channel": channel}), now),
                    )
            decision = public_payload(task_id=str(task_id), trace_id=str(trace_id), evaluation_at=evaluation_at, execution=execution, versions=versions, record_id=None)["decision"]
            await cursor.execute(
                "INSERT INTO recommendation_record "
                "(task_id, user_id, context_version, output_type, delivery_strategy, ranking_version, decision_json, warnings_json, versions_json, created_at) "
                "VALUES (%s, %s, 1, 'TOPIC_RESOURCES', 'DIRECT', %s, %s, %s, %s, %s)",
                (str(task_id), user_id, versions["ranking"], canonical_json(decision), canonical_json(list(execution.warnings)), canonical_json(versions), now),
            )
            await cursor.execute("SELECT LAST_INSERT_ID()")
            record_id = int((await cursor.fetchone())[0])
            for item in execution.items:
                await cursor.execute(
                    "INSERT INTO recommendation_item "
                    "(record_id, resource_id, rank_no, relevance_score, final_score, mmr_score, evidence_confidence, primary_channel, score_detail_json, reason_evidence_json, diversity_relaxed, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (record_id, item.feature.resource.id, item.rank_no, db_decimal(item.feature.final_score), db_decimal(item.feature.final_score), db_decimal(item.feature.final_score), db_decimal(item.feature.evidence_confidence), item.feature.primary_channel, canonical_json({"channel_scores": item.feature.channel_scores, "channel_ranks": item.feature.channel_ranks, "rrf_score": item.feature.rrf_score, "negative_penalty": item.feature.negative_penalty}), canonical_json(list(item.evidence_refs)), item.feature.diversity_relaxed, now),
                )
                await cursor.execute("SELECT LAST_INSERT_ID()")
                item_id = int((await cursor.fetchone())[0])
                await cursor.execute(
                    "INSERT INTO recommendation_item_explanation "
                    "(recommendation_item_id, explanation_version, explanation_text, effective_explanation_level, provider, validator_status, evidence_refs_json, created_at) "
                    "VALUES (%s, 1, %s, 'EVIDENCE', 'TEMPLATE', 'PASSED', %s, %s)",
                    (item_id, item.explanation, canonical_json(list(item.evidence_refs)), now),
                )
            await cursor.execute(
                "INSERT INTO recommendation_trace (trace_id, task_id, schema_version, steps_json, complete, created_at) VALUES (%s, %s, 'g3-trace-v1', %s, TRUE, %s)",
                (str(trace_id), str(task_id), canonical_json(list(execution.trace_steps)), now),
            )
        await connection.commit()
        return {
            "applied": apply,
            "idempotent_replay": False,
            "task_id": str(task_id),
            "trace_id": str(trace_id),
            "record_id": record_id if apply else None,
            "item_count": len(execution.items),
            "candidate_count": len(execution.items) * 3,
            "result": public_payload(task_id=str(task_id), trace_id=str(trace_id), evaluation_at=evaluation_at, execution=execution, versions=versions, record_id=record_id if apply else None),
            "data_quality": quality,
            "destructive_actions": 0,
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
    parser.add_argument("--input-text", required=True)
    parser.add_argument("--evaluation-at", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--apply", action="store_true")
    return parser


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    if args.user_id <= 0:
        raise ValueError("user id must be positive")
    if not args.input_text.strip() or len(args.input_text) > 500:
        raise ValueError("input text must contain 1-500 characters")
    values = read_env(args.env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not user or not password:
        raise ValueError("G3 migration credentials are required")
    result = await run_demo(
        host_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        database=values["RECPRO_MYSQL_DATABASE"],
        migration_user=user,
        migration_password=password,
        user_id=args.user_id,
        input_text=args.input_text,
        evaluation_at=parse_utc(args.evaluation_at),
        limit=args.limit,
        apply=args.apply,
    )
    path = PROJECT_ROOT / "artifacts" / "verification" / "g3" / run_id / "demo.json"
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps({"schema_version": "g3-demo-evidence-v1", "run_id": run_id, **result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] G3 demo recommendation: {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G3 demo did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
