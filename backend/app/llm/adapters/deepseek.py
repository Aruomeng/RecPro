"""Opt-in DeepSeek adapter over the OpenAI-compatible chat endpoint.

The adapter is intentionally independent from recommendation agents and
databases.  It is never constructed by the default application composition;
the caller must pass an explicit API key and provider configuration.  Errors
are raised without including the key or response body so the existing agent
fallback path can remain evidence-constrained.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import SecretStr

from backend.app.llm.ports.public import LLMResult


@dataclass(frozen=True, slots=True)
class DeepSeekLLMProvider:
    """Explicit DeepSeek provider; construction fails closed without a key."""

    api_key: SecretStr
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout_seconds: float = 20.0
    max_output_tokens: int = 512
    prompt_version: str = "deepseek-json-v1"

    def __post_init__(self) -> None:
        if not self.api_key.get_secret_value().strip():
            raise ValueError("DeepSeek API key is required")
        parsed = urlsplit(self.base_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError("DeepSeek base URL must be an HTTPS origin")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("DeepSeek timeout must be between 0 and 120 seconds")
        if not 1 <= self.max_output_tokens <= 8192:
            raise ValueError("DeepSeek max output tokens must be between 1 and 8192")

    async def classify_intent(self, text: str) -> LLMResult:
        payload = await self._complete(
            system=(
                "你是智慧图书馆意图分类器。只输出 JSON："
                "{\"intent\":\"BOOK_RECOMMENDATION|PAPER_RECOMMENDATION|GENERAL_RECOMMENDATION\"}。"
            ),
            user=text,
        )
        intent = payload.get("intent")
        if intent not in {"BOOK_RECOMMENDATION", "PAPER_RECOMMENDATION", "GENERAL_RECOMMENDATION"}:
            raise ValueError("DeepSeek returned an unsupported intent")
        return self._result({"intent": intent})

    async def parse_feedback_text(self, text: str) -> LLMResult:
        payload = await self._complete(
            system=(
                "你是图书推荐反馈分类器。只输出 JSON："
                "{\"reason_code\":\"TOO_BASIC|TOO_ADVANCED|ALREADY_READ|REPEATED|OTHER\"}。"
            ),
            user=text,
        )
        reason_code = payload.get("reason_code")
        allowed = {"TOO_BASIC", "TOO_ADVANCED", "ALREADY_READ", "REPEATED", "OTHER"}
        if reason_code not in allowed:
            raise ValueError("DeepSeek returned an unsupported feedback code")
        return self._result({"reason_code": reason_code})

    async def render_explanation(self, evidence: Mapping[str, Any]) -> LLMResult:
        safe_evidence = {"factors": [str(item) for item in evidence.get("factors", ())][:32]}
        payload = await self._complete(
            system=(
                "你是可解释推荐文案生成器。只能使用输入证据，不得编造事实。"
                "只输出 JSON：{\"text\":\"简短中文解释\"}。"
            ),
            user=json.dumps(safe_evidence, ensure_ascii=False),
        )
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("DeepSeek returned an empty explanation")
        return self._result({"text": text.strip(), "evidence_limited": not bool(safe_evidence["factors"])})

    async def render_group_summary(self, topic_name: str) -> LLMResult:
        payload = await self._complete(
            system="你是智慧图书馆主题摘要生成器。只输出 JSON：{\"text\":\"简短中文摘要\"}。",
            user=topic_name.strip()[:256],
        )
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("DeepSeek returned an empty group summary")
        return self._result({"text": text.strip()})

    async def _complete(self, *, system: str, user: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._complete_sync, system=system, user=user)

    def _complete_sync(self, *, system: str, user: str) -> dict[str, Any]:
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12000]},
            ],
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
        }
        request = Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.api_key.get_secret_value(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024)
                document = json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"DeepSeek request failed with status {exc.code}") from exc
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"DeepSeek request failed: {type(exc).__name__}") from exc
        try:
            content = document["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("DeepSeek response did not contain chat content") from exc
        if not isinstance(content, str):
            raise ValueError("DeepSeek chat content must be text")
        content = content.strip()
        if content.startswith("```"):
            content = content.removeprefix("```").removeprefix("json").removesuffix("```").strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("DeepSeek chat content is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("DeepSeek chat content must be a JSON object")
        return parsed

    def _result(self, payload: Mapping[str, Any]) -> LLMResult:
        return LLMResult(
            provider="deepseek",
            model=self.model,
            prompt_version=self.prompt_version,
            payload=dict(payload),
        )


__all__ = ["DeepSeekLLMProvider"]
