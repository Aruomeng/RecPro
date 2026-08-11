"""Append the verified vector artifact to one versioned Chroma collection.

This is an operator-only command.  It is intentionally separate from the
default backend runtime and requires both ``--apply`` and
``--confirm-chroma-write``.  The command only creates a new versioned
collection or appends missing IDs with identical metadata; it never exposes
collection lifecycle operations that could remove existing data.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from typing import Any, Iterable, Iterator, Mapping, Sequence

from backend.app.catalog.adapters.chroma import ChromaVectorReader
from scripts.verify_chroma_collection_plan import PROJECT_ROOT, _inside, _load_json, verify_collection_plan


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
DIMENSION = 384
DEFAULT_BATCH_SIZE = 256
MAX_BATCH_SIZE = 1000
SCHEMA_VERSION = "chroma-vector-import-v1"
VECTOR_ABS_TOLERANCE = 2e-6
VECTOR_L2_TOLERANCE = 2e-5


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run_id has an unsafe format")
    return value


def _load_chromadb() -> tuple[Any, Any]:
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:  # pragma: no cover - exercised in the base venv
        raise RuntimeError(
            "chromadb is not installed; use the locked G6 operator environment"
        ) from exc
    return chromadb, Settings


def _iter_records(collection_plan: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    artifact_path = _inside(collection_plan["vector_artifact"]["path"], label="vector artifact")
    with artifact_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"vector artifact line {line_number} is invalid JSON") from exc
            if not isinstance(record, dict):
                raise ValueError(f"vector artifact line {line_number} must be an object")
            yield record


def _decode_vector(record: Mapping[str, Any]) -> list[float]:
    if record.get("dimension") != DIMENSION:
        raise ValueError("vector record dimension does not match the frozen contract")
    if record.get("vector_encoding") != "float32-little-endian-base64":
        raise ValueError("vector record encoding does not match the frozen contract")
    encoded = str(record.get("vector_base64", ""))
    try:
        decoded = base64.b64decode(encoded, validate=True)
        values = struct.unpack("<" + "f" * DIMENSION, decoded)
    except (ValueError, struct.error) as exc:
        raise ValueError("vector encoding is invalid") from exc
    if len(decoded) != 4 * DIMENSION or not all(math.isfinite(value) for value in values):
        raise ValueError("vector dimension or finite-value contract failed")
    if _sha256_bytes(decoded) != record.get("vector_sha256"):
        raise ValueError("vector hash does not match the source artifact")
    return [float(value) for value in values]


def _metadata_for_record(
    record: Mapping[str, Any],
    *,
    collection_plan: Mapping[str, Any],
    graph_version: str,
) -> dict[str, object]:
    source_metadata = record.get("metadata")
    if not isinstance(source_metadata, Mapping):
        raise ValueError("vector record metadata must be an object")
    if record.get("embedding_version") != collection_plan["embedding_version"]:
        raise ValueError("vector record embedding version does not match the collection plan")
    external_id = str(record.get("external_id", "")).strip()
    vector_id = str(record.get("vector_id", "")).strip()
    content_hash = str(record.get("content_hash", ""))
    metadata_version = record.get("metadata_version")
    if (
        not external_id
        or not vector_id
        or SHA256_PATTERN.fullmatch(content_hash) is None
        or isinstance(metadata_version, bool)
        or not isinstance(metadata_version, int)
    ):
        raise ValueError("vector record identity is invalid")
    document = str(record.get("document", ""))
    if not document or _sha256_bytes(document.encode("utf-8")) != record.get("document_sha256"):
        raise ValueError("vector record document hash does not match the source artifact")
    required_fields = collection_plan["metadata_contract"]["required_fields"]
    if not all(field in source_metadata for field in required_fields if field not in {"external_id", "vector_id", "content_hash", "metadata_version", "index_version", "namespace_name"}):
        raise ValueError("vector record metadata is missing a required field")
    metadata: dict[str, object] = {str(key): value for key, value in source_metadata.items()}
    metadata.update(
        {
            "external_id": external_id,
            "vector_id": vector_id,
            "content_hash": content_hash,
            "metadata_version": metadata_version,
            "embedding_version": str(collection_plan["embedding_version"]),
            "index_version": str(collection_plan["index_version"]),
            "namespace_name": str(collection_plan["namespace_name"]),
            "graph_version": graph_version,
        }
    )
    return metadata


def _payload(
    record: Mapping[str, Any],
    *,
    collection_plan: Mapping[str, Any],
    graph_version: str,
) -> tuple[str, list[float], dict[str, object], str]:
    vector_id = str(record.get("vector_id", "")).strip()
    document = str(record.get("document", ""))
    if not vector_id or not document:
        raise ValueError("vector record must contain a vector ID and document")
    return (
        vector_id,
        _decode_vector(record),
        _metadata_for_record(record, collection_plan=collection_plan, graph_version=graph_version),
        document,
    )


def _chunks(items: Iterable[Any], size: int) -> Iterator[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _collection_name(item: Any) -> str:
    value = getattr(item, "name", item)
    if not isinstance(value, str) or not value:
        raise RuntimeError("Chroma returned an invalid collection name")
    return value


def _expected_collection_metadata(
    collection_plan: Mapping[str, Any], *, graph_version: str
) -> dict[str, str]:
    return {
        "hnsw:space": "cosine",
        "recpro_schema_version": "chroma-collection-plan-v1",
        "recpro_embedding_version": str(collection_plan["embedding_version"]),
        "recpro_index_version": str(collection_plan["index_version"]),
        "recpro_namespace_name": str(collection_plan["namespace_name"]),
        "recpro_graph_version": graph_version,
        "recpro_source_vector_plan_sha256": str(collection_plan["source_vector_plan_sha256"]),
    }


def _assert_collection_metadata(collection: Any, expected: Mapping[str, str]) -> None:
    actual = collection.metadata
    if not isinstance(actual, Mapping):
        raise RuntimeError("Chroma collection metadata is missing")
    for key, value in expected.items():
        if actual.get(key) != value:
            raise RuntimeError(f"Chroma collection metadata mismatch for {key}")


def _all_existing(collection: Any) -> dict[str, Mapping[str, Any]]:
    result = collection.get(include=["metadatas"])
    if not isinstance(result, Mapping):
        raise RuntimeError("Chroma collection get returned an invalid payload")
    ids = result.get("ids")
    metadatas = result.get("metadatas")
    if not isinstance(ids, list) or not isinstance(metadatas, list) or len(ids) != len(metadatas):
        raise RuntimeError("Chroma collection get returned mismatched IDs and metadata")
    output: dict[str, Mapping[str, Any]] = {}
    for identifier, metadata in zip(ids, metadatas):
        if not isinstance(identifier, str) or not identifier:
            raise RuntimeError("Chroma collection returned an invalid ID")
        if not isinstance(metadata, Mapping):
            raise RuntimeError("Chroma collection returned invalid metadata")
        if identifier in output:
            raise RuntimeError("Chroma collection returned duplicate IDs")
        output[identifier] = metadata
    return output


def _assert_same_metadata(existing: Mapping[str, Any], expected: Mapping[str, Any], identifier: str) -> None:
    for key, value in expected.items():
        if existing.get(key) != value:
            raise RuntimeError(f"existing Chroma ID has conflicting metadata: {identifier}:{key}")


def _as_list(value: Any, *, label: str) -> list[Any]:
    """Normalize Chroma list/NumPy return variants without importing NumPy."""

    if isinstance(value, list):
        return value
    to_list = getattr(value, "tolist", None)
    if callable(to_list):
        converted = to_list()
        if isinstance(converted, list):
            return converted
    raise RuntimeError(f"Chroma verification returned incomplete {label}")


def _compare_embedding(
    source_vector: Sequence[float], stored_vector: Sequence[Any], identifier: str
) -> tuple[float, float]:
    try:
        stored_values = tuple(float(value) for value in stored_vector)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Chroma embedding verification failed: {identifier}") from exc
    if len(stored_values) != DIMENSION or not all(math.isfinite(value) for value in stored_values):
        raise RuntimeError(f"Chroma embedding dimension verification failed: {identifier}")
    absolute_error = max(abs(float(source) - stored) for source, stored in zip(source_vector, stored_values))
    l2_error = math.sqrt(
        sum((float(source) - stored) ** 2 for source, stored in zip(source_vector, stored_values))
    )
    # Chroma's cosine index normalizes embeddings on persistence.  The
    # source artifact is already unit-normalized, but float32/float64 round
    # trips can change bytes by a few ulps.  Validate the numeric direction
    # with a strict tolerance instead of requiring impossible byte identity.
    if absolute_error > VECTOR_ABS_TOLERANCE or l2_error > VECTOR_L2_TOLERANCE:
        raise RuntimeError(
            f"Chroma embedding numeric verification failed: {identifier} "
            f"(max_abs={absolute_error:.3g}, l2={l2_error:.3g})"
        )
    return absolute_error, l2_error


def _build_expected_identity(
    collection_plan: Mapping[str, Any], *, graph_version: str
) -> dict[str, dict[str, object]]:
    identities: dict[str, dict[str, object]] = {}
    for record in _iter_records(collection_plan):
        vector_id = str(record.get("vector_id", "")).strip()
        metadata = _metadata_for_record(
            record, collection_plan=collection_plan, graph_version=graph_version
        )
        if not vector_id or vector_id in identities:
            raise RuntimeError("source vector artifact contains duplicate IDs")
        identities[vector_id] = metadata
    return identities


def _preflight_existing(
    collection: Any,
    *,
    expected_metadata: Mapping[str, Mapping[str, object]],
) -> tuple[set[str], int]:
    existing = _all_existing(collection)
    expected_ids = set(expected_metadata)
    unexpected = set(existing) - expected_ids
    if unexpected:
        raise RuntimeError(f"Chroma collection contains IDs outside this plan: {len(unexpected)}")
    for identifier, metadata in existing.items():
        _assert_same_metadata(metadata, expected_metadata[identifier], identifier)
    return set(existing), len(existing)


def _verify_batches(
    collection: Any,
    *,
    collection_plan: Mapping[str, Any],
    graph_version: str,
    batch_size: int,
) -> tuple[int, str, float, float]:
    count = 0
    first_id = ""
    max_absolute_error = 0.0
    max_l2_error = 0.0
    for records in _chunks(_iter_records(collection_plan), batch_size):
        records_by_id = {str(record["vector_id"]): record for record in records}
        payloads = [
            _payload(record, collection_plan=collection_plan, graph_version=graph_version)
            for record in records
        ]
        ids = [item[0] for item in payloads]
        result = collection.get(ids=ids, include=["embeddings", "metadatas", "documents"])
        if not isinstance(result, Mapping):
            raise RuntimeError("Chroma verification returned an invalid payload")
        returned_ids = _as_list(result.get("ids"), label="IDs")
        returned_embeddings = _as_list(result.get("embeddings"), label="embeddings")
        returned_metadatas = _as_list(result.get("metadatas"), label="metadata")
        returned_documents = _as_list(result.get("documents"), label="documents")
        if not (
            len(returned_ids) == len(returned_embeddings) == len(returned_metadatas) == len(returned_documents) == len(ids)
        ):
            raise RuntimeError("Chroma verification returned mismatched batch lengths")
        returned: dict[str, tuple[Any, Any, Any]] = {}
        for identifier, embedding, metadata, document in zip(
            returned_ids, returned_embeddings, returned_metadatas, returned_documents
        ):
            if not isinstance(identifier, str) or identifier in returned:
                raise RuntimeError("Chroma verification returned duplicate or invalid IDs")
            returned[identifier] = (embedding, metadata, document)
        for identifier, vector, metadata, document in payloads:
            if identifier not in returned:
                raise RuntimeError(f"Chroma verification missed ID: {identifier}")
            stored_vector, stored_metadata, stored_document = returned[identifier]
            if not isinstance(stored_metadata, Mapping) or stored_metadata != metadata:
                raise RuntimeError(f"Chroma metadata verification failed: {identifier}")
            if stored_document != document:
                raise RuntimeError(f"Chroma document verification failed: {identifier}")
            source_record = records_by_id[identifier]
            source_vector = _decode_vector(source_record)
            absolute_error, l2_error = _compare_embedding(source_vector, stored_vector, identifier)
            max_absolute_error = max(max_absolute_error, absolute_error)
            max_l2_error = max(max_l2_error, l2_error)
            if not first_id:
                first_id = identifier
            count += 1
    return count, first_id, max_absolute_error, max_l2_error


def _smoke_recall(
    collection: Any,
    *,
    first_record: Mapping[str, Any],
    collection_plan: Mapping[str, Any],
) -> dict[str, Any]:
    graph_plan = _load_json(
        _inside(collection_plan["source_vector_plan"], label="source vector plan"),
        label="source vector plan",
    )
    graph_version = str(graph_plan["graph_version"])
    vector = _decode_vector(first_record)
    reader = ChromaVectorReader(
        collection=collection,
        namespace_name=str(collection_plan["namespace_name"]),
        embedding_version=str(collection_plan["embedding_version"]),
        index_version=str(collection_plan["index_version"]),
        dimension=DIMENSION,
    )
    result = asyncio.run(
        reader.recall(
            query_vector=tuple(vector),
            embedding_version=str(collection_plan["embedding_version"]),
            index_version=str(collection_plan["index_version"]),
            limit=5,
        )
    )
    if not result:
        raise RuntimeError("Chroma smoke recall returned no hit")
    return {
        "query_vector_source": str(first_record["vector_id"]),
        "graph_version": graph_version,
        "hit_count": len(result),
        "top_external_id": result[0].external_id,
        "top_score": result[0].score,
    }


def _write_report(output_dir: Path, payload: Mapping[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    report_path = output_dir / "import.json"
    report_path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report_path


def import_vectors(
    *,
    collection_plan_path: Path,
    output_dir: Path,
    chroma_path: Path,
    apply: bool,
    confirm_chroma_write: bool,
    allow_existing_collection: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Path:
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise ValueError("batch_size must be between 1 and 1000")
    collection_plan_path = _inside(collection_plan_path, label="Chroma collection plan")
    report = verify_collection_plan(collection_plan_path)
    collection_plan = _load_json(collection_plan_path, label="Chroma collection plan")
    source_vector_plan = _load_json(
        _inside(collection_plan["source_vector_plan"], label="source vector plan"),
        label="source vector plan",
    )
    graph_version = str(source_vector_plan["graph_version"])
    expected_metadata = _build_expected_identity(collection_plan, graph_version=graph_version)
    expected_count = int(collection_plan["record_count"])
    if len(expected_metadata) != expected_count:
        raise RuntimeError("source record count does not match the collection plan")
    first_record = next(_iter_records(collection_plan), None)
    if first_record is None:
        raise RuntimeError("empty vector artifacts are not supported for this build")
    chroma_path = _inside(chroma_path, label="Chroma persistent path")
    output_dir = _inside(output_dir, label="Chroma import output")
    if output_dir.exists():
        raise FileExistsError(f"Chroma import evidence directory already exists: {output_dir}")

    base_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "NOT_APPLIED" if not apply else "PREPARING",
        "plan": collection_plan_path.relative_to(PROJECT_ROOT).as_posix(),
        "plan_sha256": _sha256_bytes(collection_plan_path.read_bytes()),
        "collection_name": str(collection_plan["collection_name"]),
        "chroma_path": chroma_path.relative_to(PROJECT_ROOT).as_posix(),
        "expected_count": expected_count,
        "created_collection": False,
        "collection_create_count": 0,
        "existing_count_before": 0,
        "added_count": 0,
        "write_batches_attempted": 0,
        "write_batches_completed": 0,
        "partial_write_uncertainty": False,
        "skipped_existing_count": 0,
        "final_count": 0,
        "query_smoke": None,
        "source_verification": report,
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "external_store_writes": 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
            "files_deleted": 0,
        },
        "started_at": datetime.now(UTC).isoformat(),
    }
    if not apply:
        base_payload["status"] = "PLAN_ONLY"
        base_payload["authorization"] = "--apply and --confirm-chroma-write are required"
        return _write_report(output_dir, base_payload)
    if not confirm_chroma_write:
        raise PermissionError("--confirm-chroma-write is required with --apply")
    if not chroma_path.exists() and not chroma_path.parent.exists():
        chroma_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        chromadb, settings_factory = _load_chromadb()
        settings = settings_factory(anonymized_telemetry=False, allow_reset=False)
        client = chromadb.PersistentClient(path=str(chroma_path), settings=settings)
        collection_name = str(collection_plan["collection_name"])
        names = {_collection_name(item) for item in client.list_collections()}
        expected_collection_metadata = _expected_collection_metadata(
            collection_plan, graph_version=graph_version
        )
        if collection_name in names:
            if not allow_existing_collection:
                raise PermissionError(
                    "target collection already exists; pass --allow-existing-collection for idempotent verification"
                )
            collection = client.get_collection(collection_name, embedding_function=None)
            _assert_collection_metadata(collection, expected_collection_metadata)
            base_payload["existing_count_before"] = int(collection.count())
        else:
            collection = client.create_collection(
                name=collection_name,
                metadata=expected_collection_metadata,
                embedding_function=None,
                get_or_create=False,
            )
            base_payload["created_collection"] = True
            base_payload["collection_create_count"] = 1

        existing_ids, existing_count = _preflight_existing(
            collection, expected_metadata=expected_metadata
        )
        base_payload["existing_count_before"] = existing_count
        missing_ids = set(expected_metadata) - existing_ids
        if existing_count > expected_count:
            raise RuntimeError("target collection contains more rows than the plan")
        for records in _chunks(_iter_records(collection_plan), batch_size):
            payloads = [
                _payload(record, collection_plan=collection_plan, graph_version=graph_version)
                for record in records
                if str(record.get("vector_id", "")).strip() in missing_ids
            ]
            if not payloads:
                continue
            base_payload["write_batches_attempted"] += 1
            try:
                collection.add(
                    ids=[item[0] for item in payloads],
                    embeddings=[item[1] for item in payloads],
                    metadatas=[item[2] for item in payloads],
                    documents=[item[3] for item in payloads],
                )
            except Exception:
                # Chroma clients do not guarantee whether a failed batch was
                # committed.  Never clean it up; require a later read-only
                # reconciliation/idempotent run instead.
                base_payload["partial_write_uncertainty"] = True
                raise
            base_payload["write_batches_completed"] += 1
            base_payload["added_count"] += len(payloads)

        base_payload["skipped_existing_count"] = len(existing_ids)
        final_count = int(collection.count())
        base_payload["final_count"] = final_count
        if final_count != expected_count:
            raise RuntimeError(f"Chroma count mismatch: expected {expected_count}, got {final_count}")
        verified_count, _first_verified_id, max_absolute_error, max_l2_error = _verify_batches(
            collection,
            collection_plan=collection_plan,
            graph_version=graph_version,
            batch_size=batch_size,
        )
        if verified_count != expected_count:
            raise RuntimeError(f"Chroma verification count mismatch: expected {expected_count}, got {verified_count}")
        base_payload["vector_numeric_validation"] = {
            "source_vector_sha256_verified": verified_count,
            "max_absolute_error": max_absolute_error,
            "max_l2_error": max_l2_error,
            "absolute_tolerance": VECTOR_ABS_TOLERANCE,
            "l2_tolerance": VECTOR_L2_TOLERANCE,
        }
        base_payload["query_smoke"] = _smoke_recall(
            collection,
            first_record=first_record,
            collection_plan=collection_plan,
        )
        base_payload["status"] = "APPLIED_VERIFIED"
        base_payload["safety"]["external_store_writes"] = int(base_payload["added_count"])
        base_payload["finished_at"] = datetime.now(UTC).isoformat()
        return _write_report(output_dir, base_payload)
    except Exception as exc:
        base_payload["status"] = "FAILED_NO_CLEANUP"
        base_payload["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        base_payload["finished_at"] = datetime.now(UTC).isoformat()
        base_payload["safety"]["external_store_writes"] = int(base_payload["added_count"])
        # Evidence is append-only too.  If a collection was created or a
        # batch may have been committed, leave it in place and record the
        # uncertainty; never attempt reset/cleanup.
        if not output_dir.exists():
            _write_report(output_dir, base_payload)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--collection-plan", type=Path, required=True)
    parser.add_argument("--chroma-path", type=Path, default=PROJECT_ROOT / "data/chroma")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-chroma-write", action="store_true")
    parser.add_argument("--allow-existing-collection", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_id = _safe_run_id(args.run_id)
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "chroma-import" / run_id
        report_path = import_vectors(
            collection_plan_path=args.collection_plan,
            output_dir=output_dir,
            chroma_path=args.chroma_path,
            apply=bool(args.apply),
            confirm_chroma_write=bool(args.confirm_chroma_write),
            allow_existing_collection=bool(args.allow_existing_collection),
            batch_size=args.batch_size,
        )
        print(f"[PASS] Chroma vector import: {report_path}")
        return 0
    except (OSError, PermissionError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] Chroma vector import did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
