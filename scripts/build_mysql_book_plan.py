"""Build an append-only MySQL catalog plan from an imported book graph plan.

This command is deliberately database-free.  It maps the Neo4j graph boundary
to the existing G2 ``resource_catalog`` schema and emits table-shaped JSONL
rows.  The separate importer requires an explicit MySQL write confirmation.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from scripts.import_book_graph import (
    PROJECT_ROOT,
    canonical_json,
    relative_path,
    resolve_repository_path,
    sha256_bytes,
    verify_plan,
)


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RESOURCE_TYPES = {"BOOK"}
TABLE_NAMES = (
    "resource_catalog",
    "resource_book_detail",
    "tag_dictionary",
    "resource_tag",
    "resource_index_state",
)


def validate_identifier(value: str, *, label: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} has an unsafe format")
    return value


def parse_available_from(value: str) -> tuple[str, str]:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("available-from must include a timezone")
    utc = parsed.astimezone(UTC).replace(tzinfo=None)
    return utc.strftime("%Y-%m-%d"), utc.strftime("%Y-%m-%d %H:%M:%S")


def normalize_date(year: object, month: object) -> str | None:
    if not isinstance(year, int) or not 1000 <= year <= 2200:
        return None
    normalized_month = month if isinstance(month, int) and 1 <= month <= 12 else 1
    return f"{year:04d}-{normalized_month:02d}-01"


def tag_key(kind: str, name: str) -> str:
    digest = hashlib.sha256(f"{kind}:{name}".encode("utf-8")).hexdigest()[:32]
    return f"{kind}-{digest}"


def metadata_quality(properties: Mapping[str, Any], *, authors: Sequence[str], keywords: Sequence[str]) -> float:
    checks = (
        bool(properties.get("title")),
        bool(authors),
        bool(properties.get("summary")),
        bool(properties.get("publisher")),
        properties.get("publication_year") is not None,
        properties.get("pages") is not None,
        bool(properties.get("isbn")),
        bool(properties.get("subject_raw")),
        bool(keywords),
        bool(properties.get("source_url")),
    )
    return round(sum(checks) / len(checks), 6)


def _node(node_map: Mapping[str, Mapping[str, Any]], key: str, label: str) -> Mapping[str, Any]:
    node = node_map.get(key)
    if node is None or node.get("label") != label:
        raise ValueError(f"graph triple references a missing {label} node")
    return node


def build_rows(
    *,
    plan: Mapping[str, Any],
    nodes: Sequence[Mapping[str, Any]],
    triples: Sequence[Mapping[str, Any]],
    available_from: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    node_map = {str(node["graph_key"]): node for node in nodes}
    by_subject: dict[str, list[Mapping[str, Any]]] = {}
    for triple in triples:
        by_subject.setdefault(str(triple["subject_key"]), []).append(triple)
    catalog_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    tag_dictionary: dict[str, dict[str, Any]] = {}
    resource_tags: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    graph_version = str(plan["graph_version"])
    for book in sorted((node for node in nodes if node.get("label") == "Book"), key=lambda item: str(item["entity_id"])):
        properties = book.get("properties")
        if not isinstance(properties, Mapping):
            blockers.append({"code": "BOOK_PROPERTIES_INVALID", "graph_key": book.get("graph_key")})
            continue
        external_id = str(book["entity_id"])
        title = str(properties.get("title", "")).strip()
        if not title:
            blockers.append({"code": "BOOK_TITLE_MISSING", "external_id": external_id})
            continue
        if len(external_id) > 128 or len(title) > 500:
            blockers.append({"code": "MYSQL_FIELD_LIMIT_EXCEEDED", "external_id": external_id})
            continue
        authors: list[str] = []
        keywords: list[str] = []
        topics: list[str] = []
        subject_codes: list[str] = []
        category_code: str | None = None
        publisher: str | None = None
        for triple in by_subject.get(str(book["graph_key"]), ()):
            predicate = str(triple["predicate"])
            object_node = node_map.get(str(triple["object_key"]))
            if object_node is None:
                blockers.append({"code": "GRAPH_OBJECT_MISSING", "external_id": external_id})
                continue
            object_properties = object_node.get("properties", {})
            if predicate == "AUTHORED_BY":
                authors.append(str(object_properties.get("name", "")).strip())
            elif predicate == "HAS_KEYWORD":
                keywords.append(str(object_properties.get("name", "")).strip())
            elif predicate == "IN_TOPIC":
                topics.append(str(object_properties.get("name", "")).strip())
            elif predicate == "HAS_SUBJECT_CODE":
                subject_codes.append(str(object_properties.get("code", "")).strip())
            elif predicate == "PUBLISHED_BY":
                publisher = str(object_properties.get("name", "")).strip() or None
            elif predicate == "CLASSIFIED_AS":
                category_code = str(object_properties.get("code", "")).strip() or None
        authors = sorted({item for item in authors if item})
        keywords = sorted({item for item in keywords if item})
        topics = sorted({item for item in topics if item})
        subject_codes = sorted({item for item in subject_codes if item})
        publication_date = normalize_date(properties.get("publication_year"), properties.get("publication_month"))
        quality = metadata_quality(properties, authors=authors, keywords=keywords)
        base = {
            "resource_type": "BOOK",
            "external_id": external_id,
            "title": title,
            "authors": authors,
            "abstract": properties.get("summary"),
            "keywords": keywords,
            "category_code": category_code,
            "publication_year": properties.get("publication_year"),
            "publication_date": publication_date,
            "publisher_or_source": publisher,
            "language": None,
            "difficulty_level": None,
            "availability_status": "REFERENCE_ONLY",
            "available_from": available_from,
            "access_url": properties.get("source_url"),
            "metadata_quality": quality,
            "is_classic": False,
            "metadata_version": 1,
        }
        catalog_rows.append(base)
        detail_rows.append(
            {
                "external_id": external_id,
                "isbn": properties.get("isbn"),
                "call_number": subject_codes[0] if subject_codes else None,
                "location": None,
                "borrowable_copies": 0,
            }
        )
        content_hash = sha256_bytes(canonical_json(base).encode("utf-8"))
        index_rows.append(
            {
                "external_id": external_id,
                "content_hash": content_hash,
                "embedding_status": "PENDING",
                "graph_status": "READY",
                "graph_version": graph_version,
            }
        )
        tag_specs = (
            [("kw", name, 1.0, 0.85) for name in keywords]
            + [("topic", name, 0.9, 0.9) for name in topics]
            + [("clc", name, 0.8, 0.95) for name in subject_codes]
        )
        for kind, name, weight, confidence in tag_specs:
            normalized_name = tag_key(kind, name)
            tag_dictionary.setdefault(
                normalized_name,
                {"name": name, "normalized_name": normalized_name, "kind": kind},
            )
            resource_tags.append(
                {
                    "external_id": external_id,
                    "normalized_name": normalized_name,
                    "weight": weight,
                    "confidence": confidence,
                    "source": "IMPORT",
                }
            )
    rows = {
        "resource_catalog": catalog_rows,
        "resource_book_detail": detail_rows,
        "tag_dictionary": sorted(tag_dictionary.values(), key=lambda item: item["normalized_name"]),
        "resource_tag": sorted(resource_tags, key=lambda item: (item["external_id"], item["normalized_name"])),
        "resource_index_state": index_rows,
    }
    return rows, blockers, [
        {"code": "SOURCE_GRAPH_WARNING", "message": "source graph plan contains quality warnings"}
    ] if plan.get("status") == "PASS_WITH_WARNINGS" else []


def build_plan(*, graph_plan_dir: Path, available_from: str) -> dict[str, Any]:
    plan, nodes, triples = verify_plan(graph_plan_dir)
    available_date, available_datetime = parse_available_from(available_from)
    rows, blockers, warnings = build_rows(
        plan=plan,
        nodes=nodes,
        triples=triples,
        available_from=available_datetime,
    )
    table_counts = {table: len(rows[table]) for table in TABLE_NAMES}
    status = "PASS_WITH_BLOCKERS" if blockers else ("PASS_WITH_WARNINGS" if warnings else "READY_FOR_MYSQL_REVIEW")
    return {
        "schema_version": "mysql-book-plan-v1",
        "status": status,
        "can_import": not blockers,
        "license_status": plan["license_status"],
        "graph_version": plan["graph_version"],
        "source_graph_plan": relative_path(graph_plan_dir / "graph-plan.json"),
        "source_graph_plan_sha256": sha256_bytes((graph_plan_dir / "graph-plan.json").read_bytes()),
        "available_from_date": available_date,
        "available_from": available_datetime,
        "table_counts": table_counts,
        "book_count": len(rows["resource_catalog"]),
        "tag_count": len(rows["tag_dictionary"]),
        "resource_tag_count": len(rows["resource_tag"]),
        "quality": {"warnings": warnings, "blockers": blockers},
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "_rows": rows,
    }


def execute(*, run_id: str, graph_plan_dir: Path, available_from: str) -> dict[str, Any]:
    validate_identifier(run_id, label="MySQL plan run id")
    resolved_plan_dir = resolve_repository_path(graph_plan_dir, label="graph plan directory")
    if not resolved_plan_dir.is_dir():
        raise ValueError("graph plan directory is missing")
    plan = build_plan(graph_plan_dir=resolved_plan_dir, available_from=available_from)
    rows = plan.pop("_rows")
    evidence_dir = PROJECT_ROOT / "artifacts/verification/mysql-book-plan" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    artifact_metadata: dict[str, Any] = {}
    for table in TABLE_NAMES:
        path = evidence_dir / f"{table}.jsonl"
        with path.open("x", encoding="utf-8") as handle:
            for row in rows[table]:
                handle.write(canonical_json(row) + "\n")
        artifact_metadata[table] = {
            "path": relative_path(path),
            "sha256": sha256_bytes(path.read_bytes()),
            "count": len(rows[table]),
        }
    plan["artifacts"] = artifact_metadata
    plan_path = evidence_dir / "mysql-book-plan.json"
    with plan_path.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--graph-plan-dir", type=Path, required=True)
    parser.add_argument("--available-from", default="2026-08-10T00:00:00Z")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        execute(
            run_id=args.run_id,
            graph_plan_dir=args.graph_plan_dir,
            available_from=args.available_from,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[FAIL] MySQL book plan did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
