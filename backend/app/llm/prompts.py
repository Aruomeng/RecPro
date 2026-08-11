"""Versioned prompt bundle loading and safe rendering.

Prompt text is configuration, not application logic.  This module gives the
LLM adapters a small immutable boundary with three guarantees:

* the bundle and every task are validated against a committed JSON Schema;
* templates can interpolate only their declared variables and are bounded;
* output schemas and allowed fields are checked before an adapter returns a
  payload to an Agent.

The loader is local-only.  It never fetches a prompt or a schema from the
network, and it never exposes the rendered user text in audit metadata.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from backend.app.shared_kernel.config_bundle import load_strict_json


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPT_SCHEMA_PATH = PROJECT_ROOT / "contracts/prompts/prompt-bundle.schema.json"
DEFAULT_PROMPT_BUNDLE_PATH = PROJECT_ROOT / "contracts/prompts/rec-prompts-v1.0.0.json"
_PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PromptBundleError(ValueError):
    """Raised when a prompt bundle or rendered task is unsafe or invalid."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _path_inside_project(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        if ".." in candidate.parts:
            raise PromptBundleError("prompt bundle path must not contain '..'")
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise PromptBundleError("prompt bundle path must be contained in the project") from exc
    return resolved


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (bool, int, float, list, dict)):
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise PromptBundleError("prompt variable is not JSON-serializable") from exc
    raise PromptBundleError("prompt variable must be text or JSON data")


