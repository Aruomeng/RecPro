from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from backend.app.observability.adapters.config_bundle_readiness import (
    JsonConfigBundleReadinessProbe,
)
from backend.app.observability.domain import ComponentStatus
from backend.app.shared_kernel.contracts.errors import ErrorCode


ROOT = Path(__file__).resolve().parents[3]
BUNDLE_RAW = (ROOT / "contracts/config/examples/rec-1.0.0.json").read_bytes()
SCHEMA_RAW = (ROOT / "contracts/config/rec-config.schema.json").read_bytes()


@dataclass(frozen=True)
class MemoryPath:
    raw: bytes | None = None
    error: OSError | None = None

    def read_bytes(self) -> bytes:
        if self.error is not None:
            raise self.error
        assert self.raw is not None
        return self.raw


class ConfigBundleReadinessProbeTest(unittest.IsolatedAsyncioTestCase):
    def probe(
        self,
        raw: bytes,
        *,
        version: str = "rec-1.0.0",
        schema_raw: bytes = SCHEMA_RAW,
        expected_raw: bytes | None = None,
        expected_schema_sha256: str | None = None,
        path: MemoryPath | None = None,
    ):
        return JsonConfigBundleReadinessProbe(
            path=path or MemoryPath(raw),  # type: ignore[arg-type]
            schema_path=MemoryPath(schema_raw),  # type: ignore[arg-type]
            expected_sha256=hashlib.sha256(expected_raw or raw).hexdigest(),
            expected_schema_sha256=(
                expected_schema_sha256 or hashlib.sha256(schema_raw).hexdigest()
            ),
            expected_version=version,
        )

    async def test_valid_schema_version_and_hash_are_ready(self) -> None:
        result = await self.probe(BUNDLE_RAW).check()

        self.assertEqual(ComponentStatus.UP, result.status)
        self.assertEqual("rec-1.0.0", result.active_version)

    async def test_hash_mismatch_fails_closed(self) -> None:
        expected = b'{"config_bundle_version":"rec-1.0.0"}'
        observed = b'{"config_bundle_version":"rec-1.0.1"}'
        result = await self.probe(observed, expected_raw=expected).check()

        self.assertEqual(ComponentStatus.DOWN, result.status)
        self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, result.error_code)

    async def test_invalid_json_shape_or_version_fails_closed(self) -> None:
        samples = (
            b"[]",
            b'{"config_bundle_version":"different"}',
            b"not-json",
        )
        for raw in samples:
            with self.subTest(raw=raw):
                result = await self.probe(raw).check()
                self.assertEqual(ComponentStatus.DOWN, result.status)
                self.assertEqual(
                    ErrorCode.CONFIG_BUNDLE_INVALID.value, result.error_code
                )

    async def test_read_error_is_sanitized(self) -> None:
        result = await self.probe(
            BUNDLE_RAW,
            path=MemoryPath(error=OSError("private path")),
        ).check()

        self.assertEqual(ComponentStatus.DOWN, result.status)
        self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, result.error_code)

    async def test_invalid_schema_or_schema_incomplete_bundle_fails_closed(self) -> None:
        incomplete = b'{"config_bundle_version":"rec-1.0.0"}'
        invalid_schema = b'{"type": 17}'
        for label, probe in (
            ("incomplete bundle", self.probe(incomplete)),
            ("invalid schema", self.probe(BUNDLE_RAW, schema_raw=invalid_schema)),
        ):
            with self.subTest(case=label):
                result = await probe.check()
                self.assertEqual(ComponentStatus.DOWN, result.status)
                self.assertEqual(
                    ErrorCode.CONFIG_BUNDLE_INVALID.value,
                    result.error_code,
                )

    async def test_cross_field_semantic_violations_fail_closed(self) -> None:
        samples: list[tuple[str, dict[str, object]]] = []
        for label in ("weight sum", "hydration limit", "threshold order"):
            payload = deepcopy(json.loads(BUNDLE_RAW))
            if label == "weight sum":
                payload["ranking"]["book"]["profile_score"] = 0.5
            elif label == "hydration limit":
                payload["limits"]["hydration_candidate_limit"] = 1
            else:
                payload["policy"]["evidence_degraded_threshold"] = 0.9
                payload["policy"]["evidence_detailed_threshold"] = 0.3
            samples.append((label, payload))

        for label, payload in samples:
            with self.subTest(case=label):
                raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                result = await self.probe(raw).check()
                self.assertEqual(ComponentStatus.DOWN, result.status)
                self.assertEqual(
                    ErrorCode.CONFIG_BUNDLE_INVALID.value,
                    result.error_code,
                )

    async def test_non_finite_json_number_fails_closed(self) -> None:
        payload = deepcopy(json.loads(BUNDLE_RAW))
        payload["probe"]["metadata_min"] = float("nan")
        raw = json.dumps(payload, allow_nan=True).encode("utf-8")

        result = await self.probe(raw).check()

        self.assertEqual(ComponentStatus.DOWN, result.status)
        self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, result.error_code)

    async def test_unresolved_schema_reference_is_sanitized(self) -> None:
        schema = deepcopy(json.loads(SCHEMA_RAW))
        schema["properties"]["probe"] = {"$ref": "#/$defs/missing"}
        schema_raw = json.dumps(schema, separators=(",", ":")).encode("utf-8")

        result = await self.probe(BUNDLE_RAW, schema_raw=schema_raw).check()

        self.assertEqual(ComponentStatus.DOWN, result.status)
        self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, result.error_code)

    async def test_schema_hash_mismatch_fails_closed(self) -> None:
        result = await self.probe(
            BUNDLE_RAW,
            expected_schema_sha256="0" * 64,
        ).check()

        self.assertEqual(ComponentStatus.DOWN, result.status)
        self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, result.error_code)
