"""Safely append a reviewed book catalog plan to the isolated RecPro MySQL.

The default mode is database-free and only validates the plan artifacts.  A
write requires both ``--apply`` and ``--confirm-mysql-write``.  Existing rows
are never rewritten: the importer uses ``INSERT IGNORE`` and blocks before the
transaction when an existing resource, tag, or index state conflicts with the
reviewed plan.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import asyncmy

from scripts.build_mysql_book_plan import PROJECT_ROOT, TABLE_NAMES, canonical_json, sha256_bytes
from scripts.validate_runtime_env import read_env, validate_compose


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
GRAPH_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
SAFE_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
PLAN_SCHEMA_VERSION = "mysql-book-plan-v1"
ALLOWED_LICENSE_STATUSES = {"CONFIRMED_LOCAL_RESEARCH", "LICENSED_OPEN_DATA"}
PLAN_STATUSES = {"READY_FOR_MYSQL_REVIEW", "PASS_WITH_WARNINGS"}
CHUNK_SIZE = 400


class _ExpectedDuplicateWarningFilter(logging.Filter):
    """Keep asyncmy's expected INSERT IGNORE warnings out of evidence logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.getMessage()).startswith("Duplicate entry ")


@contextmanager
def _suppress_expected_duplicate_warnings():
    # asyncmy.cursors uses ``logging.getLogger(__package__)``, i.e. ``asyncmy``.
    logger = logging.getLogger("asyncmy")
    warning_filter = _ExpectedDuplicateWarningFilter()
    logger.addFilter(warning_filter)
    try:
        yield
    finally:
        logger.removeFilter(warning_filter)


def resolve_repository_path(value: str | Path, *, label: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id has an unsafe format")
    return value


def load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def load_rows(path: Path, *, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} cannot be read: {type(exc).__name__}") from exc
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} line {line_no} is invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} line {line_no} must be an object")
        rows.append(value)
    return rows