@dataclass(frozen=True, slots=True)
class PromptTask:
    """One capability-specific prompt and its output boundary."""

    prompt_id: str
    agent_name: str
    capability: str
    version: str
    system_template: str
    user_template: str
    variables: tuple[str, ...]
    output_schema: Mapping[str, Any]
    allowed_output_fields: tuple[str, ...]
    evidence_only: bool
    max_input_chars: int
    max_output_tokens: int
    fallback_strategy: str
    template_sha256: str

    def render(self, values: Mapping[str, Any], *, bundle_max_context_chars: int) -> "RenderedPrompt":
        expected = set(self.variables)
        actual = set(values)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            raise PromptBundleError(
                f"prompt {self.prompt_id} is missing variables: {','.join(missing)}"
            )
        if extra:
            raise PromptBundleError(
                f"prompt {self.prompt_id} received undeclared variables: {','.join(extra)}"
            )

        rendered_system = self.system_template
        rendered_user = self.user_template
        for name in self.variables:
            token = "{{" + name + "}}"
            replacement = _render_value(values[name])
            rendered_system = rendered_system.replace(token, replacement)
            rendered_user = rendered_user.replace(token, replacement)

        unresolved = sorted(set(_PLACEHOLDER.findall(rendered_system + rendered_user)))
        if unresolved:
            raise PromptBundleError(
                f"prompt {self.prompt_id} contains unresolved variables: {','.join(unresolved)}"
            )
        context_chars = len(rendered_system) + len(rendered_user)
        if context_chars > min(self.max_input_chars, bundle_max_context_chars):
            raise PromptBundleError(
                f"prompt {self.prompt_id} exceeds its bounded context budget"
            )
        return RenderedPrompt(
            prompt_id=self.prompt_id,
            version=self.version,
            system=rendered_system,
            user=rendered_user,
            template_sha256=self.template_sha256,
        )

    def validate_output(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise PromptBundleError(f"prompt {self.prompt_id} output must be an object")
        fields = set(payload)
        allowed = set(self.allowed_output_fields)
        unknown = sorted(fields - allowed)
        if unknown:
            raise PromptBundleError(
                f"prompt {self.prompt_id} output contains forbidden fields: {','.join(unknown)}"
            )
        validator = Draft202012Validator(self.output_schema, format_checker=FormatChecker())
        errors = sorted(
            validator.iter_errors(dict(payload)),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if errors:
            location = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
            raise PromptBundleError(
                f"prompt {self.prompt_id} output invalid at {location}: {errors[0].message}"
            )


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    prompt_id: str
    version: str
    system: str
    user: str
    template_sha256: str


@dataclass(frozen=True, slots=True)
class PromptBundle:
    """Immutable prompt registry loaded from one reviewed local JSON file."""

    schema_version: str
    bundle_version: str
    locale: str
    max_context_chars: int
    tasks: Mapping[str, PromptTask]
    source_path: str
    source_sha256: str

    @classmethod
    def from_document(
        cls,
        document: Mapping[str, Any],
        *,
        source_path: str = "<memory>",
        source_sha256: str = "",
    ) -> "PromptBundle":
        if not isinstance(document, Mapping):
            raise PromptBundleError("prompt bundle root must be an object")
        schema_errors = sorted(
            Draft202012Validator(_load_prompt_schema()).iter_errors(document),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if schema_errors:
            location = ".".join(str(part) for part in schema_errors[0].absolute_path) or "<root>"
            raise PromptBundleError(
                f"prompt bundle invalid at {location}: {schema_errors[0].message}"
            )

        security = document["security"]
        if security["allowed_tools"]:
            raise PromptBundleError("prompt bundle must not grant tools")
        task_map: dict[str, PromptTask] = {}
        capabilities: set[str] = set()
        for raw_task in document["tasks"]:
            prompt_id = raw_task["prompt_id"]
            if prompt_id in task_map:
                raise PromptBundleError(f"duplicate prompt_id: {prompt_id}")
            capability = raw_task["capability"]
            if capability in capabilities:
                raise PromptBundleError(f"duplicate capability: {capability}")
            capabilities.add(capability)
            variables = tuple(raw_task["variables"])
            placeholders = set(
                _PLACEHOLDER.findall(raw_task["system_template"] + raw_task["user_template"])
            )
            if placeholders != set(variables):
                missing = sorted(set(variables) - placeholders)
                extra = sorted(placeholders - set(variables))
                detail = []
                if missing:
                    detail.append("unused=" + ",".join(missing))
                if extra:
                    detail.append("undeclared=" + ",".join(extra))
                raise PromptBundleError(
                    f"prompt {prompt_id} placeholder contract mismatch ({'; '.join(detail)})"
                )
            output_schema = raw_task["output_schema"]
            try:
                Draft202012Validator.check_schema(output_schema)
            except Exception as exc:  # jsonschema exposes several SchemaError subclasses
                raise PromptBundleError(f"prompt {prompt_id} has an invalid output schema") from exc
            properties = output_schema.get("properties", {})
            if not isinstance(properties, Mapping):
                raise PromptBundleError(f"prompt {prompt_id} output schema properties must be an object")
            allowed_fields = tuple(raw_task["allowed_output_fields"])
            if set(properties) != set(allowed_fields):
                raise PromptBundleError(
                    f"prompt {prompt_id} allowed_output_fields do not match output schema"
                )
            template_hash = hashlib.sha256(_canonical_json(raw_task)).hexdigest()
            task_map[prompt_id] = PromptTask(
                prompt_id=prompt_id,
                agent_name=raw_task["agent_name"],
                capability=capability,
                version=raw_task["version"],
                system_template=raw_task["system_template"],
                user_template=raw_task["user_template"],
                variables=variables,
                output_schema=MappingProxyType(dict(output_schema)),
                allowed_output_fields=allowed_fields,
                evidence_only=raw_task["evidence_only"],
                max_input_chars=raw_task["max_input_chars"],
                max_output_tokens=raw_task["max_output_tokens"],
                fallback_strategy=raw_task["fallback_strategy"],
                template_sha256=template_hash,
            )
        return cls(
            schema_version=document["schema_version"],
            bundle_version=document["bundle_version"],
            locale=document["locale"],
            max_context_chars=security["max_context_chars"],
            tasks=MappingProxyType(task_map),
            source_path=source_path,
            source_sha256=source_sha256,
        )

    def task(self, prompt_id: str) -> PromptTask:
        try:
            return self.tasks[prompt_id]
        except KeyError as exc:
            raise PromptBundleError(f"unknown prompt_id: {prompt_id}") from exc

    def render(self, prompt_id: str, values: Mapping[str, Any]) -> RenderedPrompt:
        return self.task(prompt_id).render(
            values,
            bundle_max_context_chars=self.max_context_chars,
        )


@lru_cache(maxsize=4)
def _load_prompt_bundle_cached(
    path_text: str,
    expected_sha256: str | None,
    expected_version: str | None,
) -> PromptBundle:
    path = Path(path_text)
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise PromptBundleError("prompt bundle could not be read") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        if not _SHA256.fullmatch(expected_sha256):
            raise PromptBundleError("expected prompt bundle SHA-256 is malformed")
        if actual_sha256 != expected_sha256:
            raise PromptBundleError("prompt bundle SHA-256 does not match configuration")
    try:
        document = load_strict_json(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PromptBundleError("prompt bundle is not strict JSON") from exc
    bundle = PromptBundle.from_document(
        document,
        source_path=path.relative_to(PROJECT_ROOT).as_posix(),
        source_sha256=actual_sha256,
    )
    if expected_version is not None and bundle.bundle_version != expected_version:
        raise PromptBundleError("prompt bundle version does not match configuration")
    return bundle


def load_prompt_bundle(
    path: Path | str = DEFAULT_PROMPT_BUNDLE_PATH,
    *,
    expected_sha256: str | None = None,
    expected_version: str | None = None,
) -> PromptBundle:
    """Load and validate one local prompt bundle, with no network or writes."""

    resolved = _path_inside_project(Path(path))
    return _load_prompt_bundle_cached(str(resolved), expected_sha256, expected_version)


def load_default_prompt_bundle() -> PromptBundle:
    return load_prompt_bundle(DEFAULT_PROMPT_BUNDLE_PATH)

@lru_cache(maxsize=1)
def _load_prompt_schema() -> Mapping[str, Any]:
    try:
        schema = load_strict_json(PROMPT_SCHEMA_PATH.read_bytes())
        Draft202012Validator.check_schema(schema)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PromptBundleError("prompt bundle schema is unavailable or invalid") from exc
    return schema


__all__ = [
    "DEFAULT_PROMPT_BUNDLE_PATH",
    "PromptBundle",
    "PromptBundleError",
    "PromptTask",
    "RenderedPrompt",
    "load_default_prompt_bundle",
    "load_prompt_bundle",
]
