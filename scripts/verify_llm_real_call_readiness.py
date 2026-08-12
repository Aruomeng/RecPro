#!/usr/bin/env python3
"""Verify whether a real DeepSeek call may be explicitly authorized.

This is a local, network-free preflight.  It validates the ignored runtime
environment, the pinned Prompt Bundle, and provider construction.  It never
calls DeepSeek, starts an application, connects to a database, claims Outbox
rows, or changes an existing artifact.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from backend.app.config import AppSettings
from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from backend.app.llm.factory import build_llm_provider
from backend.app.llm.prompts import PromptBundleError, load_prompt_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def resolve_env_file(path: Path) -> Path:
    candidate = path if path.is_absolute() else PROJECT_ROOT / path
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("environment file must stay inside the repository") from exc
    return resolved


def _settings_from_file(path: Path) -> AppSettings:
    """Load settings through Pydantic without exporting secrets to the shell."""

    return AppSettings(_env_file=str(path))


def _safe_provider_summary(provider: object, settings: AppSettings) -> dict[str, Any]:
    return {
        "constructed": isinstance(provider, DeepSeekLLMProvider),
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "base_url_origin": settings.llm_base_url,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_output_tokens": settings.llm_max_output_tokens,
        "api_key_present": settings.llm_api_key is not None,
    }


def build_report(*, env_file: Path, run_id: str | None = None) -> dict[str, Any]:
    env_file = resolve_env_file(env_file)
    errors: list[str] = []
    settings: AppSettings | None = None
    provider: object | None = None
    prompt_summary: dict[str, Any] = {
        "valid": False,
        "path": None,
        "version": None,
        "source_sha256": None,
        "task_count": 0,
    }
    try:
        settings = _settings_from_file(env_file)
    except Exception as exc:  # Pydantic errors must not expose secret values.
        errors.append(f"runtime configuration is invalid: {type(exc).__name__}")

    if settings is not None:
        try:
            bundle = load_prompt_bundle(
                settings.prompt_bundle_path,
                expected_sha256=settings.prompt_bundle_sha256,
                expected_version=settings.prompt_bundle_version,
            )
            prompt_summary = {
                "valid": True,
                "path": bundle.source_path,
                "version": bundle.bundle_version,
                "source_sha256": bundle.source_sha256,
                "task_count": len(bundle.tasks),
            }
        except (OSError, PromptBundleError, ValueError) as exc:
            errors.append(f"Prompt Bundle validation failed: {type(exc).__name__}")

        try:
            provider = build_llm_provider(settings)
        except (OSError, PromptBundleError, ValueError, RuntimeError) as exc:
            errors.append(f"provider construction failed: {type(exc).__name__}")

        if settings.llm_provider != "deepseek":
            errors.append("RECPRO_LLM_PROVIDER is not deepseek")
        if settings.app_env == "production":
            errors.append("production external LLM composition is not approved")

    provider_summary = (
        _safe_provider_summary(provider, settings)
        if settings is not None and provider is not None
        else {
            "constructed": False,
            "provider": settings.llm_provider if settings is not None else None,
            "model": settings.llm_model if settings is not None else None,
            "base_url_origin": settings.llm_base_url if settings is not None else None,
            "timeout_seconds": settings.llm_timeout_seconds if settings is not None else None,
            "max_output_tokens": settings.llm_max_output_tokens if settings is not None else None,
            "api_key_present": bool(settings and settings.llm_api_key is not None),
        }
    )
    ready = not errors and provider_summary["constructed"] and prompt_summary["valid"]
    report: dict[str, Any] = {
        "schema_version": "llm-real-call-readiness-v1",
        "status": "READY_FOR_EXPLICIT_OPT_IN" if ready else "BLOCKED",
        "run_id": run_id,
        "checked_at": datetime.now(UTC).isoformat(),
        "environment_file": env_file.relative_to(PROJECT_ROOT).as_posix(),
        "provider": provider_summary,
        "prompt_bundle": prompt_summary,
        "gates": {
            "configuration_valid": settings is not None and not any(
                item.startswith("runtime configuration") for item in errors
            ),
            "prompt_bundle_valid": prompt_summary["valid"],
            "provider_constructed": provider_summary["constructed"],
            "explicit_composition_required": True,
            "network_probe_performed": False,
            "external_call_authorized": False,
        },
        "blockers": errors,
        "safety": {
            "network_requests": 0,
            "external_llm_requests": 0,
            "database_reads": 0,
            "database_writes": 0,
            "outbox_claims": 0,
            "files_deleted": 0,
            "artifact_overwrites": 0,
        },
    }
    return report


def write_artifact(report: Mapping[str, Any]) -> Path:
    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required to write an evidence artifact")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "llm" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output_path = evidence_dir / "real-call-readiness.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(dict(report), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--run-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_id = validate_run_id(args.run_id) if args.run_id else None
        report = build_report(env_file=args.env_file, run_id=run_id)
        if run_id:
            output_path = write_artifact(report)
            report = {**report, "artifact_path": output_path.relative_to(PROJECT_ROOT).as_posix()}
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    return 0 if report["status"] == "READY_FOR_EXPLICIT_OPT_IN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
