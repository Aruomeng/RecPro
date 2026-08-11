"""Verify a database-free, versioned Chroma collection ChangePlan."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_chroma_collection_plan import PROJECT_ROOT
from scripts.verify_vector_index_plan import _inside, _load_json, verify_plan


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SCHEMA_PATH = PROJECT_ROOT / "contracts/data/intake/chroma-collection-plan.schema.json"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_collection_plan(plan_path: Path) -> dict[str, Any]:
    plan_path = _inside(plan_path, label="Chroma collection plan")
    plan = _load_json(plan_path, label="Chroma collection plan")
    schema = _load_json(SCHEMA_PATH, label="Chroma collection schema")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise ValueError(f"Chroma collection plan schema violation at {location}: {errors[0].message}")
    if plan["can_build"] is not True:
        raise ValueError("Chroma collection plan is not buildable")
    source_vector_plan_path = _inside(plan["source_vector_plan"], label="source vector plan")
    if _sha256_bytes(source_vector_plan_path.read_bytes()) != plan["source_vector_plan_sha256"]:
        raise ValueError("source vector plan hash does not match")
    verify_plan(source_vector_plan_path)
    source_plan = _load_json(source_vector_plan_path, label="source vector plan")
    for key in ("embedding_version", "index_version", "namespace_name"):
        if plan[key] != source_plan[key]:
            raise ValueError(f"collection plan {key} does not match source vector plan")
    if plan["dimension"] != source_plan["embedding"]["dimension"]:
        raise ValueError("collection dimension does not match source vector plan")
    source_artifact = source_plan["artifacts"]["vectors"]
    artifact = plan["vector_artifact"]
    if artifact != {
        "path": source_artifact["path"],
        "sha256": source_artifact["sha256"],
        "bytes": source_artifact["bytes"],
        "count": source_artifact["count"],
    }:
        raise ValueError("collection vector artifact does not match source vector plan")
    if plan["record_count"] != source_plan["vector_count"]:
        raise ValueError("collection record count does not match source vector plan")
    if plan["quality"]["source_status"] != source_plan["status"]:
        raise ValueError("collection quality status does not match source vector plan")
    if plan["quality"]["source_blocker_count"] != len(source_plan["quality"]["blockers"]):
        raise ValueError("collection blocker count does not match source vector plan")
    if plan["quality"]["warning_count"] != len(source_plan["quality"]["warnings"]):
        raise ValueError("collection warning count does not match source vector plan")
    if any(value != 0 for value in plan["safety"].values()):
        raise ValueError("collection plan safety counters must all be zero")
    policy = plan["write_policy"]
    if policy != {
        "operation": "ADD_NEW_COLLECTION_ONLY",
        "append_only": True,
        "overwrite_existing": False,
        "physical_delete": False,
        "activity_switch": False,
    }:
        raise ValueError("collection plan write policy is not append-only")
    return {
        "schema_version": "chroma-collection-verification-v1",
        "status": "PASS",
        "plan": plan_path.relative_to(PROJECT_ROOT).as_posix(),
        "source_vector_plan": source_vector_plan_path.relative_to(PROJECT_ROOT).as_posix(),
        "collection_name": plan["collection_name"],
        "embedding_version": plan["embedding_version"],
        "index_version": plan["index_version"],
        "record_count": plan["record_count"],
        "client_version_status": plan["client"]["version_status"],
        "external_store_writes": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
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
        report = verify_collection_plan(args.plan)
        report_dir = PROJECT_ROOT / "artifacts" / "verification" / "chroma-collection-plan" / args.run_id
        report_dir.mkdir(parents=True, exist_ok=False)
        report_path = report_dir / "verification.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"[PASS] Chroma collection ChangePlan verification: {report_path}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] Chroma collection verification did not complete: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
