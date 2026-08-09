"""Build deterministic G2 dataset manifest and quality report from the fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from scripts.seed_g2 import DEFAULT_SEED, validate_seed


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_reports(seed: dict[str, Any], *, seed_path: Path, seed_bytes: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    resources = seed["resources"]
    tags = seed["tags"]
    behaviors = seed["behaviors"]
    resource_ids = {str(item["external_id"]) for item in resources}
    tag_ids = {str(item["normalized_name"]) for item in tags}
    resource_type_counts = Counter(str(item["resource_type"]) for item in resources)
    event_type_counts = Counter(str(item["event_type"]) for item in behaviors)
    occurred_at = sorted(str(item["occurred_at"]) for item in behaviors)

    check_results = {
        "resource_external_ids_unique": len(resource_ids) == len(resources),
        "tag_normalized_names_unique": len(tag_ids) == len(tags),
        "behavior_event_uuids_unique": len({str(item["event_uuid"]) for item in behaviors}) == len(behaviors),
        "behavior_resource_references_resolve": all(
            str(item["resource_external_id"]) in resource_ids for item in behaviors
        ),
        "resource_tag_references_resolve": all(
            str(tag["normalized_name"]) in tag_ids
            for resource in resources
            for tag in resource.get("tags", [])
        ),
        "metadata_quality_in_range": all(0 <= float(item["metadata_quality"]) <= 1 for item in resources),
        "tag_weights_in_range": all(
            0 <= float(tag["weight"]) <= 1 and 0 <= float(tag["confidence"]) <= 1
            for resource in resources
            for tag in resource.get("tags", [])
        ),
        "topic_negative_reason_explicit": sum(
            1
            for item in behaviors
            if item.get("reason_code") == "TOPIC_NOT_INTERESTED"
        )
        == 1,
        "synthetic_license_declared": bool(seed.get("source", {}).get("license")),
    }
    manifest = {
        "schema_version": "g2-dataset-manifest-v1",
        "manifest_version": "g2-manifest-v1",
        "seed_file": str(seed_path.relative_to(PROJECT_ROOT)),
        "seed_sha256": sha256_bytes(seed_bytes),
        "seed_version": str(seed["seed_version"]),
        "dataset_version": str(seed["dataset_version"]),
        "source": seed["source"],
        "counts": {
            "resources": len(resources),
            "tags": len(tags),
            "resource_tag_edges": sum(len(item.get("tags", [])) for item in resources),
            "declared_profiles": len(seed["declared_profiles"]),
            "behaviors": len(behaviors),
        },
        "resource_type_counts": dict(sorted(resource_type_counts.items())),
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "behavior_time_range": {"min": occurred_at[0], "max": occurred_at[-1]},
        "content_digest": sha256_bytes(canonical_json(seed).encode("utf-8")),
    }
    quality = {
        "schema_version": "g2-data-quality-report-v1",
        "manifest_version": "g2-manifest-v1",
        "seed_sha256": manifest["seed_sha256"],
        "status": "PASS" if all(check_results.values()) else "FAIL",
        "checks": check_results,
        "issue_count": sum(1 for passed in check_results.values() if not passed),
        "checked_counts": manifest["counts"],
    }
    return manifest, quality


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--quality-out", type=Path)
    parser.add_argument("--run-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        seed_path = args.seed_file.resolve()
        seed_bytes = seed_path.read_bytes()
        seed = validate_seed(json.loads(seed_bytes.decode("utf-8")))
        manifest, quality = build_reports(seed, seed_path=seed_path, seed_bytes=seed_bytes)
        if args.run_id:
            run_id = validate_run_id(args.run_id)
            output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g2" / run_id
            manifest_path = args.manifest_out or output_dir / "dataset_manifest.json"
            quality_path = args.quality_out or output_dir / "data-quality-report.json"
        else:
            manifest_path = args.manifest_out or PROJECT_ROOT / "contracts/data/g2/dataset_manifest.json"
            quality_path = args.quality_out or PROJECT_ROOT / "contracts/data/g2/data-quality-report-v1.json"
        write_json(manifest_path.resolve(), manifest)
        write_json(quality_path.resolve(), quality)
        print(f"[PASS] G2 dataset manifest: {manifest_path}")
        print(f"[PASS] G2 data quality report: {quality_path}")
        return 0 if quality["status"] == "PASS" else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[FAIL] G2 dataset report did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
