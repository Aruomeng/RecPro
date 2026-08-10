"""Inspect normalized book metadata before any MySQL or Neo4j import.

The command is intentionally read-only.  It validates a strict intake manifest
and JSONL records, verifies source-file hashes, checks duplicate identities and
privacy/licensing gates, then writes one exclusive evidence report.  It does not
connect to either database and it never creates, updates, deletes, or overwrites
catalog or graph data.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
MANIFEST_SCHEMA = PROJECT_ROOT / "contracts/data/intake/book-intake-manifest.schema.json"
RECORD_SCHEMA = PROJECT_ROOT / "contracts/data/intake/book-record.schema.json"
DEFAULT_MANIFEST = PROJECT_ROOT / "data/incoming/books/intake_manifest.json"


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _load_json(path: Path, *, label: str) -> tuple[Any | None, bytes | None, str | None]:
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8")), raw, None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, f"{label}: {exc}"


def _schema(path: Path) -> Mapping[str, Any]:
    document, _, error = _load_json(path, label=str(path))
    if error is not None or not isinstance(document, Mapping):
        raise ValueError(error or f"{path} must contain a JSON object schema")
    return document


def _schema_errors(document: Any, schema: Mapping[str, Any]) -> list[str]:
    errors = Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document)
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(errors, key=lambda item: tuple(str(part) for part in item.absolute_path))
    ]


def _add_blocker(blockers: list[dict[str, str]], code: str, message: str) -> None:
    if any(item["code"] == code and item["message"] == message for item in blockers):
        return
    blockers.append({"code": code, "message": message})


def _verify_file(
    *,
    reference: str,
    expected_sha256: str,
    expected_bytes: int | None,
    label: str,
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
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
        "bytes": None,
        "size_matches": False,
    }
    if not path.is_file():
        _add_blocker(blockers, "REFERENCED_FILE_MISSING", f"{label}: {reference}")
        return summary
    raw = path.read_bytes()
    actual_sha256 = sha256_bytes(raw)
    summary.update(
        {
            "sha256": actual_sha256,
            "hash_matches": actual_sha256 == expected_sha256,
            "bytes": len(raw),
            "size_matches": expected_bytes is None or len(raw) == expected_bytes,
        }
    )
    if not summary["hash_matches"]:
        _add_blocker(blockers, "REFERENCED_FILE_HASH_MISMATCH", f"{label}: {reference}")
    if not summary["size_matches"]:
        _add_blocker(blockers, "REFERENCED_FILE_SIZE_MISMATCH", f"{label}: {reference}")
    return summary


def validate_record(
    record: Any,
    *,
    expected_source_id: str | None = None,
    expected_license_id: str | None = None,
) -> list[dict[str, str]]:
    """Validate one record without exposing its title or author in a report."""

    errors = _schema_errors(record, _schema(RECORD_SCHEMA))
    issues = [
        {"code": "RECORD_SCHEMA_INVALID", "message": error}
        for error in errors
    ]
    if not isinstance(record, Mapping):
        return issues
    if expected_source_id is not None and record.get("source_id") != expected_source_id:
        issues.append(
            {
                "code": "RECORD_SOURCE_MISMATCH",
                "message": "record source_id does not match the intake manifest",
            }
        )
    if expected_license_id is not None and record.get("license_id") not in (None, expected_license_id):
        issues.append(
            {
                "code": "RECORD_LICENSE_MISMATCH",
                "message": "record license_id does not match the intake manifest",
            }
        )
    tags = record.get("tags")
    if isinstance(tags, list):
        normalized_names = [
            str(tag.get("normalized_name"))
            for tag in tags
            if isinstance(tag, Mapping) and "normalized_name" in tag
        ]
        if len(normalized_names) != len(set(normalized_names)):
            issues.append(
                {
                    "code": "RECORD_DUPLICATE_TAG",
                    "message": "a record contains duplicate normalized tags",
                }
            )
    return issues


def build_intake_report(
    *,
    manifest_path: Path,
    git_commit: str,
    git_worktree_dirty: bool,
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    manifest_summary: dict[str, Any] = {
        "path": _relative(manifest_path),
        "exists": manifest_path.is_file(),
        "sha256": None,
        "schema_valid": False,
        "schema_errors": [],
    }
    if not manifest_path.is_file():
        _add_blocker(blockers, "INTAKE_MANIFEST_MISSING", "book intake manifest is not available")
        return _report(
            manifest_summary=manifest_summary,
            input_summary=None,
            blockers=blockers,
            git_commit=git_commit,
            git_worktree_dirty=git_worktree_dirty,
            record_count=0,
            valid_record_count=0,
            invalid_record_count=0,
            record_digest=None,
            warnings=[],
        )

    manifest, manifest_raw, parse_error = _load_json(manifest_path, label="book intake manifest")
    if parse_error is not None:
        _add_blocker(blockers, "INTAKE_MANIFEST_INVALID_JSON", "book intake manifest is not valid JSON")
        manifest_summary["schema_errors"] = [parse_error]
        return _report(
            manifest_summary=manifest_summary,
            input_summary=None,
            blockers=blockers,
            git_commit=git_commit,
            git_worktree_dirty=git_worktree_dirty,
            record_count=0,
            valid_record_count=0,
            invalid_record_count=0,
            record_digest=None,
            warnings=[],
        )

    manifest_summary["sha256"] = sha256_bytes(manifest_raw or b"")
    manifest_errors = _schema_errors(manifest, _schema(MANIFEST_SCHEMA))
    manifest_summary["schema_valid"] = not manifest_errors
    manifest_summary["schema_errors"] = manifest_errors
    if manifest_errors:
        _add_blocker(blockers, "INTAKE_MANIFEST_INVALID", "book intake manifest does not satisfy its schema")
        return _report(
            manifest_summary=manifest_summary,
            input_summary=None,
            blockers=blockers,
            git_commit=git_commit,
            git_worktree_dirty=git_worktree_dirty,
            record_count=0,
            valid_record_count=0,
            invalid_record_count=0,
            record_digest=None,
            warnings=[],
        )

    assert isinstance(manifest, Mapping)
    source = manifest["source"]
    input_file = manifest["input_file"]
    input_summary = _verify_file(
        reference=str(input_file["path"]),
        expected_sha256=str(input_file["sha256"]),
        expected_bytes=int(input_file["bytes"]),
        label="intake.input_file",
        blockers=blockers,
    )
    source_kind = str(source["kind"])
    warnings: list[dict[str, str]] = []
    if source_kind == "synthetic":
        warnings.append(
            {
                "code": "DEMO_ONLY",
                "message": "synthetic book data may be used for development but not confirmatory paper claims",
            }
        )
        if manifest["confirmation_eligible"] is True:
            _add_blocker(
                blockers,
                "SYNTHETIC_CONFIRMATION_FORBIDDEN",
                "synthetic intake cannot be marked confirmation_eligible",
            )
    if manifest["normalization"]["status"] != "NORMALIZED":
        _add_blocker(blockers, "NORMALIZATION_PENDING", "book records must be normalized before import")
    if manifest["privacy"]["status"] not in {"VERIFIED", "NOT_REQUIRED"}:
        _add_blocker(blockers, "PRIVACY_REVIEW_PENDING", "book intake privacy status is not approved")
    if manifest["privacy"]["contains_user_data"] is not False:
        _add_blocker(blockers, "USER_DATA_NOT_ALLOWED", "book intake must not contain user data")

    license_reference = str(source["license_evidence_ref"])
    if not license_reference.startswith(("https://", "http://", "doi:")):
        license_hash = source.get("license_evidence_sha256")
        if not isinstance(license_hash, str) or not SHA256_PATTERN.fullmatch(license_hash):
            _add_blocker(
                blockers,
                "LICENSE_EVIDENCE_HASH_MISSING",
                "local license evidence requires license_evidence_sha256",
            )
        else:
            _verify_file(
                reference=license_reference,
                expected_sha256=license_hash,
                expected_bytes=None,
                label="intake.license_evidence_ref",
                blockers=blockers,
            )

    record_count = 0
    valid_record_count = 0
    invalid_record_count = 0
    record_digests: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_isbns: set[str] = set()
    try:
        input_path = resolve_repository_path(str(input_file["path"]), label="intake.input_file")
    except ValueError:
        input_path = None
    if input_path is not None and input_path.is_file():
        for line_number, raw_line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            record_count += 1
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                invalid_record_count += 1
                _add_blocker(blockers, "RECORD_INVALID_JSON", f"book record line {line_number} is not valid JSON")
                continue
            issues = validate_record(
                record,
                expected_source_id=str(source["source_id"]),
                expected_license_id=str(source["license_id"]),
            )
            if isinstance(record, Mapping):
                key = (str(record.get("source_id", "")), str(record.get("source_record_id", "")))
                if key in seen_keys:
                    issues.append(
                        {
                            "code": "DUPLICATE_SOURCE_RECORD",
                            "message": "source_id/source_record_id must be unique",
                        }
                    )
                seen_keys.add(key)
                isbn = record.get("isbn")
                if isinstance(isbn, str) and isbn:
                    normalized_isbn = re.sub(r"[- ]", "", isbn).upper()
                    if normalized_isbn in seen_isbns:
                        issues.append(
                            {
                                "code": "DUPLICATE_ISBN",
                                "message": "ISBN is duplicated in the intake file",
                            }
                        )
                    seen_isbns.add(normalized_isbn)
            if issues:
                invalid_record_count += 1
                for issue in issues:
                    _add_blocker(
                        blockers,
                        issue["code"],
                        f"line {line_number}: {issue['message']}",
                    )
            else:
                valid_record_count += 1
                record_digests.append(sha256_bytes(canonical_json(record).encode("utf-8")))

    record_digest = (
        sha256_bytes("\n".join(record_digests).encode("ascii"))
        if record_digests
        else None
    )
    if input_summary["exists"] and record_count == 0:
        _add_blocker(blockers, "INTAKE_NO_RECORDS", "book intake JSONL contains no records")
    if invalid_record_count:
        _add_blocker(blockers, "INTAKE_RECORDS_INVALID", "one or more book records failed validation")
    return _report(
        manifest_summary=manifest_summary,
        input_summary=input_summary,
        blockers=blockers,
        git_commit=git_commit,
        git_worktree_dirty=git_worktree_dirty,
        record_count=record_count,
        valid_record_count=valid_record_count,
        invalid_record_count=invalid_record_count,
        record_digest=record_digest,
        warnings=warnings,
    )


def _report(
    *,
    manifest_summary: dict[str, Any],
    input_summary: dict[str, Any] | None,
    blockers: list[dict[str, str]],
    git_commit: str,
    git_worktree_dirty: bool,
    record_count: int,
    valid_record_count: int,
    invalid_record_count: int,
    record_digest: str | None,
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    if git_worktree_dirty:
        _add_blocker(blockers, "WORKTREE_DIRTY", "repository must be clean before an import plan is frozen")
    if blockers:
        status = "PASS_WITH_BLOCKERS"
    elif warnings:
        status = "READY_FOR_IMPORT_DEMO_ONLY"
    else:
        status = "READY_FOR_IMPORT"
    return {
        "schema_version": "book-intake-report-v1",
        "status": status,
        "can_import": not blockers,
        "paper_confirmation_ready": not warnings and not blockers,
        "verified_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "git_worktree_dirty": git_worktree_dirty,
        "manifest": manifest_summary,
        "input_file": input_summary,
        "records": {
            "total": record_count,
            "valid": valid_record_count,
            "invalid": invalid_record_count,
            "ordered_content_digest": record_digest,
        },
        "warnings": warnings,
        "blockers": blockers,
        "storage_plan": {
            "mysql_resource_catalog": "PENDING_IMPORT",
            "neo4j_graph_plan": "PENDING_IMPORT",
            "external_llm": "NOT_REQUIRED_FOR_INTAKE",
        },
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
        },
    }


def execute(*, run_id: str, manifest_path: Path, git_commit: str, git_worktree_dirty: bool) -> dict[str, Any]:
    validate_run_id(run_id)
    resolved_manifest = resolve_repository_path(manifest_path, label="book intake manifest")
    evidence_dir = PROJECT_ROOT / "artifacts/verification/data-intake" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    report = build_intake_report(
        manifest_path=resolved_manifest,
        git_commit=git_commit,
        git_worktree_dirty=git_worktree_dirty,
    )
    output_path = evidence_dir / "book-intake-report.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from subprocess import run

        git_commit = run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git_status = run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        execute(
            run_id=args.run_id,
            manifest_path=args.manifest,
            git_commit=git_commit,
            git_worktree_dirty=bool(git_status),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[FAIL] book intake inspection did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
