"""Public readiness use case used by the HTTP adapter."""

from __future__ import annotations

from backend.app.observability.domain import (
    ComponentReadiness,
    ComponentStatus,
    ReadinessAssessment,
    ServiceReadinessStatus,
)
from backend.app.observability.ports import ReadinessProbe
from backend.app.shared_kernel.contracts.errors import ErrorCode


class ReadinessService:
    """Aggregate dependency health while reporting G1 capability truthfully."""

    def __init__(
        self,
        *,
        mysql_probe: ReadinessProbe,
        config_bundle_probe: ReadinessProbe,
        config_bundle_version: str,
        configuration_valid: bool,
        configuration_error_code: str | None = None,
    ) -> None:
        self._mysql_probe = mysql_probe
        self._config_bundle_probe = config_bundle_probe
        self._config_bundle_version = config_bundle_version
        self._configuration_valid = configuration_valid
        self._configuration_error_code = configuration_error_code

    async def evaluate(self) -> ReadinessAssessment:
        components = self._g1_static_components()
        if not self._configuration_valid:
            components["config_bundle"] = ComponentReadiness(
                status=ComponentStatus.DOWN,
                required=True,
                error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
            )
            components["mysql"] = ComponentReadiness(
                status=ComponentStatus.UNKNOWN,
                required=True,
                error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
            )
            return ReadinessAssessment(
                status=ServiceReadinessStatus.NOT_READY,
                can_recommend=False,
                components=components,
                config_bundle_version=self._config_bundle_version,
                failure_error_code=(
                    self._configuration_error_code
                    or ErrorCode.CONFIG_BUNDLE_INVALID.value
                ),
            )

        try:
            config_bundle = await self._config_bundle_probe.check()
        except Exception:
            config_bundle = ComponentReadiness(
                status=ComponentStatus.DOWN,
                required=True,
                error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
            )
        components["config_bundle"] = config_bundle
        if config_bundle.status is not ComponentStatus.UP:
            components["mysql"] = ComponentReadiness(
                status=ComponentStatus.UNKNOWN,
                required=True,
                error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
            )
            return ReadinessAssessment(
                status=ServiceReadinessStatus.NOT_READY,
                can_recommend=False,
                components=components,
                config_bundle_version=self._config_bundle_version,
                failure_error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
            )

        try:
            mysql = await self._mysql_probe.check()
        except Exception:
            mysql = ComponentReadiness(
                status=ComponentStatus.DOWN,
                required=True,
                error_code=ErrorCode.CORE_STORAGE_UNAVAILABLE.value,
            )
        components["mysql"] = mysql
        if mysql.status is not ComponentStatus.UP:
            return ReadinessAssessment(
                status=ServiceReadinessStatus.NOT_READY,
                can_recommend=False,
                components=components,
                config_bundle_version=self._config_bundle_version,
                failure_error_code=(
                    mysql.error_code or ErrorCode.CORE_STORAGE_UNAVAILABLE.value
                ),
            )

        return ReadinessAssessment(
            status=ServiceReadinessStatus.DEGRADED,
            can_recommend=False,
            components=components,
            config_bundle_version=self._config_bundle_version,
        )

    @staticmethod
    def _g1_static_components() -> dict[str, ComponentReadiness]:
        return {
            "chroma": ComponentReadiness(
                status=ComponentStatus.DISABLED,
                required=False,
                error_code="G1_NOT_IMPLEMENTED",
            ),
            "neo4j": ComponentReadiness(
                status=ComponentStatus.DISABLED,
                required=False,
                error_code="G1_NOT_IMPLEMENTED",
            ),
            "llm": ComponentReadiness(
                status=ComponentStatus.MOCK,
                required=False,
                provider="MockLLMProvider",
            ),
            "recommendation_pipeline": ComponentReadiness(
                status=ComponentStatus.DISABLED,
                required=False,
                error_code="G1_NOT_IMPLEMENTED",
            ),
        }
