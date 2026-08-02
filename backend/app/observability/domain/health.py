"""Pure health and readiness value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class ComponentStatus(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    DISABLED = "DISABLED"
    MOCK = "MOCK"
    UNKNOWN = "UNKNOWN"


class ServiceReadinessStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True, slots=True)
class ComponentReadiness:
    status: ComponentStatus
    required: bool
    active_version: str | None = None
    provider: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ComponentStatus):
            raise ValueError("status must be a ComponentStatus")
        if not isinstance(self.required, bool):
            raise ValueError("required must be boolean")
        for field_name in ("active_version", "provider", "error_code"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be null or a non-blank string")


@dataclass(frozen=True, slots=True)
class ReadinessAssessment:
    status: ServiceReadinessStatus
    can_recommend: bool
    components: Mapping[str, ComponentReadiness]
    config_bundle_version: str
    failure_error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ServiceReadinessStatus):
            raise ValueError("status must be a ServiceReadinessStatus")
        if not isinstance(self.can_recommend, bool):
            raise ValueError("can_recommend must be boolean")
        if not self.components or not all(
            isinstance(name, str)
            and name.strip()
            and isinstance(component, ComponentReadiness)
            for name, component in self.components.items()
        ):
            raise ValueError("components must contain named ComponentReadiness values")
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))
        if not self.config_bundle_version.strip():
            raise ValueError("config_bundle_version must not be blank")
        if self.status is ServiceReadinessStatus.NOT_READY and not self.failure_error_code:
            raise ValueError("NOT_READY must include failure_error_code")
        if self.status is not ServiceReadinessStatus.NOT_READY and self.failure_error_code:
            raise ValueError("only NOT_READY may include failure_error_code")
        if self.can_recommend and self.status is ServiceReadinessStatus.NOT_READY:
            raise ValueError("NOT_READY cannot recommend")
