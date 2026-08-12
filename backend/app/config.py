"""Fail-closed runtime configuration for the G1 backend skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from backend.app.shared_kernel.contracts.errors import ErrorCode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_BUNDLE_SCHEMA_PATH = PROJECT_ROOT / "contracts/config/rec-config.schema.json"
CONFIG_BUNDLE_SCHEMA_SHA256 = (
    "2783a75736fe21d39f2ef3101fa9f9849f1ac3757d0a05c50d656b5169ab6bd1"
)
DEFAULT_PROMPT_BUNDLE_SHA256 = (
    "bad547702e4c3b42395280ea44781e60992a85f981605afbcd29aa13d33db94a"
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
    prompt_bundle_version: str = Field(
        default="prompt-v1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    prompt_bundle_path: Path = Path(
        "contracts/prompts/rec-prompts-v1.0.0.json"
    )
    prompt_bundle_sha256: str = Field(
        default=DEFAULT_PROMPT_BUNDLE_SHA256,
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

    # The worker process is part of the Compose skeleton, but its controlled
    # write capability must never be enabled by merely starting the stack.
    # ``profile_outbox`` is the only currently supported mode and is reserved
    # for an explicit non-production opt-in run.
    worker_enabled: bool = False
    worker_mode: Literal["disabled", "profile_outbox"] = "disabled"
    worker_id: str = Field(
        default="recpro-worker",
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$",
    )
    worker_poll_interval_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    worker_batch_limit: int = Field(default=10, ge=1, le=100)
    worker_lease_seconds: int = Field(default=60, ge=1, le=3600)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_formula_version: str = Field(
        default="profile-g2-v1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
    )

    # Mock remains the only default.  ``deepseek`` is a deliberately opt-in
    # adapter and cannot become valid until a local API key is supplied.
    llm_provider: Literal["mock", "deepseek"] = "mock"
    llm_base_url: str = Field(
        default="https://api.deepseek.com",
        min_length=1,
        max_length=255,
    )
    llm_model: str = Field(
        default="deepseek-v4-flash",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=20.0, gt=0.0, le=120.0)
    llm_max_output_tokens: int = Field(default=512, ge=1, le=8192)
    recommendation_pipeline_enabled: Literal[False] = False
    # The real G4 HTTP graph is an explicit research composition. Keeping a
    # separate switch prevents a configured G4 service from being exposed by
    # the default health-only app or by the Compose command.
    g4_http_enabled: bool = False
    # G5 interaction HTTP is a second, independent opt-in.  It is deliberately
    # separate from the frontend flag and from ``g4_http_enabled`` so a local
    # recommendation server cannot acquire database-writing feedback routes by
    # accident.
    g5_interaction_http_enabled: bool = False
    debug_api_enabled: bool = False
    # A production HTTP composition must opt in separately from authentication
    # and from the default health-only application.
    production_http_enabled: bool = False
    # Formal HTTP authentication is deliberately opt-in.  The default local
    # runtime has no bearer secret and therefore cannot accidentally expose a
    # credential-backed route.
    auth_enabled: bool = False
    auth_jwt_secret: SecretStr | None = None
    auth_jwt_issuer: str = Field(
        default="libramas-local",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    auth_jwt_audience: str = Field(
        default="libramas-api",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    auth_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
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

    @field_validator("prompt_bundle_path", mode="before")
    @classmethod
    def resolve_prompt_bundle_path(cls, value: object) -> Path:
        path = Path(str(value))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("prompt bundle path must be project-relative and contained")
        resolved = (PROJECT_ROOT / path).resolve()
        try:
            resolved.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise ValueError(
                "prompt bundle path must be project-relative and contained"
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

    @field_validator("auth_jwt_secret")
    @classmethod
    def validate_auth_jwt_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if secret == "":
            return None
        if not 32 <= len(secret) <= 256:
            raise ValueError("auth JWT secret must contain 32-256 characters")
        if any(character.isspace() for character in secret):
            raise ValueError("auth JWT secret must not contain whitespace")
        return value

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "AppSettings":
        if self.auth_enabled and self.auth_jwt_secret is None:
            raise ValueError(
                "auth JWT secret is required when formal authentication is enabled"
            )
        return self

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("llm base URL must be an HTTPS origin")
        if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("llm base URL must not include a path, query, or fragment")
        return value.rstrip("/")

    @field_validator("llm_api_key")
    @classmethod
    def validate_llm_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or value.get_secret_value() == "":
            return None
        secret = value.get_secret_value()
        if not 16 <= len(secret) <= 256 or any(character.isspace() for character in secret):
            raise ValueError("llm API key must be 16-256 non-whitespace characters")
        return value

    @model_validator(mode="after")
    def validate_llm_configuration(self) -> "AppSettings":
        if self.llm_provider == "deepseek" and self.llm_api_key is None:
            raise ValueError("llm API key is required when deepseek provider is enabled")
        return self

    @model_validator(mode="after")
    def validate_worker_configuration(self) -> "AppSettings":
        if self.worker_enabled and self.worker_mode != "profile_outbox":
            raise ValueError(
                "worker mode must be profile_outbox when the worker is enabled"
            )
        if not self.worker_enabled and self.worker_mode != "disabled":
            raise ValueError("worker mode must be disabled unless the worker is enabled")
        if self.worker_enabled and self.app_env == "production":
            raise ValueError("profile outbox worker is not enabled for production yet")
        return self


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
