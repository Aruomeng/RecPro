"""LLM abstraction with deterministic default and opt-in providers."""

from .adapters.deepseek import DeepSeekLLMProvider
from .adapters.mock import MockLLMProvider
from .factory import build_llm_provider
from .ports.public import LLMResult, TextCapabilityProvider
from .prompts import PromptBundle, PromptBundleError, load_prompt_bundle

__all__ = [
    "DeepSeekLLMProvider",
    "LLMResult",
    "MockLLMProvider",
    "TextCapabilityProvider",
    "PromptBundle",
    "PromptBundleError",
    "build_llm_provider",
    "load_prompt_bundle",
]
