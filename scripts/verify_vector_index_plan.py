"""Verify a deterministic vector ChangePlan and its offline artifact.

This verifier is database-free.  It checks the plan schema, source-plan hash,
artifact hash/count, vector dimensions, per-record content/vector digests and
stable IDs without opening a MySQL, Neo4j, Chroma, or network connection.
"""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import struct
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_vector_index_plan import (
    DIMENSION,
    PROJECT_ROOT,
    SHA256_PATTERN,
    _sha256_bytes,
    vector_id,
)


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SCHEMA_PATH = PROJECT_ROOT / "contracts/data/intake/vector-index-plan.schema.json"


def _inside(path: str | Path, *, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside the repository") from exc
    return resolved


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def verify_plan(plan_path: Path) -> dict[str, Any]:
    plan_path = _inside(plan_path, label="plan")
    plan = _load_json(plan_path, label="vector plan")
    schema = _load_json(SCHEMA_PATH, label="vector plan schema")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise ValueError(f"vector plan schema violation at {location}: {errors[0].message}")
    if plan["can_build"] is not True:
        raise ValueError("vector plan is not buildable")
    source_path = _inside(plan["source_mysql_plan"], label="source MySQL plan")
    if _sha256_bytes(source_path.read_bytes()) != plan["source_mysql_plan_sha256"]:
        raise ValueError("source MySQL plan hash does not match vector plan")
    artifact = plan["artifacts"]["vectors"]
    vector_path = _inside(artifact["path"], label="vector artifact")
    vector_bytes = vector_path.read_bytes()
    if len(vector_bytes) != artifact["bytes"]:
        raise ValueError("vector artifact byte count does not match plan")
    if _sha256_bytes(vector_bytes) != artifact["sha256"]:
        raise ValueError("vector artifact hash does not match plan")
    seen_external_ids: set[str] = set()
    seen_vector_ids: set[str] = set()
    row_count = 0
    for line_number, line in enumerate(vector_bytes.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"vector artifact line {line_number} is invalid JSON") from exc
        if not isinstance(record, Mapping):
            raise ValueError(f"vector artifact line {line_number} must be an object")
        external_id = str(record.get("external_id", ""))
        current_vector_id = str(record.get("vector_id", ""))
        if not external_id or external_id in seen_external_ids:
            raise ValueError(f"vector artifact has duplicate/empty external_id at line {line_number}")
        if not current_vector_id or current_vector_id in seen_vector_ids:
            raise ValueError(f"vector artifact has duplicate/empty vector_id at line {line_number}")
        seen_external_ids.add(external_id)
        seen_vector_ids.add(current_vector_id)
        content_hash = str(record.get("content_hash", ""))
        if SHA256_PATTERN.fullmatch(content_hash) is None:
            raise ValueError(f"vector artifact content hash is invalid at line {line_number}")
        metadata_version = int(record["metadata_version"])
        expected_id = vector_id(
            external_id=external_id,
            content_hash=content_hash,
            metadata_version=metadata_version,
            embedding_version=str(plan["embedding_version"]),
        )
        if current_vector_id != expected_id:
            raise ValueError(f"vector id mismatch at line {line_number}")
        document = str(record.get("document", ""))
        if _sha256_bytes(document.encode("utf-8")) != record.get("document_sha256"):
            raise ValueError(f"document hash mismatch at line {line_number}")
        encoded = str(record.get("vector_base64", ""))
        try:
            decoded = base64.b64decode(encoded, validate=True)
            values = struct.unpack("<" + "f" * DIMENSION, decoded)
        except (ValueError, struct.error) as exc:
            raise ValueError(f"vector encoding is invalid at line {line_number}") from exc
        if len(decoded) != 4 * DIMENSION or len(values) != DIMENSION:
            raise ValueError(f"vector dimension mismatch at line {line_number}")
        if _sha256_bytes(decoded) != record.get("vector_sha256"):
            raise ValueError(f"vector hash mismatch at line {line_number}")
        if not all(value == value and abs(value) != float("inf") for value in values):
            raise ValueError(f"vector contains a non-finite value at line {line_number}")
        row_count += 1
    if row_count != artifact["count"] or row_count != plan["vector_count"]:
        raise ValueError("vector artifact count does not match plan")
    if row_count + plan["skipped_count"] != plan["resource_count"]:
        raise ValueError("vector and skipped counts do not cover resources")
    return {
        "schema_version": "vector-index-verification-v1",
        "status": "PASS",
        "plan": plan_path.relative_to(PROJECT_ROOT).as_posix(),
        "vector_artifact": vector_path.relative_to(PROJECT_ROOT).as_posix(),
        "graph_version": plan["graph_version"],
        "index_version": plan["index_version"],
        "embedding_version": plan["embedding_version"],
        "vector_count": row_count,
        "vector_sha256": artifact["sha256"],
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "external_store_writes": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
            "files_deleted": 0,
        },
        "verified_at": datetime.now(UTC).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
            raise ValueError("run_id has an unsafe format")
        report = verify_plan(args.plan)
        report_dir = PROJECT_ROOT / "artifacts" / "verification" / "vector-index-plan" / args.run_id
        report_dir.mkdir(parents=True, exist_ok=False)
        report_path = report_dir / "verification.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[PASS] vector index artifact verification: {report_path}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] vector index verification did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
