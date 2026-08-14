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
from http.client import IncompleteRead
import json
from typing import Any, Callable, Mapping
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import SecretStr

from backend.app.llm.ports.public import LLMResult
from backend.app.llm.prompts import (
    PromptBundle,
    PromptBundleError,
    load_default_prompt_bundle,
)


class DeepSeekRequestError(RuntimeError):
    """A provider request failed; ``retryable`` is deliberately explicit."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class DeepSeekPayloadError(ValueError):
    """The remote response was not valid JSON or the expected object shape."""

    retryable = True


@dataclass(frozen=True, slots=True)
class DeepSeekLLMProvider:
    """Explicit DeepSeek provider; construction fails closed without a key."""

    api_key: SecretStr
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    timeout_seconds: float = 20.0
    max_output_tokens: int = 512
    prompt_version: str | None = None
    max_attempts: int = 2
    prompt_bundle: PromptBundle | None = None

    def __post_init__(self) -> None:
        if not self.api_key.get_secret_value().strip():
            raise ValueError("DeepSeek API key is required")
        parsed = urlsplit(self.base_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError("DeepSeek base URL must be an HTTPS origin")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= 120
        ):
            raise ValueError("DeepSeek timeout must be between 0 and 120 seconds")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 1 <= self.max_output_tokens <= 8192
        ):
            raise ValueError("DeepSeek max output tokens must be between 1 and 8192")
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= 2
        ):
            raise ValueError("DeepSeek max attempts must be between 1 and 2")
        bundle = self.prompt_bundle or load_default_prompt_bundle()
        object.__setattr__(self, "prompt_bundle", bundle)
        if self.prompt_version is None:
            object.__setattr__(self, "prompt_version", bundle.bundle_version)
        elif not isinstance(self.prompt_version, str) or not self.prompt_version.strip():
            raise ValueError("DeepSeek prompt version must not be blank")

    async def classify_intent(self, text: str) -> LLMResult:
        payload, request_id, attempts = await self._run_task(
            "intent.classify",
            {
                "allowed_intents": [
                    "BOOK_RECOMMENDATION",
                    "PAPER_RECOMMENDATION",
                    "GENERAL_RECOMMENDATION",
                ],
                "input_text": text.strip()[:4000],
                "resource_types": [],
            },
        )
        intent = payload.get("intent")
        if intent not in {"BOOK_RECOMMENDATION", "PAPER_RECOMMENDATION", "GENERAL_RECOMMENDATION"}:
            raise ValueError("DeepSeek returned an unsupported intent")
        return self._result("intent.classify", {"intent": intent}, request_id, attempts)

    async def parse_feedback_text(self, text: str) -> LLMResult:
        payload, request_id, attempts = await self._run_task(
            "feedback.parse",
            {
                "allowed_reason_codes": [
                    "TOO_BASIC",
                    "TOO_ADVANCED",
                    "ALREADY_READ",
                    "REPEATED",
                    "OTHER",
                ],
                "input_text": text.strip()[:4000],
            },
        )
        reason_code = payload.get("reason_code")
        allowed = {"TOO_BASIC", "TOO_ADVANCED", "ALREADY_READ", "REPEATED", "OTHER"}
        if reason_code not in allowed:
            raise ValueError("DeepSeek returned an unsupported feedback code")
        return self._result("feedback.parse", {"reason_code": reason_code}, request_id, attempts)

    async def render_explanation(self, evidence: Mapping[str, Any]) -> LLMResult:
        factors = [str(item).strip() for item in evidence.get("factors", ()) if str(item).strip()][:32]
        evidence_refs = [
            str(item).strip()
            for item in evidence.get("evidence_refs", ())
            if str(item).strip()
        ][:32]
        safe_evidence = {"factors": factors, "evidence_refs": evidence_refs}
        payload, request_id, attempts = await self._run_task(
            "explanation.render",
            {"evidence_json": json.dumps(safe_evidence, ensure_ascii=False, sort_keys=True)},
            validate_payload=lambda candidate: self._validate_explanation_payload(
                candidate, evidence_refs
            ),
        )
        text, output_refs = self._validate_explanation_payload(payload, evidence_refs)
        return self._result(
            "explanation.render",
            {
                "text": text.strip(),
                "evidence_refs": list(output_refs),
                "evidence_limited": not bool(output_refs),
            },
            request_id,
            attempts,
        )

    @staticmethod
    def _validate_explanation_payload(
        payload: Mapping[str, Any], evidence_refs: list[str]
    ) -> tuple[str, list[str]]:
        """Validate semantic evidence bounds in the same retry budget as JSON shape."""

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("DeepSeek returned an empty explanation")
        output_refs = payload.get("evidence_refs", [])
        if not isinstance(output_refs, list) or any(
            not isinstance(item, str) or item not in evidence_refs for item in output_refs
        ):
            raise ValueError("DeepSeek returned an evidence reference outside the allowlist")
        if evidence_refs and not output_refs:
            raise ValueError("DeepSeek omitted required evidence references")
        if any(f"[{reference}]" not in text for reference in output_refs):
            raise ValueError("DeepSeek explanation omitted an evidence marker")
        return text.strip(), list(output_refs)

    async def render_group_summary(self, topic_name: str) -> LLMResult:
        payload, request_id, attempts = await self._run_task(
            "group_summary.render", {"topic_name": topic_name.strip()[:256]}
        )
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("DeepSeek returned an empty group summary")
        return self._result("group_summary.render", {"text": text.strip()}, request_id, attempts)

    async def _run_task(
        self,
        prompt_id: str,
        variables: Mapping[str, Any],
        validate_payload: Callable[[Mapping[str, Any]], object] | None = None,
    ) -> tuple[dict[str, Any], str, int]:
        request_id = str(uuid4())
        task = self.prompt_bundle.task(prompt_id)  # type: ignore[union-attr]
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                payload = await self._complete(prompt_id=prompt_id, variables=variables)
                if not isinstance(payload, Mapping):
                    raise DeepSeekPayloadError("DeepSeek response must be a JSON object")
                task.validate_output(payload)
                if validate_payload is not None:
                    validate_payload(payload)
                return dict(payload), request_id, attempt
            except asyncio.CancelledError:
                raise
            except (PromptBundleError, DeepSeekPayloadError, ValueError, RuntimeError, TimeoutError) as exc:
                last_error = exc
                retryable = getattr(exc, "retryable", True)
                if attempt >= self.max_attempts or not retryable:
                    raise
        raise RuntimeError("DeepSeek request exhausted its bounded retry budget") from last_error

    async def _complete(
        self,
        *,
        prompt_id: str,
        variables: Mapping[str, Any],
    ) -> dict[str, Any]:
        rendered = self.prompt_bundle.render(prompt_id, variables)  # type: ignore[union-attr]
        return await asyncio.to_thread(
            self._complete_sync,
            system=rendered.system,
            user=rendered.user,
            max_output_tokens=min(
                self.max_output_tokens,
                self.prompt_bundle.task(prompt_id).max_output_tokens,  # type: ignore[union-attr]
            ),
        )

    def _complete_sync(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12000]},
            ],
            "temperature": 0,
            "max_tokens": max_output_tokens or self.max_output_tokens,
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
            retryable = exc.code in {408, 409, 425, 429} or 500 <= exc.code <= 599
            raise DeepSeekRequestError(
                f"DeepSeek request failed with status {exc.code}",
                retryable=retryable,
            ) from exc
        except (
            URLError,
            TimeoutError,
            OSError,
            IncompleteRead,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise DeepSeekRequestError(
                f"DeepSeek request failed: {type(exc).__name__}",
                retryable=True,
            ) from exc
        try:
            content = document["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekPayloadError("DeepSeek response did not contain chat content") from exc
        if not isinstance(content, str):
            raise DeepSeekPayloadError("DeepSeek chat content must be text")
        content = content.strip()
        if content.startswith("```"):
            content = content.removeprefix("```").removeprefix("json").removesuffix("```").strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise DeepSeekPayloadError("DeepSeek chat content is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise DeepSeekPayloadError("DeepSeek chat content must be a JSON object")
        return parsed

    def _result(
        self,
        prompt_id: str,
        payload: Mapping[str, Any],
        request_id: str,
        attempts: int,
    ) -> LLMResult:
        task = self.prompt_bundle.task(prompt_id)  # type: ignore[union-attr]
        return LLMResult(
            provider="deepseek",
            model=self.model,
            prompt_version=self.prompt_version or task.version,
            payload=dict(payload),
            prompt_id=prompt_id,
            prompt_sha256=task.template_sha256,
            request_id=request_id,
            attempts=attempts,
        )


__all__ = ["DeepSeekLLMProvider", "DeepSeekPayloadError", "DeepSeekRequestError"]
