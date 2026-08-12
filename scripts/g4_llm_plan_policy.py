"""Safe, secret-free DeepSeek policy binding for one G4 Intent request."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.app.config import AppSettings


EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_BASE_URL = "https://api.deepseek.com"
CAPABILITY = "intent.classify"
MAX_ATTEMPTS = 2


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


def policy_hash(policy: dict[str, Any]) -> str:
    return sha256_bytes(canonical(policy))


__all__ = [
    "CAPABILITY",
    "EXPECTED_BASE_URL",
    "EXPECTED_MODEL",
    "MAX_ATTEMPTS",
    "canonical",
    "load_deepseek_intent_policy",
    "policy_hash",
    "sha256_bytes",
]