def _require_keys(row: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    if set(row) != expected:
        missing = sorted(expected - set(row))
        unknown = sorted(set(row) - expected)
        raise ValueError(f"{label} fields mismatch (missing={missing}, unknown={unknown})")


def _require_text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be a non-blank string of at most {maximum} characters")
    return value


def _validate_rows(plan: Mapping[str, Any], rows_by_table: Mapping[str, list[dict[str, Any]]]) -> None:
    expected_fields = {
        "resource_catalog": {"resource_type", "external_id", "title", "authors", "abstract", "keywords", "category_code", "publication_year", "publication_date", "publisher_or_source", "language", "difficulty_level", "availability_status", "available_from", "access_url", "metadata_quality", "is_classic", "metadata_version"},
        "resource_book_detail": {"external_id", "isbn", "call_number", "location", "borrowable_copies"},
        "tag_dictionary": {"name", "normalized_name", "kind"},
        "resource_tag": {"external_id", "normalized_name", "weight", "confidence", "source"},
        "resource_index_state": {"external_id", "content_hash", "embedding_status", "graph_status", "graph_version"},
    }
    for table in TABLE_NAMES:
        if table not in rows_by_table:
            raise ValueError(f"plan is missing {table} artifact")
        if int(plan["table_counts"][table]) != len(rows_by_table[table]):
            raise ValueError(f"{table} count does not match plan")
        for row in rows_by_table[table]:
            _require_keys(row, expected_fields[table], label=table)

    catalog_ids: set[str] = set()
    for row in rows_by_table["resource_catalog"]:
        if row["resource_type"] != "BOOK" or row["availability_status"] != "REFERENCE_ONLY":
            raise ValueError("catalog rows must be BOOK and REFERENCE_ONLY")
        external_id = _require_text(row["external_id"], label="resource external_id", maximum=128)
        _require_text(row["title"], label="resource title", maximum=500)
        if external_id in catalog_ids:
            raise ValueError("catalog contains duplicate external_id")
        catalog_ids.add(external_id)
        if not isinstance(row["authors"], list) or not isinstance(row["keywords"], list):
            raise ValueError("authors and keywords must be arrays")
        if not isinstance(row["metadata_quality"], (int, float)) or not 0 <= float(row["metadata_quality"]) <= 1:
            raise ValueError("metadata_quality must be between 0 and 1")
        if row["metadata_version"] != 1 or not isinstance(row["is_classic"], bool):
            raise ValueError("catalog immutable version fields are invalid")
        if row["category_code"] is not None and len(str(row["category_code"])) > 64:
            raise ValueError("catalog category_code exceeds MySQL field limit")
        if row["publisher_or_source"] is not None and len(str(row["publisher_or_source"])) > 500:
            raise ValueError("catalog publisher_or_source exceeds MySQL field limit")
        if row["language"] is not None and len(str(row["language"])) > 16:
            raise ValueError("catalog language exceeds MySQL field limit")
        if row["access_url"] is not None and len(str(row["access_url"])) > 1000:
            raise ValueError("catalog access_url exceeds MySQL field limit")

    for row in rows_by_table["resource_book_detail"]:
        for field, maximum in (("isbn", 32), ("call_number", 128), ("location", 255)):
            if row[field] is not None and len(str(row[field])) > maximum:
                raise ValueError(f"book detail {field} exceeds MySQL field limit")
    detail_ids = {str(row["external_id"]) for row in rows_by_table["resource_book_detail"]}
    index_ids = {str(row["external_id"]) for row in rows_by_table["resource_index_state"]}
    if detail_ids != catalog_ids or index_ids != catalog_ids:
        raise ValueError("book detail and index rows must cover exactly the catalog resources")

    tag_ids: set[str] = set()
    for row in rows_by_table["tag_dictionary"]:
        name = _require_text(row["name"], label="tag name", maximum=128)
        normalized = _require_text(row["normalized_name"], label="normalized tag name", maximum=128)
        if normalized in tag_ids:
            raise ValueError("tag dictionary contains duplicate normalized_name")
        tag_ids.add(normalized)
        if row["kind"] not in {"kw", "topic", "clc"} or len(name) > 128:
            raise ValueError("tag dictionary row has an unsupported kind")

    for row in rows_by_table["resource_tag"]:
        if str(row["external_id"]) not in catalog_ids or str(row["normalized_name"]) not in tag_ids:
            raise ValueError("resource_tag references an unknown resource or tag")
        if row["source"] != "IMPORT" or not all(isinstance(row[key], (int, float)) and 0 <= float(row[key]) <= 1 for key in ("weight", "confidence")):
            raise ValueError("resource_tag scores or source are invalid")

    for row in rows_by_table["resource_index_state"]:
        if not SHA256_PATTERN.fullmatch(str(row["content_hash"])):
            raise ValueError("resource index content hash is invalid")
        if row["embedding_status"] != "PENDING" or row["graph_status"] != "READY":
            raise ValueError("resource index state must start PENDING/READY")
        if GRAPH_VERSION_PATTERN.fullmatch(str(row["graph_version"])) is None or str(row["graph_version"]) != str(plan["graph_version"]):
            raise ValueError("resource index graph version is invalid")


def verify_plan(plan_dir: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    plan_path = plan_dir / "mysql-book-plan.json"
    plan = load_object(plan_path, label="MySQL book plan")
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported MySQL book plan schema version")
    if plan.get("status") not in PLAN_STATUSES or plan.get("can_import") is not True:
        raise ValueError("MySQL book plan is not ready for import review")
    if plan.get("license_status") not in ALLOWED_LICENSE_STATUSES:
        raise ValueError("MySQL book plan requires an explicit source license status")
    source_plan = resolve_repository_path(str(plan.get("source_graph_plan", "")), label="source graph plan")
    if not source_plan.is_file() or sha256_bytes(source_plan.read_bytes()) != plan.get("source_graph_plan_sha256"):
        raise ValueError("source graph plan hash does not match the reviewed MySQL plan")
    artifacts = plan.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("MySQL plan artifacts metadata is missing")
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    for table in TABLE_NAMES:
        metadata = artifacts.get(table)
        if not isinstance(metadata, Mapping):
            raise ValueError(f"{table} artifact metadata is missing")
        artifact_path = resolve_repository_path(str(metadata.get("path", "")), label=f"{table} artifact")
        if not artifact_path.is_file() or sha256_bytes(artifact_path.read_bytes()) != metadata.get("sha256"):
            raise ValueError(f"{table} artifact hash does not match the reviewed plan")
        rows = load_rows(artifact_path, label=table)
        if len(rows) != int(metadata.get("count", -1)):
            raise ValueError(f"{table} artifact count does not match metadata")
        rows_by_table[table] = rows
    _validate_rows(plan, rows_by_table)
    if int(plan["book_count"]) != len(rows_by_table["resource_catalog"]):
        raise ValueError("book_count does not match resource_catalog artifact")
    if int(plan["tag_count"]) != len(rows_by_table["tag_dictionary"]):
        raise ValueError("tag_count does not match tag_dictionary artifact")
    if int(plan["resource_tag_count"]) != len(rows_by_table["resource_tag"]):
        raise ValueError("resource_tag_count does not match resource_tag artifact")
    return plan, rows_by_table


def _chunks(values: Sequence[Any], size: int = CHUNK_SIZE) -> tuple[Sequence[Any], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))


def _placeholders(count: int) -> str:
    if count < 1:
        raise ValueError("query placeholder list cannot be empty")
    return ",".join("%s" for _ in range(count))


async def _connection(values: Mapping[str, str]) -> Any:
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


async def _target_snapshot(connection: Any, *, database: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"tables": {}, "row_counts": {}, "read_queries": 0}
    async with connection.cursor() as cursor:
        for table in TABLE_NAMES:
            if SAFE_TABLE_NAME.fullmatch(table) is None:
                raise ValueError("unsafe table identifier")
            await cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                (database, table),
            )
            snapshot["read_queries"] += 1
            row = await cursor.fetchone()
            snapshot["tables"][table] = bool(row and int(row[0]) == 1)
        if not all(snapshot["tables"].values()):
            raise ValueError("one or more required MySQL catalog tables are missing")
        for table in TABLE_NAMES:
            await cursor.execute(f"SELECT COUNT(*) FROM {table}")
            snapshot["read_queries"] += 1
            row = await cursor.fetchone()
            snapshot["row_counts"][table] = int(row[0]) if row else 0
    return snapshot


