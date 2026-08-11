"""Create a database-free, append-only Chroma collection ChangePlan.

The plan freezes the collection/version, metadata contract, expected record
count and safety boundary from a verified vector plan.  It never imports a
Chroma client, connects to a store, or performs collection lifecycle work.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Sequence

from scripts.verify_vector_index_plan import PROJECT_ROOT, _inside, _load_json, verify_plan


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
CLIENT_STATUS = {"NOT_INSTALLED", "PIN_REQUIRED", "PINNED"}
SCHEMA_VERSION = "chroma-collection-plan-v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run_id has an unsafe format")
    return value


def build_plan(
    *,
    vector_plan_path: Path,
    output_dir: Path,
    client_version_status: str = "NOT_INSTALLED",
    client_version: str | None = None,
) -> Path:
    vector_plan_path = _inside(vector_plan_path, label="vector plan")
    vector_report = verify_plan(vector_plan_path)
    vector_plan = _load_json(vector_plan_path, label="vector plan")
    if client_version_status not in CLIENT_STATUS:
        raise ValueError("client version status is invalid")
    if client_version is not None and (not client_version.strip() or len(client_version) > 64):
        raise ValueError("client version is invalid")

    source_status = str(vector_plan["status"])
    quality = vector_plan["quality"]
    blockers = list(quality["blockers"])
    warnings = list(quality["warnings"])
    status = "PASS_WITH_BLOCKERS" if blockers else (
        "PASS_WITH_WARNINGS" if warnings else "READY_FOR_CHROMA_BUILD"
    )
    can_build = not blockers and vector_plan.get("can_build") is True
    artifact = vector_plan["artifacts"]["vectors"]
    artifact_path = _inside(artifact["path"], label="vector artifact")
    required_fields = [
        "external_id",
        "vector_id",
        "resource_type",
        "content_hash",
        "metadata_version",
        "embedding_version",
        "index_version",
        "namespace_name",
        "graph_version",
        "category_code",
        "publication_year",
        "difficulty_level",
        "available_from_epoch",
    ]
    plan_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "can_build": can_build,
        "collection_name": str(vector_plan["namespace_name"]),
        "distance_metric": "cosine",
        "embedding_version": str(vector_plan["embedding_version"]),
        "index_version": str(vector_plan["index_version"]),
        "namespace_name": str(vector_plan["namespace_name"]),
        "dimension": int(vector_plan["embedding"]["dimension"]),
        "client": {
            "package": "chromadb",
            "version_status": client_version_status,
            **({"version": client_version} if client_version is not None else {}),
            "write_authorization_required": True,
        },
        "source_vector_plan": vector_plan_path.relative_to(PROJECT_ROOT).as_posix(),
        "source_vector_plan_sha256": _sha256_bytes(vector_plan_path.read_bytes()),
        "vector_artifact": {
            "path": artifact_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": str(artifact["sha256"]),
            "bytes": int(artifact["bytes"]),
            "count": int(artifact["count"]),
        },
        "record_count": int(vector_plan["vector_count"]),
        "quality": {
            "source_status": source_status,
            "source_blocker_count": len(blockers),
            "warning_count": len(warnings),
            "missing_abstract_count": int(quality["missing_abstract_count"]),
            "missing_keywords_count": int(quality["missing_keywords_count"]),
        },
        "metadata_contract": {
            "required_fields": required_fields,
            "source_mapping": {
                "external_id": "vector_record.external_id",
                "vector_id": "vector_record.vector_id",
                "embedding_version": "vector_plan.embedding_version",
                "index_version": "vector_plan.index_version",
                "namespace_name": "vector_plan.namespace_name",
            },
            "version_filter": {
                "embedding_version": "embedding_version",
                "index_version": "index_version",
            },
        },
        "write_policy": {
            "operation": "ADD_NEW_COLLECTION_ONLY",
            "append_only": True,
            "overwrite_existing": False,
            "physical_delete": False,
            "activity_switch": False,
        },
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
    }
    output_dir = _inside(output_dir, label="collection plan output")
    if output_dir.exists():
        raise FileExistsError(f"collection plan evidence directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    plan_path = output_dir / "chroma-collection-plan.json"
    plan_path.write_text(
        json.dumps(plan_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # Keep the verifier's report in memory so this builder remains a single
    # append-only output and does not create a second mutable side effect.
    if vector_report["status"] != "PASS":
        raise ValueError("vector plan verification did not pass")
    return plan_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--vector-plan", type=Path, required=True)
    parser.add_argument(
        "--client-version-status",
        choices=sorted(CLIENT_STATUS),
        default="NOT_INSTALLED",
    )
    parser.add_argument("--client-version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_id = _safe_run_id(args.run_id)
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "chroma-collection-plan" / run_id
        plan_path = build_plan(
            vector_plan_path=args.vector_plan,
            output_dir=output_dir,
            client_version_status=args.client_version_status,
            client_version=args.client_version,
        )
        print(f"[PASS] Chroma collection ChangePlan: {plan_path}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] Chroma collection plan did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
