"""Run an append-only preflight for the paper experiment freeze gates.

The preflight is intentionally not an experiment runner.  It validates the
frozen protocol and the currently available dataset manifest, reports missing
F1--F5 artifacts without fabricating them, and writes one new evidence report.
It never connects to a database and never removes or overwrites a prior run.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence

from scripts.build_g2_dataset_report import build_reports
from scripts.seed_g2 import validate_seed


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
REQUIRED_PROTOCOL_MARKERS = (
    "协议版本：1.0.0",
    "## 19. 冻结规则",
    "## 25. 正式实验启动门禁",
    "expected_delete_count=0",
)


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _check_protocol(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    missing = [marker for marker in REQUIRED_PROTOCOL_MARKERS if marker not in text]
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "sha256": sha256_bytes(path.read_bytes()),
        "protocol_version": "1.0.0" if not missing else None,
        "required_markers_present": not missing,
        "missing_markers": missing,
    }


def _check_manifest(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    seed_path_value = manifest.get("seed_file")
    if not isinstance(seed_path_value, str) or not seed_path_value:
        raise ValueError("dataset manifest seed_file is required")
    seed_path = (PROJECT_ROOT / seed_path_value).resolve()
    seed_path.relative_to(PROJECT_ROOT)
    seed_bytes = seed_path.read_bytes()
    seed = validate_seed(json.loads(seed_bytes.decode("utf-8")))
    expected_manifest, quality = build_reports(
        seed,
        seed_path=seed_path,
        seed_bytes=seed_bytes,
    )
    manifest_matches_seed = manifest == expected_manifest
    source = manifest.get("source")
    source_kind = source.get("kind") if isinstance(source, dict) else None
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "sha256": sha256_bytes(path.read_bytes()),
        "seed_path": str(seed_path.relative_to(PROJECT_ROOT)),
        "seed_sha256_matches": manifest.get("seed_sha256") == sha256_bytes(seed_bytes),
        "manifest_matches_seed": manifest_matches_seed,
        "quality_status": quality["status"],
        "source_kind": source_kind,
        "dataset_version": manifest.get("dataset_version"),
        "manifest_version": manifest.get("manifest_version"),
    }


def _artifact_state(path: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "exists": path.exists(),
        "sha256": sha256_bytes(path.read_bytes()) if path.is_file() else None,
    }


def build_preflight_report(
    *,
    protocol_path: Path,
    manifest_path: Path,
    git_status: str,
    git_commit: str,
) -> dict[str, object]:
    protocol = _check_protocol(protocol_path)
    manifest = _check_manifest(manifest_path)
    blockers: list[dict[str, str]] = []

    if not protocol["required_markers_present"]:
        blockers.append(
            {
                "code": "F0_PROTOCOL_INCOMPLETE",
                "message": "The frozen protocol is missing required gate markers.",
            }
        )
    if not manifest["seed_sha256_matches"] or not manifest["manifest_matches_seed"]:
        blockers.append(
            {
                "code": "F1_MANIFEST_MISMATCH",
                "message": "The dataset manifest does not match its immutable seed.",
            }
        )
    if manifest["source_kind"] == "synthetic":
        blockers.append(
            {
                "code": "DEMO_FIXTURE",
                "message": "The available G2 fixture is synthetic and cannot support confirmatory paper accuracy claims.",
            }
        )
    if git_status:
        blockers.append(
            {
                "code": "WORKTREE_DIRTY",
                "message": "The repository must be committed and clean before a formal test run.",
            }
        )

    split_manifest = PROJECT_ROOT / "data" / "evaluation" / "split_manifest.json"
    annotation_manifest = PROJECT_ROOT / "data" / "evaluation" / "annotation_manifest.json"
    config_manifest = PROJECT_ROOT / "data" / "evaluation" / "config_manifest.json"
    prediction_root = PROJECT_ROOT / "experiments" / "runs"
    for code, path, message in (
        (
            "F2_SPLIT_MISSING",
            split_manifest,
            "A frozen train/validation/test split is not available.",
        ),
        (
            "ANNOTATION_MANIFEST_MISSING",
            annotation_manifest,
            "A blinded annotation manifest is not available.",
        ),
        (
            "F3_CONFIG_MANIFEST_MISSING",
            config_manifest,
            "A formal evaluation configuration manifest is not available.",
        ),
    ):
        if not path.is_file():
            blockers.append({"code": code, "message": message})

    return {
        "status": "PASS_WITH_BLOCKERS" if blockers else "READY_FOR_FORMAL_RUN",
        "paper_confirmation_ready": not blockers,
        "verified_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "git_worktree_dirty": bool(git_status),
        "git_status_summary": git_status,
        "protocol": protocol,
        "dataset": manifest,
        "freeze": {
            "F0_protocol": not any(item["code"] == "F0_PROTOCOL_INCOMPLETE" for item in blockers),
            "F1_data": not any(item["code"] in {"F1_MANIFEST_MISMATCH", "DEMO_FIXTURE"} for item in blockers),
            "F2_split": split_manifest.is_file(),
            "F3_configuration": config_manifest.is_file() and not bool(git_status),
            "F4_predictions": False,
            "F5_report": False,
        },
        "artifacts": {
            "split_manifest": _artifact_state(split_manifest),
            "annotation_manifest": _artifact_state(annotation_manifest),
            "config_manifest": _artifact_state(config_manifest),
            "prediction_root": {
                "path": str(prediction_root.relative_to(PROJECT_ROOT)),
                "exists": prediction_root.exists(),
            },
        },
        "blockers": blockers,
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_runs": 0,
        },
    }


def execute(
    *,
    run_id: str,
    protocol_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    run_id = validate_run_id(run_id)
    protocol_path = protocol_path.resolve()
    manifest_path = manifest_path.resolve()
    protocol_path.relative_to(PROJECT_ROOT)
    manifest_path.relative_to(PROJECT_ROOT)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "experiment" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    report = build_preflight_report(
        protocol_path=protocol_path,
        manifest_path=manifest_path,
        git_status=_git("status", "--porcelain"),
        git_commit=_git("rev-parse", "HEAD"),
    )
    output_path = evidence_dir / "freeze-preflight.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=PROJECT_ROOT / "docs" / "experiment_protocol.md",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "contracts" / "data" / "g2" / "dataset_manifest.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        execute(run_id=args.run_id, protocol_path=args.protocol, manifest_path=args.manifest)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] experiment freeze preflight did not complete: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
