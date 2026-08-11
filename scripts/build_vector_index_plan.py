"""Build a deterministic, database-free vector index ChangePlan.

The input is a reviewed MySQL book ChangePlan, not a live database.  This
keeps the embedding build reproducible and lets the later Chroma adapter
consume a versioned artifact without allowing this command to mutate MySQL,
Neo4j, Chroma, or any existing evidence run.
"""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from typing import Any, Mapping, Sequence
import unicodedata

PROJECT_ROOT = Path(__file__).resolve().parents[1]


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
DIMENSION = 384
NGRAM_MIN = 2
NGRAM_MAX = 4
EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"
NAMESPACE_NAME = "library_resources__hash_char_ngram_v1"


def _safe(value: str, *, label: str, pattern: re.Pattern[str]) -> str:
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{label} has an unsafe format")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize_field(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.split())


def document_text(row: Mapping[str, Any]) -> str:
    """Use the documented title/keywords/abstract format exactly."""

    title = _normalize_field(row.get("title"))
    keywords = row.get("keywords")
    keyword_text = " ".join(
        _normalize_field(item)
        for item in (keywords if isinstance(keywords, list) else [])
        if _normalize_field(item)
    )
    abstract = _normalize_field(row.get("abstract"))
    return "\n".join((title, keyword_text, abstract))


def _ngrams(text: str) -> Sequence[tuple[int, str]]:
    return tuple(
        (size, text[index : index + size])
        for size in range(NGRAM_MIN, NGRAM_MAX + 1)
        for index in range(0, max(0, len(text) - size + 1))
    )


