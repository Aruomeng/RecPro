"""Safe, secret-free DeepSeek policy bindings for bounded G4 capabilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.app.config import AppSettings


EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_BASE_URL = "https://api.deepseek.com"
CAPABILITY = "intent.classify"
EXPLANATION_CAPABILITY = "explanation.render"
MAX_ATTEMPTS = 2
EXPLANATION_MAX_CONCURRENCY = 4


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_deepseek_intent_policy(env_file: Path) -> tuple[AppSettings, dict[str, Any]]:
    """Load local secrets but return only an auditable non-secret policy."""

    settings = AppSettings(_env_file=str(env_file.resolve(strict=True)))
    if settings.app_env != "demo":
        raise ValueError("DeepSeek G4 plan requires RECPRO_APP_ENV=demo")
    if not settings.g4_http_enabled or not settings.g4_llm_intent_enabled:
        raise ValueError("DeepSeek G4 plan requires both G4 HTTP and Intent LLM switches")
    if settings.llm_provider != "deepseek":
        raise ValueError("DeepSeek G4 plan requires RECPRO_LLM_PROVIDER=deepseek")
    if settings.llm_model != EXPECTED_MODEL:
        raise ValueError(f"DeepSeek G4 plan requires model {EXPECTED_MODEL}")
    if settings.llm_base_url != EXPECTED_BASE_URL:
        raise ValueError(f"DeepSeek G4 plan requires origin {EXPECTED_BASE_URL}")
    if settings.llm_api_key is None:
        raise ValueError("DeepSeek G4 plan requires a local API key")
    prompt_path = settings.prompt_bundle_path.resolve(strict=True)
    policy = {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "base_url_origin": settings.llm_base_url,
        "capability": CAPABILITY,
        "max_attempts": MAX_ATTEMPTS,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_output_tokens": settings.llm_max_output_tokens,
        "prompt_version": settings.prompt_bundle_version,
        "prompt_bundle_sha256": sha256_bytes(prompt_path.read_bytes()),
        "input_scope": "fixed_non_sensitive_input_text_only",
        "raw_response_persisted": False,
        "explanation_llm_enabled": False,
    }
    return settings, policy


def load_deepseek_explanation_policy(
    env_file: Path, *, max_items: int
) -> tuple[AppSettings, dict[str, Any]]:
    """Bind evidence-only Explanation calls without exposing the API key."""

    if isinstance(max_items, bool) or not 1 <= max_items <= 20:
        raise ValueError("DeepSeek Explanation max_items must be between 1 and 20")
    settings, _intent_policy = load_deepseek_intent_policy(env_file)
    if not settings.g4_llm_explanation_enabled:
        raise ValueError("DeepSeek G4 plan requires the Explanation LLM switch")
    prompt_path = settings.prompt_bundle_path.resolve(strict=True)
    policy = {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "base_url_origin": settings.llm_base_url,
        "capability": EXPLANATION_CAPABILITY,
        "max_items": max_items,
        "max_attempts_per_item": MAX_ATTEMPTS,
        "max_total_attempts": max_items * MAX_ATTEMPTS,
        "max_concurrency": EXPLANATION_MAX_CONCURRENCY,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_output_tokens": settings.llm_max_output_tokens,
        "prompt_version": settings.prompt_bundle_version,
        "prompt_bundle_sha256": sha256_bytes(prompt_path.read_bytes()),
        "input_scope": "ranked_factors_and_allowlisted_evidence_refs_only",
        "raw_response_persisted": False,
        "evidence_validation_required": True,
        "per_item_template_fallback": True,
        "intent_llm_required": True,
    }
    return settings, policy


def policy_hash(policy: dict[str, Any]) -> str:
    return sha256_bytes(canonical(policy))


__all__ = [
    "CAPABILITY",
    "EXPECTED_BASE_URL",
    "EXPECTED_MODEL",
    "EXPLANATION_CAPABILITY",
    "EXPLANATION_MAX_CONCURRENCY",
    "MAX_ATTEMPTS",
    "canonical",
    "load_deepseek_intent_policy",
    "load_deepseek_explanation_policy",
    "policy_hash",
    "sha256_bytes",
]
