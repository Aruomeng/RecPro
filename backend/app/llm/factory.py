"""Composition boundary for selecting the configured text capability provider."""

from __future__ import annotations

from backend.app.config import AppSettings
from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from backend.app.llm.adapters.mock import MockLLMProvider
from backend.app.llm.ports.public import TextCapabilityProvider


def build_llm_provider(settings: AppSettings) -> TextCapabilityProvider:
    """Build a provider without performing a network call.

    ``AppSettings`` has already enforced the key and HTTPS gates.  The returned
    provider is still not called until an explicit recommendation composition
    invokes one of its async capabilities.
    """

    if settings.llm_provider == "mock":
        return MockLLMProvider()
    if settings.llm_api_key is None:
        raise ValueError("DeepSeek provider requires a validated API key")
    return DeepSeekLLMProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )


__all__ = ["build_llm_provider"]