def embedding_vector(text: str) -> tuple[float, ...]:
    values = [0.0] * DIMENSION
    for size, ngram in _ngrams(text):
        digest = hashlib.sha256(f"{size}:{ngram}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % DIMENSION
        values[bucket] += 1.0
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        raise ValueError("document produced an empty embedding")
    normalized = tuple(value / norm for value in values)
    packed = struct.pack("<" + "f" * DIMENSION, *normalized)
    unpacked = struct.unpack("<" + "f" * DIMENSION, packed)
    if not all(math.isfinite(value) for value in unpacked):
        raise ValueError("embedding contains a non-finite value")
    return unpacked


def encode_vector(vector: Sequence[float]) -> tuple[str, str]:
    if len(vector) != DIMENSION:
        raise ValueError("embedding dimension mismatch")
    packed = struct.pack("<" + "f" * DIMENSION, *vector)
    return base64.b64encode(packed).decode("ascii"), _sha256_bytes(packed)


def vector_id(*, external_id: str, content_hash: str, metadata_version: int, embedding_version: str) -> str:
    key = f"{external_id}:{content_hash}:{metadata_version}:{embedding_version}".encode("utf-8")
    return "vec-" + _sha256_bytes(key)


def _available_epoch(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError("available_from must be a MySQL datetime string")
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _artifact_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("artifact path must stay inside the repository") from exc
    return resolved


def build_vector_records(
    *,
    plan: Mapping[str, Any],
    rows_by_table: Mapping[str, list[dict[str, Any]]],
    embedding_version: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    catalog_rows = rows_by_table["resource_catalog"]
    index_rows = {str(row["external_id"]): row for row in rows_by_table["resource_index_state"]}
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    missing_abstract_count = 0
    missing_keywords_count = 0
    empty_document_count = 0
    invalid_content_hash_count = 0
    seen_external_ids: set[str] = set()
    seen_vector_ids: set[str] = set()
    duplicate_external_id_count = 0
    duplicate_vector_id_count = 0

    for row in catalog_rows:
        external_id = str(row["external_id"])
        if external_id in seen_external_ids:
            duplicate_external_id_count += 1
            blockers.append({"code": "DUPLICATE_EXTERNAL_ID", "external_id": external_id})
            continue
        seen_external_ids.add(external_id)
        index_row = index_rows.get(external_id)
        if index_row is None:
            blockers.append({"code": "INDEX_STATE_MISSING", "external_id": external_id})
            continue
        content_hash = str(index_row["content_hash"])
        if SHA256_PATTERN.fullmatch(content_hash) is None:
            invalid_content_hash_count += 1
            blockers.append({"code": "INVALID_CONTENT_HASH", "external_id": external_id})
            continue
        abstract = row.get("abstract")
        keywords = row.get("keywords")
        if not _normalize_field(abstract):
            missing_abstract_count += 1
        if not isinstance(keywords, list) or not any(_normalize_field(item) for item in keywords):
            missing_keywords_count += 1
        text = document_text(row)
        if not text.strip():
            empty_document_count += 1
            blockers.append({"code": "EMPTY_DOCUMENT", "external_id": external_id})
            continue
        try:
            vector = embedding_vector(text)
            available_epoch = _available_epoch(row["available_from"])
        except (TypeError, ValueError) as exc:
            blockers.append({"code": "VECTOR_BUILD_FAILED", "external_id": external_id, "detail": str(exc)})
            continue
        encoded, vector_sha256 = encode_vector(vector)
        metadata_version = int(row["metadata_version"])
        current_vector_id = vector_id(
            external_id=external_id,
            content_hash=content_hash,
            metadata_version=metadata_version,
            embedding_version=embedding_version,
        )
        if current_vector_id in seen_vector_ids:
            duplicate_vector_id_count += 1
            blockers.append({"code": "DUPLICATE_VECTOR_ID", "vector_id": current_vector_id})
            continue
        seen_vector_ids.add(current_vector_id)
        records.append(
            {
                "vector_id": current_vector_id,
                "external_id": external_id,
                "resource_type": str(row["resource_type"]),
                "content_hash": content_hash,
                "metadata_version": metadata_version,
                "embedding_version": embedding_version,
                "dimension": DIMENSION,
                "document": text,
                "document_sha256": _sha256_bytes(text.encode("utf-8")),
                "vector_encoding": "float32-little-endian-base64",
                "vector_base64": encoded,
                "vector_sha256": vector_sha256,
                "metadata": {
                    "resource_type": str(row["resource_type"]),
                    "category_code": str(row["category_code"] or ""),
                    "publication_year": int(row["publication_year"] or 0),
                    "difficulty_level": int(row["difficulty_level"] or 0),
                    "available_from_epoch": available_epoch,
                    "embedding_version": embedding_version,
                    "metadata_version": metadata_version,
                    "graph_version": str(plan["graph_version"]),
                },
            }
        )

    if missing_abstract_count:
        warnings.append({"code": "MISSING_ABSTRACT", "count": missing_abstract_count})
    if missing_keywords_count:
        warnings.append({"code": "MISSING_KEYWORDS", "count": missing_keywords_count})
    return records, {
        "warnings": warnings,
        "blockers": blockers,
        "missing_abstract_count": missing_abstract_count,
        "missing_keywords_count": missing_keywords_count,
        "empty_document_count": empty_document_count,
        "duplicate_external_id_count": duplicate_external_id_count,
        "duplicate_vector_id_count": duplicate_vector_id_count,
        "invalid_content_hash_count": invalid_content_hash_count,
    }


def build_plan(*, mysql_plan_dir: Path, output_dir: Path, embedding_version: str, index_version: str, namespace_name: str) -> Path:
    # Keep the deterministic/vector operator environment independent from the
    # optional MySQL driver.  The MySQL plan verifier is loaded only when this
    # build command is explicitly asked to consume a MySQL ChangePlan.
    from scripts.import_mysql_book_catalog import verify_plan as verify_mysql_plan

    mysql_plan, rows_by_table = verify_mysql_plan(mysql_plan_dir)
    _safe(embedding_version, label="embedding_version", pattern=VERSION_PATTERN)
    _safe(index_version, label="index_version", pattern=VERSION_PATTERN)
    if not re.fullmatch(r"^[a-z][a-z0-9_]{2,254}$", namespace_name):
        raise ValueError("namespace_name has an unsafe format")
    records, quality = build_vector_records(
        plan=mysql_plan,
        rows_by_table=rows_by_table,
        embedding_version=embedding_version,
    )
    resource_count = len(rows_by_table["resource_catalog"])
    status = "PASS_WITH_BLOCKERS" if quality["blockers"] else ("PASS_WITH_WARNINGS" if quality["warnings"] else "READY_FOR_VECTOR_BUILD")
    output_dir = _artifact_path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"vector evidence directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    vector_path = output_dir / "vectors.jsonl"
    with vector_path.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    vector_bytes = vector_path.read_bytes()
    plan_payload: dict[str, Any] = {
        "schema_version": "vector-index-plan-v1",
        "status": status,
        "can_build": not quality["blockers"],
        "graph_version": str(mysql_plan["graph_version"]),
        "index_version": index_version,
        "embedding_version": embedding_version,
        "namespace_name": namespace_name,
        "source_mysql_plan": str((mysql_plan_dir / "mysql-book-plan.json").relative_to(PROJECT_ROOT).as_posix()),
        "source_mysql_plan_sha256": _sha256_bytes((mysql_plan_dir / "mysql-book-plan.json").read_bytes()),
        "embedding": {
            "provider": "HashingEmbeddingProvider",
            "analyzer": "char",
            "ngram_min": NGRAM_MIN,
            "ngram_max": NGRAM_MAX,
            "dimension": DIMENSION,
            "alternate_sign": False,
            "normalization": "L2",
            "dtype": "float32",
            "encoding": "float32-little-endian-base64",
            "document_format": "title\nkeywords\nabstract",
        },
        "resource_count": resource_count,
        "vector_count": len(records),
        "skipped_count": resource_count - len(records),
        "quality": quality,
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "external_store_writes": 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
            "files_deleted": 0,
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "artifacts": {
            "vectors": {
                "path": vector_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": _sha256_bytes(vector_bytes),
                "count": len(records),
                "bytes": len(vector_bytes),
            }
        },
    }
    plan_path = output_dir / "vector-index-plan.json"
    plan_path.write_text(json.dumps(plan_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mysql-plan-dir", type=Path, required=True)
    parser.add_argument("--embedding-version", default=EMBEDDING_VERSION)
    parser.add_argument("--index-version", default=INDEX_VERSION)
    parser.add_argument("--namespace-name", default=NAMESPACE_NAME)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_id = _safe(args.run_id, label="run_id", pattern=RUN_ID_PATTERN)
        mysql_plan_dir = args.mysql_plan_dir if args.mysql_plan_dir.is_absolute() else PROJECT_ROOT / args.mysql_plan_dir
        mysql_plan_dir = mysql_plan_dir.resolve()
        mysql_plan_dir.relative_to(PROJECT_ROOT)
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "vector-index-plan" / run_id
        plan_path = build_plan(
            mysql_plan_dir=mysql_plan_dir,
            output_dir=output_dir,
            embedding_version=args.embedding_version,
            index_version=args.index_version,
            namespace_name=args.namespace_name,
        )
        print(f"[PASS] vector index plan and offline embeddings: {plan_path}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] vector index plan did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
