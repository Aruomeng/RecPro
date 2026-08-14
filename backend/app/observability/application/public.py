"""Public readiness use case used by the HTTP adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from backend.app.observability.domain import (
    ComponentReadiness,
    ComponentStatus,
    ReadinessAssessment,
    ServiceReadinessStatus,
)
from backend.app.observability.ports import ReadinessProbe
from backend.app.shared_kernel.contracts.errors import ErrorCode


class ReadinessService:
    """Aggregate dependency health while keeping capability opt-in.

    The default constructor represents the health-only G1 application.  An
    explicit composition root may set ``recommendation_enabled=True`` after it
    has supplied a recommendation service and enabled its HTTP route.  This
    keeps the health response truthful for both graphs without changing the
    module-level default app.
    """

    def __init__(
        self,
        *,
        mysql_probe: ReadinessProbe,
        config_bundle_probe: ReadinessProbe,
        config_bundle_version: str,
        configuration_valid: bool,
        configuration_error_code: str | None = None,
        recommendation_enabled: bool = False,
        recommendation_version: str = "recommendation-g3-mysql-v1",
        component_probes: Mapping[str, ReadinessProbe] | None = None,
        component_overrides: Mapping[str, ComponentReadiness] | None = None,
    ) -> None:
        self._mysql_probe = mysql_probe
        self._config_bundle_probe = config_bundle_probe
        self._config_bundle_version = config_bundle_version
        self._configuration_valid = configuration_valid
        self._configuration_error_code = configuration_error_code
        if not isinstance(recommendation_enabled, bool):
            raise ValueError("recommendation_enabled must be boolean")
        if not recommendation_version.strip():
            raise ValueError("recommendation_version must not be blank")
        self._recommendation_enabled = recommendation_enabled
        self._recommendation_version = recommendation_version
        allowed_components = {"chroma", "neo4j", "llm", "interaction_pipeline"}
        probes = dict(component_probes or {})
        overrides = dict(component_overrides or {})
        if set(probes) - allowed_components or set(overrides) - allowed_components:
            raise ValueError("runtime readiness overrides contain an unsupported component")
        if set(probes) & set(overrides):
            raise ValueError("a readiness component cannot have both a probe and override")
        self._component_probes = probes
        self._component_overrides = overrides

    async def evaluate(self) -> ReadinessAssessment:
        components = self._static_components()
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
            self._mark_pipeline_unavailable(
                components, ErrorCode.CONFIG_BUNDLE_INVALID.value
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
            self._mark_pipeline_unavailable(
                components, ErrorCode.CONFIG_BUNDLE_INVALID.value
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
            self._mark_pipeline_unavailable(
                components,
                mysql.error_code or ErrorCode.CORE_STORAGE_UNAVAILABLE.value,
            )
            return ReadinessAssessment(
                status=ServiceReadinessStatus.NOT_READY,
                can_recommend=False,
                components=components,
                config_bundle_version=self._config_bundle_version,
                failure_error_code=(
                    mysql.error_code or ErrorCode.CORE_STORAGE_UNAVAILABLE.value
                ),
            )

        if self._component_probes:
            names = tuple(sorted(self._component_probes))
            results = await asyncio.gather(
                *(self._component_probes[name].check() for name in names),
                return_exceptions=True,
            )
            for name, result in zip(names, results, strict=True):
                if isinstance(result, ComponentReadiness):
                    components[name] = result
                else:
                    components[name] = ComponentReadiness(
                        status=ComponentStatus.DOWN,
                        required=False,
                        error_code="OPTIONAL_RUNTIME_UNAVAILABLE",
                    )

        required_unavailable = next(
            (
                component
                for component in components.values()
                if component.required and component.status is not ComponentStatus.UP
            ),
            None,
        )
        if required_unavailable is not None:
            self._mark_pipeline_unavailable(
                components,
                required_unavailable.error_code or "REQUIRED_RUNTIME_UNAVAILABLE",
            )
            return ReadinessAssessment(
                status=ServiceReadinessStatus.NOT_READY,
                can_recommend=False,
                components=components,
                config_bundle_version=self._config_bundle_version,
                failure_error_code=(
                    required_unavailable.error_code or "REQUIRED_RUNTIME_UNAVAILABLE"
                ),
            )

        degraded = any(
            component.status in {
                ComponentStatus.DOWN,
                ComponentStatus.MOCK,
                ComponentStatus.UNKNOWN,
            }
            for component in components.values()
        )

        return ReadinessAssessment(
            status=(
                ServiceReadinessStatus.DEGRADED
                if degraded or not self._recommendation_enabled
                else ServiceReadinessStatus.READY
            ),
            can_recommend=self._recommendation_enabled,
            components=components,
            config_bundle_version=self._config_bundle_version,
        )

    def _static_components(self) -> dict[str, ComponentReadiness]:
        components = {
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
                status=(
                    ComponentStatus.UP
                    if self._recommendation_enabled
                    else ComponentStatus.DISABLED
                ),
                required=self._recommendation_enabled,
                active_version=(
                    self._recommendation_version
                    if self._recommendation_enabled
                    else None
                ),
                error_code=(
                    None
                    if self._recommendation_enabled
                    else "G1_NOT_IMPLEMENTED"
                ),
            ),
        }
        components.update(self._component_overrides)
        return components

    def _mark_pipeline_unavailable(
        self,
        components: dict[str, ComponentReadiness],
        error_code: str,
    ) -> None:
        if not self._recommendation_enabled:
            return
        components["recommendation_pipeline"] = ComponentReadiness(
            status=ComponentStatus.UNKNOWN,
            required=True,
            active_version=self._recommendation_version,
            error_code=error_code,
        )
