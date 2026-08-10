"""Build a deterministic, append-only Neo4j graph plan from ``Lib/*.csv``.

This command is an intake/normalization step.  It never connects to Neo4j and
never changes the source files.  Each run writes a new evidence directory with
normalized nodes and predicate triples.  The importer consumes these artifacts
only after the plan, source boundary, and license status have been reviewed.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence
import unicodedata
from urllib.parse import urlsplit, urlunsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = PROJECT_ROOT / "Lib"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
GRAPH_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
EXPECTED_FIELDS = (
    "题名",
    "外文题名",
    "作者",
    "出版社",
    "发行时间",
    "ISBN号",
    "页数",
    "原书定价",
    "开本",
    "主题词",
    "中图法分类号",
    "内容提要",
    "详情页Url",
)
ROLE_PATTERN = re.compile(r"(编著|主编|副主编|著|译|编|校注|审校|整理|口述|绘|摄影)$")
ISBN_PATTERN = re.compile(r"^(?:\d{9}[\dX]|\d{13})$")


def validate_identifier(value: str, *, label: str, pattern: re.Pattern[str]) -> str:
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{label} must use 3-64 safe characters")
    return value


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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\ufeff", "").replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_isbn(value: str) -> str | None:
    compact = re.sub(r"[-\s]", "", normalize_text(value)).upper()
    return compact if ISBN_PATTERN.fullmatch(compact) else None


def parse_publication_date(value: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"(\d{4})(?:[./-](\d{1,2}))?.*", normalize_text(value))
    if match is None:
        return None, None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    return year, month if month and 1 <= month <= 12 else None


def parse_integer(value: str) -> int | None:
    compact = normalize_text(value).replace(",", "")
    return int(compact) if re.fullmatch(r"\d+", compact) else None


def parse_price(value: str) -> float | None:
    compact = normalize_text(value).replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", compact):
        return None
    return float(compact)


def split_values(value: str, *, pattern: str) -> list[str]:
    return [part for part in (normalize_text(item) for item in re.split(pattern, value)) if part]


def parse_authors(value: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for raw_part in split_values(value, pattern=r"[；;、，,]"):
        name = re.sub(r"^（[^）]+）|^\([^)]*\)", "", raw_part).strip()
        role_match = ROLE_PATTERN.search(name)
        role = role_match.group(1) if role_match else ""
        if role:
            name = name[: -len(role)].strip()
        if name:
            result.append({"name": name, "role": role, "raw": raw_part})
    return result


def parse_keywords(value: str) -> list[str]:
    return sorted(
        {
            item
            for item in split_values(value, pattern=r"[-—;；,，、\s]+")
            if item and item not in {"隐藏更多", "更多"}
        }
    )


def normalize_subject_code(value: str) -> str:
    return normalize_text(value).split("(", 1)[0].split("（", 1)[0].strip()


def sanitize_source_url(value: str) -> tuple[str | None, str | None]:
    raw = normalize_text(value)
    if not raw:
        return None, None
    digest = sha256_bytes(raw.encode("utf-8"))
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw, digest
    # Drop query/fragment values because the scraped URL may contain access
    # tokens.  Keep a digest for provenance without storing those values.
    safe = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return safe, digest


def category_parts(path: Path) -> tuple[str, str]:
    name = path.parent.name
    match = re.fullmatch(r"([A-Z])-(.+)", name)
    return (match.group(1), match.group(2)) if match else (name, name)


def graph_key(graph_version: str, label: str, entity_id: str) -> str:
    digest = hashlib.sha256(entity_id.encode("utf-8")).hexdigest()[:32]
    return f"{graph_version}:{label.lower()}:{digest}"


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _add_node(
    nodes: dict[str, dict[str, Any]],
    *,
    graph_version: str,
    label: str,
    entity_id: str,
    properties: Mapping[str, Any],
) -> str:
    key = graph_key(graph_version, label, entity_id)
    document = nodes.get(key)
    cleaned_properties = {
        name: value
        for name, value in properties.items()
        if value is not None and value != ""
    }
    if document is None:
        nodes[key] = {
            "label": label,
            "graph_key": key,
            "entity_id": entity_id,
            "graph_version": graph_version,
            "properties": cleaned_properties,
        }
    else:
        for name, value in cleaned_properties.items():
            if name not in document["properties"] and value != []:
                document["properties"][name] = value
    return key


def _add_triple(
    triples: dict[str, dict[str, Any]],
    *,
    subject_key: str,
    predicate: str,
    object_key: str,
    properties: Mapping[str, Any] | None = None,
) -> None:
    edge_properties = dict(properties or {})
    edge_identity = canonical_json(
        {
            "subject": subject_key,
            "predicate": predicate,
            "object": object_key,
            "properties": edge_properties,
        }
    )
    edge_key = "edge:" + sha256_bytes(edge_identity.encode("utf-8"))[:32]
    triples[edge_key] = {
        "edge_key": edge_key,
        "subject_key": subject_key,
        "predicate": predicate,
        "object_key": object_key,
        "properties": edge_properties,
    }


def _parse_rows(input_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    files = sorted(input_root.rglob("*.csv"))
    if not files:
        raise ValueError("input root contains no CSV files")
    records: list[dict[str, Any]] = []
    file_summaries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    source_id = "lib-duixiu-scrape"
    for path in files:
        relative = _relative(path)
        raw_bytes = path.read_bytes()
        summary = {
            "path": relative,
            "sha256": sha256_bytes(raw_bytes),
            "bytes": len(raw_bytes),
            "record_count": 0,
        }
        file_summaries.append(summary)
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                header = tuple(reader.fieldnames or ())
                if header != EXPECTED_FIELDS:
                    errors.append(
                        {
                            "code": "CSV_HEADER_MISMATCH",
                            "file": relative,
                            "message": "CSV header does not match the frozen Lib schema",
                        }
                    )
                    continue
                for line_number, row in enumerate(reader, start=2):
                    if row is None or not any(normalize_text(value) for value in row.values()):
                        continue
                    if None in row:
                        errors.append(
                            {
                                "code": "CSV_FIELD_COUNT_MISMATCH",
                                "file": relative,
                                "line": line_number,
                                "message": "CSV row has extra fields",
                            }
                        )
                        continue
                    values = {key: normalize_text(row.get(key, "")) for key in EXPECTED_FIELDS}
                    raw_digest = sha256_bytes(canonical_json(values).encode("utf-8"))
                    isbn = normalize_isbn(values["ISBN号"])
                    if values["ISBN号"] and isbn is None:
                        errors.append(
                            {
                                "code": "ISBN_NORMALIZATION_WARNING",
                                "file": relative,
                                "line": line_number,
                                "message": "ISBN is retained as raw text and identity falls back to content hash",
                            }
                        )
                    category_code, category_name = category_parts(path)
                    year, month = parse_publication_date(values["发行时间"])
                    safe_url, url_digest = sanitize_source_url(values["详情页Url"])
                    authors = parse_authors(values["作者"])
                    keywords = parse_keywords(values["主题词"])
                    subject_code = normalize_subject_code(values["中图法分类号"])
                    core = {
                        "title": values["题名"],
                        "authors": [author["name"] for author in authors],
                        "publisher": values["出版社"],
                        "publication_year": year,
                        "pages": parse_integer(values["页数"]),
                    }
                    core_digest = sha256_bytes(canonical_json(core).encode("utf-8"))
                    record = {
                        "source_id": source_id,
                        "source_file": relative,
                        "source_line": line_number,
                        "source_file_sha256": summary["sha256"],
                        "raw_record_sha256": raw_digest,
                        # A source record is an occurrence in a concrete input
                        # file, not merely a content value.  Including the
                        # source line prevents repeated rows in different
                        # category files from being silently merged.
                        "source_record_id": "record:"
                        + sha256_bytes(
                            f"{relative}:{line_number}:{raw_digest}".encode("utf-8")
                        )[:32],
                        "values": values,
                        "isbn": isbn,
                        "isbn_raw": values["ISBN号"] or None,
                        "authors": authors,
                        "keywords": keywords,
                        "subject_code": subject_code or None,
                        "category_code": category_code,
                        "category_name": category_name,
                        "topic_name": path.stem,
                        "publication_year": year,
                        "publication_month": month,
                        "pages": parse_integer(values["页数"]),
                        "list_price": parse_price(values["原书定价"]),
                        "safe_url": safe_url,
                        "url_sha256": url_digest,
                        "core_digest": core_digest,
                    }
                    records.append(record)
                    summary["record_count"] += 1
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            errors.append(
                {
                    "code": "CSV_READ_ERROR",
                    "file": relative,
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )
    return records, file_summaries, errors


def _assign_book_identities(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    isbn_groups: dict[str, set[str]] = {}
    for record in records:
        isbn = record["isbn"]
        if isbn:
            isbn_groups.setdefault(isbn, set()).add(record["core_digest"])
    conflict_groups = {isbn for isbn, variants in isbn_groups.items() if len(variants) > 1}
    for record in records:
        if record["isbn"]:
            if record["isbn"] in conflict_groups:
                record["book_entity_id"] = (
                    f"book:isbn:{record['isbn']}:variant:{record['core_digest'][:20]}"
                )
                record["identity_strategy"] = "ISBN_VARIANT_CONTENT_FINGERPRINT"
            else:
                record["book_entity_id"] = f"book:isbn:{record['isbn']}"
                record["identity_strategy"] = "ISBN"
        else:
            record["book_entity_id"] = f"book:content:{record['core_digest'][:32]}"
            record["identity_strategy"] = "CONTENT_FINGERPRINT"
    return {
        "isbn_group_count": len(isbn_groups),
        "isbn_conflict_group_count": len(conflict_groups),
        "isbn_conflicting_record_count": sum(
            1 for record in records if record["isbn"] in conflict_groups
        ),
    }


def build_plan(
    *,
    input_root: Path,
    graph_version: str,
    source_license_status: str = "PENDING_USER_CONFIRMATION",
) -> dict[str, Any]:
    records, file_summaries, errors = _parse_rows(input_root)
    identity_summary = _assign_book_identities(records)
    nodes: dict[str, dict[str, Any]] = {}
    triples: dict[str, dict[str, Any]] = {}
    source_id = "lib-duixiu-scrape"
    file_digest_input = "\n".join(
        f"{item['path']}:{item['sha256']}" for item in file_summaries
    ).encode("utf-8")
    input_digest = sha256_bytes(file_digest_input)

    graph_node_key = _add_node(
        nodes,
        graph_version=graph_version,
        label="GraphVersion",
        entity_id=graph_version,
        properties={
            "graph_version": graph_version,
            "source_id": source_id,
            "status": "READY_FOR_IMPORT_REVIEW",
            "input_root": _relative(input_root),
            "input_sha256": input_digest,
            "file_count": len(file_summaries),
            "record_count": len(records),
        },
    )

    for file_summary in file_summaries:
        file_key = _add_node(
            nodes,
            graph_version=graph_version,
            label="SourceFile",
            entity_id=file_summary["path"],
            properties={**file_summary, "source_id": source_id},
        )
        _add_triple(
            triples,
            subject_key=file_key,
            predicate="FROM_BATCH",
            object_key=graph_node_key,
        )

    for record in records:
        values = record["values"]
        book_key = _add_node(
            nodes,
            graph_version=graph_version,
            label="Book",
            entity_id=record["book_entity_id"],
            properties={
                "title": values["题名"],
                "foreign_title": values["外文题名"] or None,
                "isbn": record["isbn"],
                "isbn_raw": record["isbn_raw"],
                "publisher": values["出版社"] or None,
                "publication_date_raw": values["发行时间"] or None,
                "publication_year": record["publication_year"],
                "publication_month": record["publication_month"],
                "pages": record["pages"],
                "list_price": record["list_price"],
                "physical_format": values["开本"] or None,
                "subject_raw": values["中图法分类号"] or None,
                "summary": values["内容提要"].split("隐藏更多", 1)[0].strip() or None,
                "source_url": record["safe_url"],
                "source_url_sha256": record["url_sha256"],
                "identity_strategy": record["identity_strategy"],
                "source_id": source_id,
            },
        )
        record_key = _add_node(
            nodes,
            graph_version=graph_version,
            label="SourceRecord",
            entity_id=record["source_record_id"],
            properties={
                "source_record_id": record["source_record_id"],
                "source_id": source_id,
                "source_file": record["source_file"],
                "source_line": record["source_line"],
                "raw_record_sha256": record["raw_record_sha256"],
            },
        )
        file_key = graph_key(graph_version, "SourceFile", record["source_file"])
        _add_triple(triples, subject_key=record_key, predicate="FROM_BATCH", object_key=graph_node_key)
        _add_triple(triples, subject_key=record_key, predicate="READ_FROM", object_key=file_key)
        _add_triple(triples, subject_key=record_key, predicate="DESCRIBES", object_key=book_key)
        _add_triple(triples, subject_key=book_key, predicate="IN_GRAPH_VERSION", object_key=graph_node_key)

        category_key = _add_node(
            nodes,
            graph_version=graph_version,
            label="Category",
            entity_id=f"category:{record['category_code']}",
            properties={"code": record["category_code"], "name": record["category_name"]},
        )
        topic_entity = f"topic:{record['category_code']}:{normalize_text(record['topic_name'])}"
        topic_key = _add_node(
            nodes,
            graph_version=graph_version,
            label="Topic",
            entity_id=topic_entity,
            properties={
                "name": normalize_text(record["topic_name"]),
                "category_code": record["category_code"],
                "category_name": record["category_name"],
            },
        )
        _add_triple(triples, subject_key=book_key, predicate="CLASSIFIED_AS", object_key=category_key)
        _add_triple(triples, subject_key=book_key, predicate="IN_TOPIC", object_key=topic_key)
        _add_triple(triples, subject_key=category_key, predicate="HAS_TOPIC", object_key=topic_key)

        for author in record["authors"]:
            author_entity = "author:" + sha256_bytes(author["name"].encode("utf-8"))[:32]
            author_key = _add_node(
                nodes,
                graph_version=graph_version,
                label="Author",
                entity_id=author_entity,
                properties={"name": author["name"]},
            )
            _add_triple(
                triples,
                subject_key=book_key,
                predicate="AUTHORED_BY",
                object_key=author_key,
                properties={"role": author["role"]} if author["role"] else {},
            )

        publisher = normalize_text(values["出版社"])
        if publisher:
            publisher_entity = "publisher:" + sha256_bytes(publisher.encode("utf-8"))[:32]
            publisher_key = _add_node(
                nodes,
                graph_version=graph_version,
                label="Publisher",
                entity_id=publisher_entity,
                properties={"name": publisher},
            )
            _add_triple(triples, subject_key=book_key, predicate="PUBLISHED_BY", object_key=publisher_key)

        if record["subject_code"]:
            subject_entity = "clc:" + record["subject_code"]
            subject_key = _add_node(
                nodes,
                graph_version=graph_version,
                label="SubjectCode",
                entity_id=subject_entity,
                properties={"code": record["subject_code"]},
            )
            _add_triple(triples, subject_key=book_key, predicate="HAS_SUBJECT_CODE", object_key=subject_key)

        for keyword in record["keywords"]:
            keyword_entity = "keyword:" + sha256_bytes(keyword.encode("utf-8"))[:32]
            keyword_key = _add_node(
                nodes,
                graph_version=graph_version,
                label="Keyword",
                entity_id=keyword_entity,
                properties={"name": keyword},
            )
            _add_triple(triples, subject_key=book_key, predicate="HAS_KEYWORD", object_key=keyword_key)

    label_counts: dict[str, int] = {}
    for node in nodes.values():
        label_counts[node["label"]] = label_counts.get(node["label"], 0) + 1
    predicate_counts: dict[str, int] = {}
    for triple in triples.values():
        predicate_counts[triple["predicate"]] = predicate_counts.get(triple["predicate"], 0) + 1
    blockers = []
    if errors and any(item["code"] in {"CSV_HEADER_MISMATCH", "CSV_FIELD_COUNT_MISMATCH", "CSV_READ_ERROR"} for item in errors):
        blockers.append({"code": "INPUT_PARSE_FAILED", "message": "one or more CSV files cannot be safely normalized"})
    if not records:
        blockers.append({"code": "NO_BOOK_RECORDS", "message": "no valid book records were found"})
    status = "PASS_WITH_WARNINGS" if errors and not blockers else ("READY_FOR_IMPORT_REVIEW" if not blockers else "PASS_WITH_BLOCKERS")
    return {
        "schema_version": "book-graph-plan-v1",
        "status": status,
        "can_import": not blockers,
        "license_status": source_license_status,
        "graph_version": graph_version,
        "source_id": source_id,
        "input_root": _relative(input_root),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git("status", "--porcelain")),
        "generated_at": datetime.now(UTC).isoformat(),
        "input": {
            "file_count": len(file_summaries),
            "record_count": len(records),
            "total_bytes": sum(item["bytes"] for item in file_summaries),
            "sha256": input_digest,
            "files": file_summaries,
        },
        "quality": {
            "errors": errors,
            "error_count": len(errors),
            **identity_summary,
        },
        "nodes": {"total": len(nodes), "by_label": dict(sorted(label_counts.items()))},
        "triples": {"total": len(triples), "by_predicate": dict(sorted(predicate_counts.items()))},
        "blockers": blockers,
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
        },
        "_nodes": sorted(nodes.values(), key=lambda item: item["graph_key"]),
        "_triples": sorted(triples.values(), key=lambda item: item["edge_key"]),
    }


def execute(*, run_id: str, graph_version: str, input_root: Path, license_status: str) -> dict[str, Any]:
    validate_identifier(run_id, label="run id", pattern=RUN_ID_PATTERN)
    validate_identifier(graph_version, label="graph version", pattern=GRAPH_VERSION_PATTERN)
    resolved_root = resolve_repository_path(input_root, label="book input root")
    if not resolved_root.is_dir():
        raise ValueError("book input root is missing")
    evidence_dir = PROJECT_ROOT / "artifacts/verification/book-graph" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    plan = build_plan(
        input_root=resolved_root,
        graph_version=graph_version,
        source_license_status=license_status,
    )
    nodes = plan.pop("_nodes")
    triples = plan.pop("_triples")
    nodes_path = evidence_dir / "nodes.jsonl"
    triples_path = evidence_dir / "triples.jsonl"
    with nodes_path.open("x", encoding="utf-8") as handle:
        for node in nodes:
            handle.write(canonical_json(node) + "\n")
    with triples_path.open("x", encoding="utf-8") as handle:
        for triple in triples:
            handle.write(canonical_json(triple) + "\n")
    plan["artifacts"] = {
        "nodes_path": _relative(nodes_path),
        "triples_path": _relative(triples_path),
        "nodes_sha256": sha256_bytes(nodes_path.read_bytes()),
        "triples_sha256": sha256_bytes(triples_path.read_bytes()),
    }
    plan_path = evidence_dir / "graph-plan.json"
    with plan_path.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--graph-version", required=True)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument(
        "--license-status",
        default="PENDING_USER_CONFIRMATION",
        choices=("PENDING_USER_CONFIRMATION", "CONFIRMED_LOCAL_RESEARCH", "LICENSED_OPEN_DATA"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        execute(
            run_id=args.run_id,
            graph_version=args.graph_version,
            input_root=args.input_root,
            license_status=args.license_status,
        )
    except (OSError, ValueError, subprocess.SubprocessError, csv.Error) as exc:
        print(f"[FAIL] book graph plan did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
