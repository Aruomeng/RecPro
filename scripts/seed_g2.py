"""Load the deterministic G2 fixture with insert-only, idempotent writes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import asyncmy

from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = PROJECT_ROOT / "contracts/data/g2/seed-v1.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def validate_seed(seed: object) -> dict[str, Any]:
    if not isinstance(seed, dict):
        raise ValueError("G2 seed must be a JSON object")
    for key in ("seed_version", "dataset_version", "tags", "resources", "behaviors", "declared_profiles"):
        if key not in seed:
            raise ValueError(f"G2 seed is missing {key}")
    if not isinstance(seed["tags"], list) or not isinstance(seed["resources"], list):
        raise ValueError("G2 seed tags and resources must be arrays")
    if not isinstance(seed["behaviors"], list) or not isinstance(seed["declared_profiles"], list):
        raise ValueError("G2 seed behaviors and declared_profiles must be arrays")
    return seed


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def db_decimal(value: object) -> Decimal:
    """Convert fixture numbers through text so MySQL receives exact decimals."""

    return Decimal(str(value))


async def insert_seed(
    *,
    host_port: int,
    database: str,
    migration_user: str,
    migration_password: str,
    seed: dict[str, Any],
    env_values: dict[str, str],
    source_hash: str,
) -> dict[str, int | str | bool]:
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
    created_at = datetime.now(UTC).replace(tzinfo=None)
    seed_version = str(seed["seed_version"])
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT seed_version FROM g2_seed_run WHERE seed_version = %s",
                (seed_version,),
            )
            if await cursor.fetchone() is not None:
                await connection.rollback()
                return {"seed_version": seed_version, "applied": False, "resource_count": 0, "tag_count": 0, "behavior_count": 0}

            tag_ids: dict[str, int] = {}
            for tag in seed["tags"]:
                await cursor.execute(
                    "INSERT IGNORE INTO tag_dictionary "
                    "(name, normalized_name, status, created_at, updated_at) "
                    "VALUES (%s, %s, 'ACTIVE', %s, %s)",
                    (tag["name"], tag["normalized_name"], created_at, created_at),
                )
                await cursor.execute(
                    "SELECT id FROM tag_dictionary WHERE normalized_name = %s",
                    (tag["normalized_name"],),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("seed tag could not be resolved after insert")
                tag_ids[str(tag["normalized_name"])] = int(row[0])

            resource_ids: dict[str, int] = {}
            for resource in seed["resources"]:
                resource_type = str(resource["resource_type"])
                external_id = str(resource["external_id"])
                await cursor.execute(
                    "INSERT IGNORE INTO resource_catalog "
                    "(resource_type, external_id, title, authors_json, abstract_text, "
                    "keywords_json, category_code, publication_year, publication_date, "
                    "publisher_or_source, language, difficulty_level, availability_status, "
                    "available_from, access_url, metadata_quality, is_classic, metadata_version, "
                    "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        resource_type,
                        external_id,
                        resource["title"],
                        canonical_json(resource.get("authors", [])),
                        resource.get("abstract"),
                        canonical_json(resource.get("keywords", [])),
                        resource.get("category_code"),
                        resource.get("publication_year"),
                        resource.get("publication_date"),
                        resource.get("publisher_or_source"),
                        resource.get("language"),
                        resource.get("difficulty_level"),
                        resource["availability_status"],
                        parse_utc(resource["available_from"]),
                        resource.get("access_url"),
                        db_decimal(resource["metadata_quality"]),
                        bool(resource.get("is_classic", False)),
                        1,
                        created_at,
                        created_at,
                    ),
                )
                await cursor.execute(
                    "SELECT id FROM resource_catalog WHERE resource_type = %s AND external_id = %s",
                    (resource_type, external_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("seed resource could not be resolved after insert")
                resource_id = int(row[0])
                resource_ids[external_id] = resource_id
                if resource_type == "BOOK":
                    await cursor.execute(
                        "INSERT IGNORE INTO resource_book_detail "
                        "(resource_id, isbn, call_number, location, borrowable_copies) VALUES (%s, %s, %s, %s, %s)",
                        (resource_id, resource.get("isbn"), resource.get("call_number"), resource.get("location"), resource.get("borrowable_copies", 0)),
                    )
                else:
                    await cursor.execute(
                        "INSERT IGNORE INTO resource_paper_detail "
                        "(resource_id, doi, journal_or_conference, open_access) VALUES (%s, %s, %s, %s)",
                        (resource_id, resource.get("doi"), resource.get("journal_or_conference"), bool(resource.get("open_access", False))),
                    )
                resource_hash = sha256_bytes(canonical_json(resource).encode("utf-8"))
                await cursor.execute(
                    "INSERT IGNORE INTO resource_index_state "
                    "(resource_id, content_hash, embedding_status, graph_status) VALUES (%s, %s, 'PENDING', 'PENDING')",
                    (resource_id, resource_hash),
                )
                for tag in resource.get("tags", []):
                    await cursor.execute(
                        "INSERT IGNORE INTO resource_tag "
                        "(resource_id, tag_id, weight, confidence, source, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                        (resource_id, tag_ids[str(tag["normalized_name"])], db_decimal(tag["weight"]), db_decimal(tag["confidence"]), tag.get("source", "IMPORT"), created_at),
                    )

            for profile in seed["declared_profiles"]:
                values = (
                    int(profile["user_id"]),
                    int(profile["declared_version"]),
                    profile.get("major"),
                    profile.get("grade"),
                    profile.get("research_direction"),
                    profile.get("preferred_language"),
                    bool(profile.get("personalization_enabled", True)),
                    parse_utc(profile["valid_from"]),
                    created_at,
                )
                await cursor.execute(
                    "INSERT IGNORE INTO user_declared_profile_history "
                    "(user_id, declared_version, major, grade, research_direction, preferred_language, "
                    "personalization_enabled, valid_from, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    values,
                )
                await cursor.execute(
                    "INSERT IGNORE INTO user_declared_profile "
                    "(user_id, declared_version, major, grade, research_direction, preferred_language, personalization_enabled, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (values[0], values[1], values[2], values[3], values[4], values[5], values[6], created_at),
                )

            behavior_count = 0
            for behavior in seed["behaviors"]:
                resource_id = resource_ids.get(str(behavior["resource_external_id"]))
                if resource_id is None:
                    raise ValueError("behavior references an unknown resource")
                await cursor.execute(
                    "INSERT IGNORE INTO user_behavior_event "
                    "(event_uuid, user_id, session_id, event_type, resource_id, rating, reason_code, occurred_at, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (behavior["event_uuid"], int(behavior["user_id"]), behavior["session_id"], behavior["event_type"], resource_id, db_decimal(behavior["rating"]) if behavior.get("rating") is not None else None, behavior.get("reason_code"), parse_utc(behavior["occurred_at"]), created_at),
                )
                await cursor.execute(
                    "SELECT id FROM user_behavior_event WHERE event_uuid = %s",
                    (behavior["event_uuid"],),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("seed behavior could not be resolved after insert")
                event_id = int(row[0])
                await cursor.execute(
                    "INSERT IGNORE INTO profile_update_outbox "
                    "(user_id, source_event_id, source_type, payload_json, status, created_at, updated_at) "
                    "VALUES (%s, %s, 'BEHAVIOR', %s, 'PENDING', %s, %s)",
                    (int(behavior["user_id"]), event_id, canonical_json(behavior), created_at, created_at),
                )
                behavior_count += 1

            bundle_path = PROJECT_ROOT / str(env_values["RECPRO_CONFIG_BUNDLE_PATH"])
            bundle_json = json.loads(bundle_path.read_text(encoding="utf-8"))
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_config_version "
                "(config_bundle_version, policy_version, ranking_version, behavior_formula_version, prompt_version, bundle_json, config_hash, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s)",
                (env_values["RECPRO_CONFIG_BUNDLE_VERSION"], "policy-g2-v1", "ranking-g2-v1", "profile-g2-v1", "prompt-g1-v1", canonical_json(bundle_json), env_values["RECPRO_CONFIG_BUNDLE_SHA256"], created_at),
            )
            await cursor.execute(
                "INSERT IGNORE INTO g2_seed_run "
                "(seed_version, source_sha256, resource_count, tag_count, behavior_count, applied_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (seed_version, source_hash, len(seed["resources"]), len(seed["tags"]), behavior_count, created_at),
            )
        await connection.commit()
        return {"seed_version": seed_version, "applied": True, "resource_count": len(seed["resources"]), "tag_count": len(seed["tags"]), "behavior_count": behavior_count}
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--apply", action="store_true", help="execute insert-only seed writes")
    return parser


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    env_values = read_env(args.env_file.resolve())
    issues = validate_compose(env_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    migration_user = env_values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    migration_password = env_values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if not migration_user or not migration_password:
        raise ValueError("G2 migration credentials are required")
    seed_path = args.seed_file.resolve()
    seed_bytes = seed_path.read_bytes()
    seed_source_hash = sha256_bytes(seed_bytes)
    seed = validate_seed(json.loads(seed_bytes.decode("utf-8")))
    evidence_path = PROJECT_ROOT / "artifacts" / "verification" / "g2" / run_id / "seed.json"
    if not args.apply:
        evidence_path.parent.mkdir(parents=True, exist_ok=False)
        evidence_path.write_text(json.dumps({"schema_version": "g2-seed-evidence-v1", "run_id": run_id, "status": "DRY_RUN", "seed_version": seed["seed_version"], "seed_sha256": seed_source_hash, "resource_count": len(seed["resources"]), "tag_count": len(seed["tags"]), "behavior_count": len(seed["behaviors"]), "destructive_actions": 0, "applied": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[PASS] G2 seed dry-run: {evidence_path}")
        return 0
    result = await insert_seed(host_port=int(env_values["RECPRO_MYSQL_HOST_PORT"]), database=env_values["RECPRO_MYSQL_DATABASE"], migration_user=migration_user, migration_password=migration_password, seed=seed, env_values=env_values, source_hash=seed_source_hash)
    evidence_path.parent.mkdir(parents=True, exist_ok=False)
    evidence_path.write_text(json.dumps({"schema_version": "g2-seed-evidence-v1", "run_id": run_id, "status": "APPLIED" if result["applied"] else "IDEMPOTENT_NOOP", "seed_version": seed["seed_version"], "seed_sha256": seed_source_hash, **result, "destructive_actions": 0}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] G2 seed result: {evidence_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] G2 seed did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