async def _existing_conflicts(
    connection: Any,
    *,
    catalog_rows: Sequence[Mapping[str, Any]],
    tag_rows: Sequence[Mapping[str, Any]],
    index_graph_version: str,
) -> dict[str, Any]:
    existing_resources: dict[str, dict[str, Any]] = {}
    existing_tags: dict[str, str] = {}
    resource_ids: dict[str, int] = {}
    read_queries = 0
    async with connection.cursor() as cursor:
        external_ids = [str(row["external_id"]) for row in catalog_rows]
        for chunk in _chunks(external_ids):
            query = (
                "SELECT id, resource_type, external_id, title FROM resource_catalog "
                f"WHERE external_id IN ({_placeholders(len(chunk))})"
            )
            await cursor.execute(query, tuple(chunk))
            read_queries += 1
            for row in await cursor.fetchall():
                existing_resources[str(row[2])] = {"id": int(row[0]), "resource_type": str(row[1]), "title": str(row[3])}
                resource_ids[str(row[2])] = int(row[0])
        normalized_names = [str(row["normalized_name"]) for row in tag_rows]
        for chunk in _chunks(normalized_names):
            query = (
                "SELECT normalized_name, name FROM tag_dictionary "
                f"WHERE normalized_name IN ({_placeholders(len(chunk))})"
            )
            await cursor.execute(query, tuple(chunk))
            read_queries += 1
            for row in await cursor.fetchall():
                existing_tags[str(row[0])] = str(row[1])

        index_conflicts: list[dict[str, Any]] = []
        for chunk in _chunks(tuple(resource_ids.values())):
            query = (
                "SELECT resource_id, content_hash, graph_version FROM resource_index_state "
                f"WHERE resource_id IN ({_placeholders(len(chunk))})"
            )
            await cursor.execute(query, tuple(chunk))
            read_queries += 1
            for row in await cursor.fetchall():
                index_conflicts.append({"resource_id": int(row[0]), "content_hash": str(row[1]), "graph_version": row[2]})
    return {
        "resources": existing_resources,
        "tags": existing_tags,
        "resource_ids": resource_ids,
        "index_states": index_conflicts,
        "requested_graph_version": index_graph_version,
        "read_queries": read_queries,
    }


