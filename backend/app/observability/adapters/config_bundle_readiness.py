"""Read-only integrity probe for the frozen recommendation config Bundle."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from backend.app.shared_kernel.config_bundle import (
    load_strict_json,
    validate_config_bundle_semantics,
)
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.shared_kernel.contracts.errors import ErrorCode


@dataclass(frozen=True, slots=True)
class JsonConfigBundleReadinessProbe:
    path: Path
    schema_path: Path
    expected_sha256: str
    expected_schema_sha256: str
    expected_version: str

    async def check(self) -> ComponentReadiness:
        return await asyncio.to_thread(self._check_read_only)

    def _check_read_only(self) -> ComponentReadiness:
        try:
            raw = self.path.read_bytes()
            actual_sha256 = hashlib.sha256(raw).hexdigest()
            if actual_sha256 != self.expected_sha256:
                return self._invalid()
            payload: Any = load_strict_json(raw)
            if not isinstance(payload, dict):
                return self._invalid()
            if payload.get("config_bundle_version") != self.expected_version:
                return self._invalid()
            schema_raw = self.schema_path.read_bytes()
            if hashlib.sha256(schema_raw).hexdigest() != self.expected_schema_sha256:
                return self._invalid()
            schema: Any = load_strict_json(schema_raw)
            if not isinstance(schema, dict):
                return self._invalid()
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(payload)
            if validate_config_bundle_semantics(payload):
                return self._invalid()
            return ComponentReadiness(
                status=ComponentStatus.UP,
                required=True,
                active_version=self.expected_version,
            )
        except Exception:
            return self._invalid()

    @staticmethod
    def _invalid() -> ComponentReadiness:
        return ComponentReadiness(
            status=ComponentStatus.DOWN,
            required=True,
            error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
        )
