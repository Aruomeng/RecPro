#!/usr/bin/env python3
"""Make one explicitly confirmed, non-sensitive DeepSeek fixture call.

The command is intentionally narrow: it exercises one selected capability
with a fixed research fixture.  It never connects to a database, starts an
application, claims Outbox rows, sends user history, or stores the raw model
response.  A new run id is required so evidence is append-only.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Sequence

from backend.app.config import AppSettings
from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from backend.app.llm.factory import build_llm_provider
from scripts.verify_llm_real_call_readiness import resolve_env_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
INTENT_FIXTURE_ID = "intent-classify-research-fixture-v1"
INTENT_FIXTURE_TEXT = "请推荐与多智能体系统和智慧图书馆相关的图书"
EXPLANATION_FIXTURE_ID = "explanation-render-evidence-fixture-v1"
EXPLANATION_FIXTURE = {
    "factors": ["召回通道：MYSQL+VECTOR", "排序位置：1"],
    "evidence_refs": ["resource:book:6452"],
}
ALLOWED_INTENTS = {
    "BOOK_RECOMMENDATION",
    "PAPER_RECOMMENDATION",
    "GENERAL_RECOMMENDATION",
}


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def _write_report(run_id: str, report: dict[str, Any]) -> Path:
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "llm" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output_path = evidence_dir / "real-call.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return output_path


def _fixture_metadata(capability: str) -> dict[str, Any]:
    if capability == "intent":
        serialized = INTENT_FIXTURE_TEXT
        fixture_id = INTENT_FIXTURE_ID
    elif capability == "explanation":
        serialized = json.dumps(EXPLANATION_FIXTURE, ensure_ascii=False, sort_keys=True)
        fixture_id = EXPLANATION_FIXTURE_ID
    else:
        raise ValueError("capability must be intent or explanation")
    return {
        "fixture_id": fixture_id,
        "capability": capability,
        "input_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "input_chars": len(serialized),
        "sensitive_user_data": False,
    }


async def execute(
    *, env_file: Path, run_id: str, confirmation: str, capability: str = "intent"
) -> dict[str, Any]:
    if confirmation != "YES_REAL_EXTERNAL_LLM":
        raise ValueError("an exact confirmation is required for the external call")
    run_id = validate_run_id(run_id)
    fixture_metadata = _fixture_metadata(capability)
    env_file = resolve_env_file(env_file)
    settings = AppSettings(_env_file=str(env_file))
    if settings.app_env == "production":
        raise ValueError("fixture call cannot run with production app_env")
    if settings.llm_provider != "deepseek":
        raise ValueError("fixture call requires RECPRO_LLM_PROVIDER=deepseek")

    # Construction is still explicit and local; the network is touched only by
    # the single capability invocation below.
    provider = build_llm_provider(settings)
    if not isinstance(provider, DeepSeekLLMProvider):
        raise ValueError("configured provider was not DeepSeekLLMProvider")

    started = time.monotonic()
    try:
        if capability == "intent":
            result = await provider.classify_intent(INTENT_FIXTURE_TEXT)
            intent = result.payload.get("intent")
            if intent not in ALLOWED_INTENTS:
                raise ValueError("provider returned an unsupported intent")
            validated_result: dict[str, Any] = {"intent": intent}
        else:
            result = await provider.render_explanation(EXPLANATION_FIXTURE)
            rendered_text = result.payload.get("text")
            evidence_refs = result.payload.get("evidence_refs")
            allowed_refs = EXPLANATION_FIXTURE["evidence_refs"]
            if (
                not isinstance(rendered_text, str)
                or not rendered_text.strip()
                or len(rendered_text.strip()) > 240
                or not isinstance(evidence_refs, list)
                or not evidence_refs
                or any(
                    not isinstance(reference, str)
                    or reference not in allowed_refs
                    or f"[{reference}]" not in rendered_text
                    for reference in evidence_refs
                )
            ):
                raise ValueError("provider returned an invalid evidence-constrained explanation")
            # Do not retain generated prose: only record its validated shape.
            validated_result = {
                "text_chars": len(rendered_text.strip()),
                "evidence_refs": evidence_refs,
                "all_evidence_markers_present": True,
            }
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        attempts = int(result.attempts)
        report: dict[str, Any] = {
            "schema_version": "llm-real-call-evidence-v1",
            "status": "PASS",
            "run_id": run_id,
            "checked_at": datetime.now(UTC).isoformat(),
            "fixture": fixture_metadata,
            "provider": {
                "provider": result.provider,
                "model": result.model,
                "base_url_origin": settings.llm_base_url,
                "prompt_id": result.prompt_id,
                "prompt_version": result.prompt_version,
                "prompt_sha256": result.prompt_sha256,
                "request_id": result.request_id,
                "attempts": attempts,
                "latency_ms": elapsed_ms,
            },
            "result": validated_result,
            "safety": {
                "external_llm_requests": attempts,
                "network_requests": attempts,
                "database_reads": 0,
                "database_writes": 0,
                "neo4j_reads": 0,
                "neo4j_writes": 0,
                "chroma_reads": 0,
                "chroma_writes": 0,
                "outbox_claims": 0,
                "files_deleted": 0,
                "database_physical_deletions": 0,
                "artifact_overwrites": 0,
            },
        }
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        report = {
            "schema_version": "llm-real-call-evidence-v1",
            "status": "FAIL",
            "run_id": run_id,
            "checked_at": datetime.now(UTC).isoformat(),
            "fixture": fixture_metadata,
            "provider": {
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "base_url_origin": settings.llm_base_url,
                "latency_ms": elapsed_ms,
            },
            "error": {"type": type(exc).__name__},
            "safety": {
                "external_llm_requests": 1,
                "network_requests": 1,
                "database_reads": 0,
                "database_writes": 0,
                "neo4j_reads": 0,
                "neo4j_writes": 0,
                "chroma_reads": 0,
                "chroma_writes": 0,
                "outbox_claims": 0,
                "files_deleted": 0,
                "database_physical_deletions": 0,
                "artifact_overwrites": 0,
            },
        }
    output_path = _write_report(run_id, report)
    report["artifact_path"] = output_path.relative_to(PROJECT_ROOT).as_posix()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--capability", choices=("intent", "explanation"), default="intent")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(
            execute(
                env_file=args.env_file,
                run_id=args.run_id,
                confirmation=args.confirm,
                capability=args.capability,
            )
        )
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