def _conflict_messages(
    *,
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
    conflicts: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    catalog_by_id = {str(row["external_id"]): row for row in rows_by_table["resource_catalog"]}
    for external_id, existing in conflicts["resources"].items():
        planned = catalog_by_id.get(external_id)
        if planned is None:
            continue
        if existing["resource_type"] != "BOOK" or existing["title"] != planned["title"]:
            blockers.append({"code": "EXISTING_RESOURCE_CONFLICT", "external_id": external_id})
    tag_by_name = {str(row["normalized_name"]): str(row["name"]) for row in rows_by_table["tag_dictionary"]}
    for normalized_name, existing_name in conflicts["tags"].items():
        if tag_by_name.get(normalized_name) != existing_name:
            blockers.append({"code": "EXISTING_TAG_CONFLICT", "normalized_name": normalized_name})
    plan_by_id = {str(row["external_id"]): row for row in rows_by_table["resource_index_state"]}
    id_to_external = {int(value): key for key, value in conflicts["resource_ids"].items()}
    for state in conflicts["index_states"]:
        external_id = id_to_external.get(int(state["resource_id"]))
        planned = plan_by_id.get(external_id or "")
        if planned and (state["content_hash"] != planned["content_hash"] or state["graph_version"] != planned["graph_version"]):
            blockers.append({"code": "EXISTING_INDEX_STATE_CONFLICT", "external_id": external_id})
    return blockers


async def append_rows(
    connection: Any,
    *,
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
    created_at: datetime,
) -> int:
    writes_attempted = 0

    async def insert_batches(cursor: Any, statement: str, values: Sequence[Sequence[Any]]) -> int:
        for batch in _chunks(values):
            await cursor.executemany(statement, batch)
        return len(values)

    async with connection.cursor() as cursor:
        catalog_values = [
            (
                row["resource_type"], row["external_id"], row["title"], canonical_json(row["authors"]),
                row["abstract"], canonical_json(row["keywords"]), row["category_code"], row["publication_year"],
                row["publication_date"], row["publisher_or_source"], row["language"], row["difficulty_level"],
                row["availability_status"], row["available_from"], row["access_url"], row["metadata_quality"],
                row["is_classic"], row["metadata_version"], created_at, created_at,
            )
            for row in rows_by_table["resource_catalog"]
        ]
        await insert_batches(
            cursor,
            "INSERT IGNORE INTO resource_catalog (resource_type, external_id, title, authors_json, abstract_text, keywords_json, category_code, publication_year, publication_date, publisher_or_source, language, difficulty_level, availability_status, available_from, access_url, metadata_quality, is_classic, metadata_version, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            catalog_values,
        )
        writes_attempted += len(catalog_values)

        external_ids = [str(row["external_id"]) for row in rows_by_table["resource_catalog"]]
        resource_ids: dict[str, int] = {}
        for chunk in _chunks(external_ids):
            await cursor.execute(
                "SELECT id, external_id FROM resource_catalog WHERE resource_type = 'BOOK' "
                f"AND external_id IN ({_placeholders(len(chunk))})",
                tuple(chunk),
            )
            resource_ids.update({str(row[1]): int(row[0]) for row in await cursor.fetchall()})
        if len(resource_ids) != len(external_ids):
            raise RuntimeError("not every catalog row resolved after append")

        tag_values = [
            (row["name"], row["normalized_name"], "ACTIVE", created_at, created_at)
            for row in rows_by_table["tag_dictionary"]
        ]
        await insert_batches(
            cursor,
            "INSERT IGNORE INTO tag_dictionary (name, normalized_name, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
            tag_values,
        )
        writes_attempted += len(tag_values)
        normalized_names = [str(row["normalized_name"]) for row in rows_by_table["tag_dictionary"]]
        tag_ids: dict[str, int] = {}
        for chunk in _chunks(normalized_names):
            await cursor.execute(
                "SELECT id, normalized_name FROM tag_dictionary "
                f"WHERE normalized_name IN ({_placeholders(len(chunk))})",
                tuple(chunk),
            )
            tag_ids.update({str(row[1]): int(row[0]) for row in await cursor.fetchall()})
        if len(tag_ids) != len(normalized_names):
            raise RuntimeError("not every tag row resolved after append")

        detail_values = [
            (resource_ids[str(row["external_id"])], row["isbn"], row["call_number"], row["location"], row["borrowable_copies"])
            for row in rows_by_table["resource_book_detail"]
        ]
        await insert_batches(
            cursor,
            "INSERT IGNORE INTO resource_book_detail (resource_id, isbn, call_number, location, borrowable_copies) VALUES (%s, %s, %s, %s, %s)",
            detail_values,
        )
        writes_attempted += len(detail_values)

        index_values = [
            (resource_ids[str(row["external_id"])], row["content_hash"], row["embedding_status"], row["graph_status"], row["graph_version"])
            for row in rows_by_table["resource_index_state"]
        ]
        await insert_batches(
            cursor,
            "INSERT IGNORE INTO resource_index_state (resource_id, content_hash, embedding_status, graph_status, graph_version) VALUES (%s, %s, %s, %s, %s)",
            index_values,
        )
        writes_attempted += len(index_values)

        resource_tag_values = [
            (resource_ids[str(row["external_id"])], tag_ids[str(row["normalized_name"])], row["weight"], row["confidence"], row["source"], created_at)
            for row in rows_by_table["resource_tag"]
        ]
        await insert_batches(
            cursor,
            "INSERT IGNORE INTO resource_tag (resource_id, tag_id, weight, confidence, source, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            resource_tag_values,
        )
        writes_attempted += len(resource_tag_values)
    return writes_attempted


async def apply_plan(
    *,
    values: Mapping[str, str],
    plan: Mapping[str, Any],
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
    allow_nonempty_target: bool,
) -> dict[str, Any]:
    connection = await _connection(values)
    try:
        before = await _target_snapshot(connection, database=values["RECPRO_MYSQL_DATABASE"])
        nonempty = {table: count for table, count in before["row_counts"].items() if count > 0}
        if nonempty and not allow_nonempty_target:
            raise ValueError("target MySQL catalog is non-empty; pass --allow-nonempty-target after review")
        conflicts = await _existing_conflicts(
            connection,
            catalog_rows=rows_by_table["resource_catalog"],
            tag_rows=rows_by_table["tag_dictionary"],
            index_graph_version=str(plan["graph_version"]),
        )
        blockers = _conflict_messages(rows_by_table=rows_by_table, conflicts=conflicts)
        if blockers:
            raise ValueError("existing MySQL rows conflict with the reviewed plan: " + json.dumps(blockers[:5], ensure_ascii=False))
        writes_attempted = await append_rows(
            connection,
            rows_by_table=rows_by_table,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        await connection.commit()
        after = await _target_snapshot(connection, database=values["RECPRO_MYSQL_DATABASE"])
        return {
            "before": before,
            "after": after,
            "writes_attempted": writes_attempted,
            "read_queries": int(before["read_queries"]) + int(conflicts["read_queries"]) + int(after["read_queries"]),
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
        }
    except Exception:
        await connection.rollback()
        raise
    finally:
        connection.close()


async def preflight_plan(
    *,
    values: Mapping[str, str],
    plan: Mapping[str, Any],
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Read target counts and conflicts without opening a write path."""

    connection = await _connection(values)
    try:
        snapshot = await _target_snapshot(connection, database=values["RECPRO_MYSQL_DATABASE"])
        conflicts = await _existing_conflicts(
            connection,
            catalog_rows=rows_by_table["resource_catalog"],
            tag_rows=rows_by_table["tag_dictionary"],
            index_graph_version=str(plan["graph_version"]),
        )
        blockers = _conflict_messages(rows_by_table=rows_by_table, conflicts=conflicts)
        return {
            "target": {
                "project": values.get("COMPOSE_PROJECT_NAME"),
                "database": values.get("RECPRO_MYSQL_DATABASE"),
            },
            "snapshot": snapshot,
            "existing_plan_resources": len(conflicts["resources"]),
            "existing_plan_tags": len(conflicts["tags"]),
            "existing_plan_index_states": len(conflicts["index_states"]),
            "blockers": blockers,
            "read_queries": int(snapshot["read_queries"]) + int(conflicts["read_queries"]),
        }
    finally:
        await connection.rollback()
        connection.close()


def write_evidence(run_id: str, payload: Mapping[str, Any]) -> Path:
    evidence_dir = PROJECT_ROOT / "artifacts/verification/mysql-book-import" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    path = evidence_dir / "import.json"
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


async def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    plan_dir = resolve_repository_path(args.plan_dir, label="MySQL plan directory")
    if not plan_dir.is_dir():
        raise ValueError("MySQL plan directory is missing")
    plan, rows_by_table = verify_plan(plan_dir)
    if args.apply and not args.confirm_mysql_write:
        raise ValueError("--apply requires --confirm-mysql-write")
    payload: dict[str, Any] = {
        "schema_version": "mysql-book-import-evidence-v1",
        "run_id": run_id,
        "plan_dir": plan_dir.relative_to(PROJECT_ROOT).as_posix(),
        "plan_schema_version": plan["schema_version"],
        "graph_version": plan["graph_version"],
        "license_status": plan["license_status"],
        "planned_counts": plan["table_counts"],
        "status": "DRY_RUN",
        "applied": False,
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
        },
    }
    if args.apply or args.preflight_db:
        values = read_env(resolve_repository_path(args.env_file, label="MySQL environment file"))
        issues = validate_compose(values)
        if issues:
            raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    if args.preflight_db and not args.apply:
        preflight = await preflight_plan(values=values, plan=plan, rows_by_table=rows_by_table)
        payload.update(
            {
                "status": "PREFLIGHT_PASS" if not preflight["blockers"] else "PREFLIGHT_BLOCKED",
                "target": preflight["target"],
                "before": preflight["snapshot"],
                "existing_plan_rows": {
                    "resource_catalog": preflight["existing_plan_resources"],
                    "tag_dictionary": preflight["existing_plan_tags"],
                    "resource_index_state": preflight["existing_plan_index_states"],
                },
                "blockers": preflight["blockers"],
                "safety": {
                    "database_reads": preflight["read_queries"],
                    "database_writes": 0,
                    "expected_delete_count": 0,
                    "actual_delete_count": 0,
                    "overwritten_inputs": 0,
                },
            }
        )
    if args.apply:
        # INSERT IGNORE is intentional for append-only/idempotent replays.  The
        # driver logs one warning for every already-present key; suppress only
        # that expected message while preserving all other importer failures.
        with _suppress_expected_duplicate_warnings():
            result = await apply_plan(
                values=values,
                plan=plan,
                rows_by_table=rows_by_table,
                allow_nonempty_target=args.allow_nonempty_target,
            )
        payload.update(
            {
                "status": "APPLIED",
                "applied": True,
                "target_project": values.get("COMPOSE_PROJECT_NAME"),
                "before": result["before"],
                "after": result["after"],
                "writes_attempted": result["writes_attempted"],
                "safety": {
                    "database_reads": result["read_queries"],
                    "database_writes": result["writes_attempted"],
                    "expected_delete_count": 0,
                    "actual_delete_count": 0,
                    "overwritten_inputs": 0,
                },
            }
        )
    evidence_path = write_evidence(run_id, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"[PASS] MySQL book catalog {'import' if args.apply else 'dry-run'} evidence: {evidence_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--apply", action="store_true", help="append reviewed rows to MySQL")
    parser.add_argument("--preflight-db", action="store_true", help="read target counts and conflicts without writing")
    parser.add_argument("--confirm-mysql-write", action="store_true", help="explicitly authorize the MySQL write")
    parser.add_argument("--allow-nonempty-target", action="store_true", help="allow append-only writes after reviewing existing row counts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error) as exc:
        print(f"[FAIL] MySQL book catalog import did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
