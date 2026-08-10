"""Validate formal evaluation input manifests without touching data or a database.

This checker is deliberately an intake gate, not a split generator or experiment
runner.  It reads the dataset, license, annotation, split and configuration
manifests, verifies referenced file hashes and cross-manifest relationships, and
writes one append-only evidence report.  It never edits an input, overwrites an
existing run, connects to a database, or treats the checked-in demo fixture as
paper evidence.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")

SCHEMA_PATHS = {
    "dataset": PROJECT_ROOT / "contracts" / "experiment" / "dataset-manifest.schema.json",
    "license": PROJECT_ROOT / "contracts" / "experiment" / "license-manifest.schema.json",
    "annotation": PROJECT_ROOT / "contracts" / "experiment" / "annotation-manifest.schema.json",
    "split": PROJECT_ROOT / "contracts" / "experiment" / "split-manifest.schema.json",
    "config": PROJECT_ROOT / "contracts" / "experiment" / "config-manifest.schema.json",
}

DEFAULT_PATHS = {
    # Keep the checked-in deterministic fixture as the default only so the
    # command produces a useful, explicit SYNTHETIC_DATASET blocker today.
    "dataset": PROJECT_ROOT / "contracts" / "data" / "g2" / "dataset_manifest.json",
    "license": PROJECT_ROOT / "data" / "evaluation" / "license_manifest.json",
    "annotation": PROJECT_ROOT / "data" / "evaluation" / "annotation_manifest.json",
    "split": PROJECT_ROOT / "data" / "evaluation" / "split_manifest.json",
    "config": PROJECT_ROOT / "data" / "evaluation" / "config_manifest.json",
}

def validate_run_id(value: str) -> str:
    """Reject path-like run IDs before they are used as an evidence directory."""

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


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def resolve_repository_path(value: str | Path, *, label: str) -> Path:
    """Resolve an input path and reject traversal or symlink escape."""

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def _load_schema(name: str) -> Mapping[str, Any]:
    path = SCHEMA_PATHS[name]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load {name} manifest schema: {exc}") from exc


def _format_schema_errors(errors: Sequence[Any]) -> list[str]:
    formatted: list[str] = []
    for error in sorted(errors, key=lambda item: tuple(str(part) for part in item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        formatted.append(f"{location}: {error.message}")
    return formatted


def _read_manifest(name: str, path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": _relative(path),
        "exists": path.is_file(),
        "sha256": None,
        "schema_valid": False,
        "schema_errors": [],
        "document": None,
    }
    if not path.is_file():
        result["status"] = "MISSING"
        return result

    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result["status"] = "INVALID_JSON"
        result["schema_errors"] = [str(exc)]
        return result

    result["sha256"] = sha256_bytes(raw)
    result["document"] = document
    if not isinstance(document, Mapping):
        result["status"] = "INVALID_SCHEMA"
        result["schema_errors"] = ["manifest root must be an object"]
        return result

    errors = list(
        Draft202012Validator(
            _load_schema(name),
            format_checker=FormatChecker(),
        ).iter_errors(document)
    )
    result["schema_valid"] = not errors
    result["schema_errors"] = _format_schema_errors(errors)
    result["status"] = "VALID" if not errors else "INVALID_SCHEMA"
    return result


def _public_manifest(result: Mapping[str, Any]) -> dict[str, Any]:
    document = result.get("document")
    summary: dict[str, Any] = {
        "path": result.get("path"),
        "exists": result.get("exists"),
        "sha256": result.get("sha256"),
        "status": result.get("status"),
        "schema_valid": result.get("schema_valid"),
        "schema_errors": result.get("schema_errors", []),
    }
    if isinstance(document, Mapping):
        for key in (
            "schema_version",
            "manifest_version",
            "dataset_version",
            "track",
            "status",
            "source",
            "approval_status",
            "annotation_version",
            "split_version",
            "config_version",
        ):
            if key in document:
                summary[key] = document[key]
    return summary


def _add_blocker(blockers: list[dict[str, str]], code: str, message: str) -> None:
    if any(item["code"] == code and item["message"] == message for item in blockers):
        return
    blockers.append({"code": code, "message": message})


def _verify_file(
    *,
    reference: str,
    expected_sha256: str,
    label: str,
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
    """Verify one repository-relative file and return a non-sensitive summary."""

    try:
        path = resolve_repository_path(reference, label=label)
    except ValueError as exc:
        _add_blocker(blockers, "REFERENCED_PATH_OUTSIDE_REPOSITORY", f"{label}: {exc}")
        return {"path": reference, "exists": False, "sha256": None, "hash_matches": False}

    summary: dict[str, Any] = {
        "path": _relative(path),
        "exists": path.is_file(),
        "sha256": None,
        "hash_matches": False,
    }
    if not path.is_file():
        _add_blocker(blockers, "REFERENCED_FILE_MISSING", f"{label}: {reference}")
        return summary
    actual_sha256 = sha256_bytes(path.read_bytes())
    summary["sha256"] = actual_sha256
    summary["hash_matches"] = actual_sha256 == expected_sha256
    if not summary["hash_matches"]:
        _add_blocker(
            blockers,
            "REFERENCED_FILE_HASH_MISMATCH",
            f"{label}: {reference}",
        )
    return summary


def _verify_dataset_files(
    document: Mapping[str, Any],
    blockers: list[dict[str, str]],
) -> list[dict[str, Any]]:
    files = document.get("input_files")
    if not isinstance(files, list):
        return []
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, Mapping):
            continue
        reference = item.get("path")
        expected = item.get("sha256")
        if not isinstance(reference, str) or not isinstance(expected, str):
            continue
        if reference in seen:
            _add_blocker(
                blockers,
                "DATASET_INPUT_DUPLICATE",
                f"dataset.input_files[{index}].path={reference}",
            )
        seen.add(reference)
        summary = _verify_file(
            reference=reference,
            expected_sha256=expected,
            label=f"dataset.input_files[{index}]",
            blockers=blockers,
        )
        expected_bytes = item.get("bytes")
        try:
            path = resolve_repository_path(reference, label="dataset input")
            if path.is_file() and isinstance(expected_bytes, int) and path.stat().st_size != expected_bytes:
                _add_blocker(
                    blockers,
                    "REFERENCED_FILE_SIZE_MISMATCH",
                    f"dataset.input_files[{index}]: {reference}",
                )
        except (OSError, ValueError):
            pass
        summaries.append(summary)
    return summaries


def _verify_license_evidence(
    document: Mapping[str, Any],
    blockers: list[dict[str, str]],
) -> list[dict[str, Any]]:
    sources = document.get("sources")
    if not isinstance(sources, list):
        return []
    summaries: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        if not isinstance(source, Mapping):
            continue
        reference = source.get("evidence_ref")
        if not isinstance(reference, str) or not reference:
            continue
        if reference.startswith(("https://", "http://", "doi:")):
            summaries.append({"reference": reference, "external": True})
            continue
        summary = _verify_file(
            reference=reference,
            expected_sha256=source.get("evidence_sha256", ""),
            label=f"license.sources[{index}].evidence_ref",
            blockers=blockers,
        )
        # Evidence hashes are optional for a legacy intake record, but a local
        # evidence file without a declared digest cannot be frozen safely.
        if not isinstance(source.get("evidence_sha256"), str) or not SHA256_PATTERN.fullmatch(
            source.get("evidence_sha256", "")
        ):
            _add_blocker(
                blockers,
                "LICENSE_EVIDENCE_HASH_MISSING",
                f"license.sources[{index}].evidence_sha256 is required for local evidence",
            )
        summaries.append(summary)
    return summaries


def _verify_annotation_files(
    document: Mapping[str, Any],
    blockers: list[dict[str, str]],
) -> dict[str, Any] | None:
    label_file = document.get("label_file")
    if not isinstance(label_file, Mapping):
        return None
    reference = label_file.get("path")
    expected = label_file.get("sha256")
    if not isinstance(reference, str) or not isinstance(expected, str):
        return None
    summary: dict[str, Any] = {
        "label_file": _verify_file(
            reference=reference,
            expected_sha256=expected,
            label="annotation.label_file",
            blockers=blockers,
        )
    }
    adjudication = document.get("adjudication")
    if isinstance(adjudication, Mapping):
        reference = adjudication.get("artifact_ref")
        if isinstance(reference, str) and reference and not reference.startswith(
            ("https://", "http://", "doi:")
        ):
            # The artifact reference is required to be a repository path when
            # it is local; its own content hash belongs in the audit record.
            try:
                path = resolve_repository_path(reference, label="annotation.adjudication.artifact_ref")
                if not path.is_file():
                    _add_blocker(blockers, "ADJUDICATION_ARTIFACT_MISSING", reference)
                summary["adjudication_artifact"] = {
                    "path": _relative(path),
                    "exists": path.is_file(),
                }
            except ValueError as exc:
                _add_blocker(blockers, "REFERENCED_PATH_OUTSIDE_REPOSITORY", str(exc))
    return summary


def _verify_split_files(
    document: Mapping[str, Any],
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for split_name in ("train", "validation", "test"):
        entry = document.get(split_name)
        if not isinstance(entry, Mapping):
            continue
        reference = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(reference, str) or not isinstance(expected, str):
            continue
        summaries[split_name] = _verify_file(
            reference=reference,
            expected_sha256=expected,
            label=f"split.{split_name}",
            blockers=blockers,
        )
    boundaries = document.get("boundaries")
    if isinstance(boundaries, Mapping):
        try:
            train_end = datetime.fromisoformat(str(boundaries["train_end"]).replace("Z", "+00:00"))
            validation_start = datetime.fromisoformat(
                str(boundaries["validation_start"]).replace("Z", "+00:00")
            )
            test_start = datetime.fromisoformat(str(boundaries["test_start"]).replace("Z", "+00:00"))
            if not (train_end <= validation_start < test_start):
                _add_blocker(
                    blockers,
                    "SPLIT_BOUNDARY_ORDER_INVALID",
                    "boundaries must satisfy train_end <= validation_start < test_start",
                )
            if any(value.tzinfo is None for value in (train_end, validation_start, test_start)):
                _add_blocker(blockers, "SPLIT_BOUNDARY_TIMEZONE_MISSING", "all split boundaries need a timezone")
        except (KeyError, TypeError, ValueError):
            # JSON Schema supplies the detailed format/required-field blocker.
            pass
    return summaries


def _verify_config_files(
    document: Mapping[str, Any],
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for key, label in (
        ("dependency_lock_file", "config.dependency_lock_file"),
        ("config_bundle_file", "config.config_bundle_file"),
    ):
        reference = document.get(key)
        digest_key = key.replace("_file", "_sha256")
        expected = document.get(digest_key)
        if isinstance(reference, str) and isinstance(expected, str):
            summaries[key] = _verify_file(
                reference=reference,
                expected_sha256=expected,
                label=label,
                blockers=blockers,
            )
    refs = document.get("input_refs")
    if isinstance(refs, Mapping):
        for name in ("dataset_manifest", "license_manifest", "annotation_manifest", "split_manifest"):
            ref = refs.get(name)
            if not isinstance(ref, Mapping):
                continue
            path = ref.get("path")
            expected = ref.get("sha256")
            if isinstance(path, str) and isinstance(expected, str):
                summaries[f"input_ref:{name}"] = _verify_file(
                    reference=path,
                    expected_sha256=expected,
                    label=f"config.input_refs.{name}",
                    blockers=blockers,
                )
    return summaries


def _cross_manifest_checks(
    manifests: Mapping[str, Mapping[str, Any]],
    blockers: list[dict[str, str]],
    *,
    git_commit: str,
) -> dict[str, bool]:
    dataset = manifests["dataset"].get("document")
    license_manifest = manifests["license"].get("document")
    annotation = manifests["annotation"].get("document")
    split = manifests["split"].get("document")
    config = manifests["config"].get("document")

    dataset_version = dataset.get("dataset_version") if isinstance(dataset, Mapping) else None
    source = dataset.get("source") if isinstance(dataset, Mapping) else None
    source_kind = source.get("kind") if isinstance(source, Mapping) else None
    if source_kind == "synthetic":
        _add_blocker(
            blockers,
            "SYNTHETIC_DATASET",
            "the available dataset source is synthetic and cannot support confirmatory paper claims",
        )
    if isinstance(dataset, Mapping):
        if dataset.get("confirmation_eligible") is not True:
            _add_blocker(
                blockers,
                "DATASET_CONFIRMATION_DISABLED",
                "dataset.confirmation_eligible must be true for a formal run",
            )
        anonymization = dataset.get("anonymization")
        if not isinstance(anonymization, Mapping) or anonymization.get("status") != "VERIFIED" or anonymization.get("mapping_separated") is not True:
            _add_blocker(
                blockers,
                "ANONYMIZATION_NOT_VERIFIED",
                "dataset anonymization must be VERIFIED with mapping_separated=true",
            )
        counts = dataset.get("counts")
        track = dataset.get("track")
        if isinstance(counts, Mapping):
            thresholds = (
                (
                    ("resources", 5000),
                    ("anonymous_users", 200),
                    ("events", 30000),
                )
                if track == "TRACK_I"
                else (("tasks", 100),) if track == "TRACK_J" else ()
            )
            for field, minimum in thresholds:
                value = counts.get(field)
                if not isinstance(value, int) or value < minimum:
                    _add_blocker(
                        blockers,
                        "DATASET_SCALE_BELOW_THRESHOLD",
                        f"dataset.counts.{field} must be at least {minimum} for {track}",
                    )
            if track == "TRACK_I" and (
                not isinstance(anonymization, Mapping)
                or anonymization.get("status") != "VERIFIED"
            ):
                _add_blocker(
                    blockers,
                    "TRACK_I_ANONYMIZATION_REQUIRED",
                    "Track-I requires verified user anonymization",
                )

    if isinstance(license_manifest, Mapping):
        if license_manifest.get("dataset_version") != dataset_version:
            _add_blocker(blockers, "DATASET_VERSION_MISMATCH", "dataset and license manifests disagree")
        if license_manifest.get("approval_status") != "VERIFIED":
            _add_blocker(blockers, "LICENSE_NOT_VERIFIED", "license approval_status must be VERIFIED")
        if isinstance(source, Mapping):
            expected_source_id = source.get("source_id")
            expected_license_id = source.get("license_id")
            source_entries = license_manifest.get("sources")
            matches = (
                [entry for entry in source_entries if isinstance(entry, Mapping)]
                if isinstance(source_entries, list)
                else []
            )
            if not any(
                entry.get("source_id") == expected_source_id and entry.get("license_id") == expected_license_id
                for entry in matches
            ):
                _add_blocker(
                    blockers,
                    "LICENSE_SOURCE_MISMATCH",
                    "license manifest must cover dataset.source.source_id and license_id",
                )

    for name, document in (("annotation", annotation), ("split", split), ("config", config)):
        if isinstance(document, Mapping) and document.get("dataset_version") != dataset_version:
            _add_blocker(blockers, "DATASET_VERSION_MISMATCH", f"dataset and {name} manifests disagree")

    if isinstance(annotation, Mapping):
        reliability = annotation.get("reliability")
        if not isinstance(reliability, Mapping) or reliability.get("meets_threshold") is not True:
            _add_blocker(blockers, "ANNOTATION_RELIABILITY_NOT_MET", "annotation reliability threshold is not met")
        else:
            value = reliability.get("value")
            threshold = reliability.get("threshold")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isinstance(threshold, (int, float))
                and not isinstance(threshold, bool)
                and value < threshold
            ):
                _add_blocker(
                    blockers,
                    "ANNOTATION_RELIABILITY_VALUE_BELOW_THRESHOLD",
                    "annotation reliability value is below its declared threshold",
                )
        adjudication = annotation.get("adjudication")
        if not isinstance(adjudication, Mapping) or adjudication.get("status") != "COMPLETE":
            _add_blocker(blockers, "ANNOTATION_ADJUDICATION_INCOMPLETE", "annotation adjudication must be COMPLETE")
        elif not adjudication.get("artifact_ref"):
            _add_blocker(
                blockers,
                "ANNOTATION_ADJUDICATION_ARTIFACT_MISSING",
                "completed annotation adjudication requires artifact_ref",
            )
        if annotation.get("test_set_frozen") is not True:
            _add_blocker(blockers, "ANNOTATION_TEST_SET_NOT_FROZEN", "annotation test_set_frozen must be true")

    if isinstance(split, Mapping):
        for key, expected in (("no_overlap", True), ("user_group_leakage", False), ("event_unique", True), ("frozen", True)):
            if split.get(key) is not expected:
                _add_blocker(blockers, "SPLIT_SAFETY_PROPERTY_FAILED", f"split.{key} must be {expected!r}")
        if split.get("strategy") in {"GROUP_TIME", "STRATIFIED_GROUP"} and split.get("group_key") == "NONE":
            _add_blocker(
                blockers,
                "SPLIT_GROUP_KEY_INVALID",
                "group-based split strategies require a non-NONE group_key",
            )

    if isinstance(config, Mapping):
        if config.get("status") != "FROZEN":
            _add_blocker(blockers, "CONFIG_NOT_FROZEN", "config status must be FROZEN")
        if config.get("git_commit") != git_commit:
            _add_blocker(blockers, "CONFIG_COMMIT_MISMATCH", "config git_commit must equal the checked commit")
        if config.get("worktree_clean") is not True:
            _add_blocker(blockers, "CONFIG_WORKTREE_DIRTY", "config worktree_clean must be true")

        refs = config.get("input_refs")
        if isinstance(refs, Mapping):
            for name in ("dataset", "license", "annotation", "split"):
                ref = refs.get(f"{name}_manifest")
                actual = manifests[name]
                if not isinstance(ref, Mapping) or not actual.get("schema_valid"):
                    continue
                if ref.get("path") != actual.get("path") or ref.get("sha256") != actual.get("sha256"):
                    _add_blocker(
                        blockers,
                        "CONFIG_INPUT_REF_MISMATCH",
                        f"config.input_refs.{name}_manifest does not match the loaded manifest",
                    )

    f1_ok = not any(
        item["code"]
        in {
            "DATASET_MANIFEST_MISSING",
            "DATASET_MANIFEST_INVALID",
            "DATASET_MANIFEST_INVALID_JSON",
            "DATASET_CONFIRMATION_DISABLED",
            "SYNTHETIC_DATASET",
            "ANONYMIZATION_NOT_VERIFIED",
            "DATASET_SCALE_BELOW_THRESHOLD",
            "TRACK_I_ANONYMIZATION_REQUIRED",
            "LICENSE_MANIFEST_MISSING",
            "LICENSE_NOT_VERIFIED",
            "LICENSE_SOURCE_MISMATCH",
            "DATASET_VERSION_MISMATCH",
        }
        for item in blockers
    )
    f2_ok = not any(
        item["code"]
        in {
            "SPLIT_MANIFEST_MISSING",
            "SPLIT_MANIFEST_INVALID",
            "SPLIT_SAFETY_PROPERTY_FAILED",
            "SPLIT_GROUP_KEY_INVALID",
            "SPLIT_BOUNDARY_ORDER_INVALID",
            "REFERENCED_FILE_MISSING",
            "REFERENCED_FILE_HASH_MISMATCH",
        }
        for item in blockers
    )
    f3_ok = not any(
        item["code"]
        in {
            "CONFIG_MANIFEST_MISSING",
            "CONFIG_MANIFEST_INVALID",
            "CONFIG_NOT_FROZEN",
            "CONFIG_COMMIT_MISMATCH",
            "CONFIG_WORKTREE_DIRTY",
            "CONFIG_INPUT_REF_MISMATCH",
            "WORKTREE_DIRTY",
            "REFERENCED_FILE_MISSING",
            "REFERENCED_FILE_HASH_MISMATCH",
            "REFERENCED_PATH_OUTSIDE_REPOSITORY",
        }
        for item in blockers
    )
    return {"F1_data": f1_ok, "F2_split": f2_ok, "F3_configuration": f3_ok}


def build_evaluation_freeze_report(
    *,
    dataset_path: Path,
    license_path: Path,
    annotation_path: Path,
    split_path: Path,
    config_path: Path,
    git_status: str,
    git_commit: str,
) -> dict[str, Any]:
    paths = {
        "dataset": dataset_path,
        "license": license_path,
        "annotation": annotation_path,
        "split": split_path,
        "config": config_path,
    }
    manifests = {name: _read_manifest(name, path) for name, path in paths.items()}
    blockers: list[dict[str, str]] = []
    for name, result in manifests.items():
        if not result["exists"]:
            _add_blocker(blockers, f"{name.upper()}_MANIFEST_MISSING", f"{name} manifest is not available")
        elif result["status"] == "INVALID_JSON":
            _add_blocker(blockers, f"{name.upper()}_MANIFEST_INVALID_JSON", f"{name} manifest is not valid JSON")
        elif not result["schema_valid"]:
            _add_blocker(blockers, f"{name.upper()}_MANIFEST_INVALID", f"{name} manifest does not satisfy its schema")

    dataset_doc = manifests["dataset"].get("document")
    if isinstance(dataset_doc, Mapping) and manifests["dataset"].get("schema_valid"):
        input_summaries = _verify_dataset_files(dataset_doc, blockers)
    else:
        input_summaries = []
    license_doc = manifests["license"].get("document")
    license_summaries = (
        _verify_license_evidence(license_doc, blockers)
        if isinstance(license_doc, Mapping) and manifests["license"].get("schema_valid")
        else []
    )
    annotation_doc = manifests["annotation"].get("document")
    annotation_summary = (
        _verify_annotation_files(annotation_doc, blockers)
        if isinstance(annotation_doc, Mapping) and manifests["annotation"].get("schema_valid")
        else None
    )
    split_doc = manifests["split"].get("document")
    split_summaries = (
        _verify_split_files(split_doc, blockers)
        if isinstance(split_doc, Mapping) and manifests["split"].get("schema_valid")
        else {}
    )
    config_doc = manifests["config"].get("document")
    config_summaries = (
        _verify_config_files(config_doc, blockers)
        if isinstance(config_doc, Mapping) and manifests["config"].get("schema_valid")
        else {}
    )

    if git_status:
        _add_blocker(blockers, "WORKTREE_DIRTY", "repository must be clean before a formal run")

    freeze = _cross_manifest_checks(manifests, blockers, git_commit=git_commit)
    report = {
        "schema_version": "evaluation-input-freeze-report-v1",
        "status": "PASS_WITH_BLOCKERS" if blockers else "READY_FOR_FORMAL_RUN",
        "paper_confirmation_ready": not blockers,
        "verified_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "git_worktree_dirty": bool(git_status),
        "git_status_summary": git_status,
        "manifests": {name: _public_manifest(result) for name, result in manifests.items()},
        "freeze": {
            **freeze,
            "annotation": not any(
                item["code"]
                in {
                    "ANNOTATION_MANIFEST_MISSING",
                    "ANNOTATION_MANIFEST_INVALID",
                    "ANNOTATION_MANIFEST_INVALID_JSON",
                    "ANNOTATION_RELIABILITY_NOT_MET",
                    "ANNOTATION_RELIABILITY_VALUE_BELOW_THRESHOLD",
                    "ANNOTATION_ADJUDICATION_INCOMPLETE",
                    "ANNOTATION_ADJUDICATION_ARTIFACT_MISSING",
                    "ANNOTATION_TEST_SET_NOT_FROZEN",
                    "ADJUDICATION_ARTIFACT_MISSING",
                    "REFERENCED_FILE_MISSING",
                    "REFERENCED_FILE_HASH_MISMATCH",
                    "REFERENCED_PATH_OUTSIDE_REPOSITORY",
                }
                for item in blockers
            ),
            "F4_predictions": False,
            "F5_report": False,
        },
        "referenced_files": {
            "dataset": input_summaries,
            "license": license_summaries,
            "annotation": annotation_summary,
            "split": split_summaries,
            "config": config_summaries,
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
    return report


def execute(
    *,
    run_id: str,
    dataset_path: Path,
    license_path: Path,
    annotation_path: Path,
    split_path: Path,
    config_path: Path,
) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    resolved_paths = {
        name: resolve_repository_path(path, label=f"{name} manifest")
        for name, path in {
            "dataset": dataset_path,
            "license": license_path,
            "annotation": annotation_path,
            "split": split_path,
            "config": config_path,
        }.items()
    }
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "experiment-inputs" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    report = build_evaluation_freeze_report(
        **{f"{name}_path": path for name, path in resolved_paths.items()},
        git_status=_git("status", "--porcelain"),
        git_commit=_git("rev-parse", "HEAD"),
    )
    output_path = evidence_dir / "input-freeze-report.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_PATHS["dataset"])
    parser.add_argument("--license", dest="license_path", type=Path, default=DEFAULT_PATHS["license"])
    parser.add_argument("--annotation", type=Path, default=DEFAULT_PATHS["annotation"])
    parser.add_argument("--split", type=Path, default=DEFAULT_PATHS["split"])
    parser.add_argument("--config", dest="config_path", type=Path, default=DEFAULT_PATHS["config"])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        execute(
            run_id=args.run_id,
            dataset_path=args.dataset,
            license_path=args.license_path,
            annotation_path=args.annotation,
            split_path=args.split,
            config_path=args.config_path,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] evaluation input freeze did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
