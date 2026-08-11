"""Independently verify one local Chroma collection without writes.

The command opens only the requested persistent path and performs list/get/count
and query operations.  It never creates a collection, adds vectors, changes
metadata, resets a client, or invokes any collection lifecycle mutation.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Sequence

from scripts.build_chroma_collection_plan import PROJECT_ROOT
from scripts.import_chroma_vectors import (
    DIMENSION,
    _all_existing,
    _build_expected_identity,
    _collection_name,
    _expected_collection_metadata,
    _inside,
    _iter_records,
    _load_chromadb,
    _load_json,
    _smoke_recall,
    _verify_batches,
)
from scripts.verify_chroma_collection_plan import verify_collection_plan


RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$"
DEFAULT_BATCH_SIZE = 256
MAX_BATCH_SIZE = 1000


def _write_report(output_dir: Path, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    path = output_dir / "readonly.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def verify_collection(
    *,
    collection_plan_path: Path,
    chroma_path: Path,
    output_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Path:
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise ValueError("batch_size must be between 1 and 1000")
    collection_plan_path = _inside(collection_plan_path, label="Chroma collection plan")
    plan_report = verify_collection_plan(collection_plan_path)
    plan = _load_json(collection_plan_path, label="Chroma collection plan")
    source_plan = _load_json(
        _inside(plan["source_vector_plan"], label="source vector plan"),
        label="source vector plan",
    )
    graph_version = str(source_plan["graph_version"])
    expected_metadata = _build_expected_identity(plan, graph_version=graph_version)
    expected_count = int(plan["record_count"])
    if len(expected_metadata) != expected_count:
        raise ValueError("source vector identity count does not match the collection plan")
    first_record = next(_iter_records(plan), None)
    if first_record is None:
        raise ValueError("empty vector artifacts are not supported")
    chroma_path = _inside(chroma_path, label="Chroma persistent path")
    output_dir = _inside(output_dir, label="Chroma verification output")
    if output_dir.exists():
        raise FileExistsError(f"Chroma verification evidence directory already exists: {output_dir}")

    chromadb, settings_factory = _load_chromadb()
    settings = settings_factory(anonymized_telemetry=False, allow_reset=False)
    client = chromadb.PersistentClient(path=str(chroma_path), settings=settings)
    collection_name = str(plan["collection_name"])
    names = {_collection_name(item) for item in client.list_collections()}
    if collection_name not in names:
        raise RuntimeError("planned Chroma collection is missing")
    collection = client.get_collection(collection_name, embedding_function=None)
    expected_collection_metadata = _expected_collection_metadata(
        plan, graph_version=graph_version
    )
    actual_metadata = collection.metadata
    if not isinstance(actual_metadata, dict):
        raise RuntimeError("Chroma collection metadata is missing")
    metadata_mismatches = {
        key: {"expected": value, "actual": actual_metadata.get(key)}
        for key, value in expected_collection_metadata.items()
        if actual_metadata.get(key) != value
    }
    if metadata_mismatches:
        raise RuntimeError(f"Chroma collection metadata mismatch: {sorted(metadata_mismatches)}")

    existing = _all_existing(collection)
    unexpected_ids = sorted(set(existing) - set(expected_metadata))
    missing_ids = sorted(set(expected_metadata) - set(existing))
    if unexpected_ids or missing_ids:
        raise RuntimeError(
            f"Chroma ID set mismatch: unexpected={len(unexpected_ids)}, missing={len(missing_ids)}"
        )
    for identifier, metadata in existing.items():
        if dict(metadata) != expected_metadata[identifier]:
            raise RuntimeError(f"Chroma metadata mismatch for ID: {identifier}")

    count = int(collection.count())
    if count != expected_count:
        raise RuntimeError(f"Chroma count mismatch: expected {expected_count}, got {count}")
    verified_count, _, max_absolute_error, max_l2_error = _verify_batches(
        collection,
        collection_plan=plan,
        graph_version=graph_version,
        batch_size=batch_size,
    )
    if verified_count != expected_count:
        raise RuntimeError(
            f"Chroma vector/document verification mismatch: expected {expected_count}, got {verified_count}"
        )
    query_smoke = _smoke_recall(
        collection,
        first_record=first_record,
        collection_plan=plan,
    )
    report = {
        "schema_version": "chroma-import-readonly-verification-v1",
        "status": "PASS",
        "collection_name": collection_name,
        "chroma_path": chroma_path.relative_to(PROJECT_ROOT).as_posix(),
        "client": {"package": "chromadb", "version": getattr(chromadb, "__version__", "unknown")},
        "plan": plan_report,
        "expected_count": expected_count,
        "actual_count": count,
        "id_set": {"expected": expected_count, "actual": len(existing), "unexpected": 0, "missing": 0},
        "metadata_fields_verified": sorted(expected_collection_metadata),
        "vectors_documents_metadata_verified": verified_count,
        "vector_numeric_validation": {
            "source_vector_sha256_verified": verified_count,
            "max_absolute_error": max_absolute_error,
            "max_l2_error": max_l2_error,
        },
        "dimension": DIMENSION,
        "query_smoke": query_smoke,
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "external_store_writes": 0,
            "collection_create_count": 0,
            "actual_delete_count": 0,
            "files_deleted": 0,
            "overwritten_inputs": 0,
        },
        "verified_at": datetime.now(UTC).isoformat(),
    }
    return _write_report(output_dir, report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--collection-plan", type=Path, required=True)
    parser.add_argument("--chroma-path", type=Path, default=PROJECT_ROOT / "data/chroma")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import re

    try:
        if re.fullmatch(RUN_ID_PATTERN, args.run_id) is None:
            raise ValueError("run_id has an unsafe format")
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "chroma-import" / args.run_id
        path = verify_collection(
            collection_plan_path=args.collection_plan,
            chroma_path=args.chroma_path,
            output_dir=output_dir,
            batch_size=args.batch_size,
        )
        print(f"[PASS] Chroma read-only import verification: {path}")
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] Chroma read-only verification did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
