"""Fail-closed runtime configuration for the G1 backend skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from backend.app.shared_kernel.contracts.errors import ErrorCode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_BUNDLE_SCHEMA_PATH = PROJECT_ROOT / "contracts/config/rec-config.schema.json"
CONFIG_BUNDLE_SCHEMA_SHA256 = (
    "2783a75736fe21d39f2ef3101fa9f9849f1ac3757d0a05c50d656b5169ab6bd1"
)
LOCAL_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")


class AppSettings(BaseSettings):
    """Validated settings sourced only from explicit ``RECPRO_`` variables."""

    model_config = SettingsConfigDict(
        env_prefix="RECPRO_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        validate_default=True,
    )

    app_env: Literal["development", "test", "demo", "production"] = "development"
    app_version: str = Field(default="0.1.0", min_length=1, max_length=64)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    config_bundle_version: str = Field(
        default="rec-1.0.0",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    config_bundle_path: Path = Path(
        "contracts/config/examples/rec-1.0.0.json"
    )
    config_bundle_sha256: str = Field(
        default="220b0fb30f38fef7ca148c43b1f2751715c7df7ecf7d47e7ddfce7ff2847a5c6",
        pattern=r"^[0-9a-f]{64}$",
    )

    mysql_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = Field(
        default="recpro",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{2,63}$",
    )
    mysql_user: str = Field(
        default="recpro_runtime",
        min_length=3,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]{2,31}$",
    )
    mysql_password: SecretStr
    mysql_connect_timeout_seconds: float = Field(default=3.0, gt=0.0, le=30.0)
    persistence_probe_id: str = Field(
        default="g1-bootstrap-v1",
        min_length=3,
        max_length=48,
        pattern=r"^[a-z0-9][a-z0-9_-]{2,47}$",
    )

    llm_provider: Literal["mock"] = "mock"
    recommendation_pipeline_enabled: Literal[False] = False
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    @field_validator("config_bundle_path", mode="before")
    @classmethod
    def resolve_config_bundle_path(cls, value: object) -> Path:
        path = Path(str(value))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("config bundle path must be project-relative and contained")
        resolved = (PROJECT_ROOT / path).resolve()
        try:
            resolved.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise ValueError(
                "config bundle path must be project-relative and contained"
            ) from exc
        return resolved

    @field_validator("mysql_password")
    @classmethod
    def validate_mysql_password(cls, value: SecretStr) -> SecretStr:
        if not LOCAL_SECRET_PATTERN.fullmatch(value.get_secret_value()):
            raise ValueError(
                "mysql password must contain 16-128 approved local characters"
            )
        return value


@dataclass(frozen=True, slots=True)
class ConfigurationState:
    settings: AppSettings
    is_valid: bool
    error_code: str | None = None


def load_configuration() -> ConfigurationState:
    """Load settings without allowing a malformed environment to crash liveness.

    A validation failure produces a safe placeholder configuration. Readiness sees
    ``is_valid=False`` and fails closed before any dependency probe is attempted.
    """

    try:
        return ConfigurationState(settings=AppSettings(), is_valid=True)
    except (OSError, RuntimeError, SettingsError, ValidationError, ValueError):
        fallback = AppSettings.model_construct(
            mysql_password=SecretStr("invalid-configuration-placeholder")
        )
        return ConfigurationState(
            settings=fallback,
            is_valid=False,
            error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
        )
