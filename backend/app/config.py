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
    "1fa3b19788574189ae1680a0ef5565fd378200d146d9c0ba83da583ba3abce1a"
)
LOCAL_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
RETIRED_WORKSPACE_AUDIT_PLAN_IDS = frozenset(
    {"0cb5fb89-ba1a-5f8d-ab32-841b2d4df6e5"}
)


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
        "contracts/prompts/rec-prompts-v1.0.1.json"
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
    # Connection pools are lazy (min size 0 by default) so importing or
    # composing an application never opens a database connection.  The upper
    # bound keeps one process from exhausting the shared research MySQL.
    mysql_pool_min_size: int = Field(default=0, ge=0, le=32)
    mysql_pool_max_size: int = Field(default=10, ge=1, le=64)
    mysql_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    mysql_pool_acquire_timeout_seconds: float = Field(default=3.0, gt=0.0, le=30.0)
    persistence_probe_id: str = Field(
        default="g1-bootstrap-v1",
        min_length=3,
        max_length=48,
        pattern=r"^[a-z0-9][a-z0-9_-]{2,47}$",
    )
    # The active Neo4j graph, MySQL catalog snapshot, and Chroma source graph
    # are versioned independently.  The current v2 graph adds Work identity
    # nodes while the existing immutable vector index still truthfully records
    # the v1 Book snapshot from which it was built.
    research_graph_version: str = Field(
        default="lib-books-v2-20260828",
        pattern=r"^lib-books-v[0-9]+-[0-9]{8}$",
    )
    research_dataset_version: str = Field(
        default="lib-books-v1-20260810",
        pattern=r"^lib-books-v[0-9]+-[0-9]{8}$",
    )
    research_vector_source_graph_version: str = Field(
        default="lib-books-v1-20260810",
        pattern=r"^lib-books-v[0-9]+-[0-9]{8}$",
    )
    identity_mysql_user: str | None = Field(
        default=None, min_length=3, max_length=32,
        pattern=r"^[a-z][a-z0-9_]{2,31}$",
    )
    identity_mysql_password: SecretStr | None = None

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
    # Real model use is capability-scoped. Intent and evidence-constrained
    # explanation have independent gates so request cost and fallback evidence
    # remain reviewable instead of changing with the provider setting alone.
    g4_llm_intent_enabled: bool = False
    g4_llm_explanation_enabled: bool = False
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
    local_identity_api_enabled: bool = False
    auth_jwt_secret: SecretStr | None = None
    auth_identifier_pepper: SecretStr | None = None
    auth_token_pepper: SecretStr | None = None
    auth_cookie_secure: bool = True
    auth_access_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    auth_refresh_ttl_seconds: int = Field(default=8 * 60 * 60, ge=3600, le=7 * 24 * 3600)
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
    # Workspace audit is a separately approved append-only capability.  Merely
    # enabling the research application is insufficient: a successor plan,
    # its canonical hash, and a bounded run identity must all be supplied.
    agent_workspace_audit_enabled: bool = False
    agent_workspace_audit_plan_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    agent_workspace_audit_plan_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    agent_workspace_audit_run_identity: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$",
    )
    agent_workspace_audit_max_facts: int = Field(default=512, ge=1, le=512)
    agent_workspace_audit_batch_limit: int = Field(default=32, ge=1, le=64)
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

    @field_validator("identity_mysql_password")
    @classmethod
    def validate_identity_mysql_password(
        cls, value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        if not LOCAL_SECRET_PATTERN.fullmatch(value.get_secret_value()):
            raise ValueError(
                "identity MySQL password must contain 16-128 approved local characters"
            )
        return value

    @field_validator("auth_jwt_secret", "auth_identifier_pepper", "auth_token_pepper")
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
    def validate_mysql_pool_configuration(self) -> "AppSettings":
        if self.mysql_pool_min_size > self.mysql_pool_max_size:
            raise ValueError("mysql pool min size cannot exceed max size")
        return self

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "AppSettings":
        if self.auth_enabled and self.auth_jwt_secret is None:
            raise ValueError(
                "auth JWT secret is required when formal authentication is enabled"
            )
        if self.local_identity_api_enabled and not self.auth_enabled:
            raise ValueError("local identity API requires formal authentication")
        if self.local_identity_api_enabled and (
            self.auth_identifier_pepper is None or self.auth_token_pepper is None
        ):
            raise ValueError("local identity API requires identifier and token peppers")
        if self.local_identity_api_enabled and (
            self.identity_mysql_user is None or self.identity_mysql_password is None
        ):
            raise ValueError("local identity API requires its least-privilege MySQL account")
        if self.app_env == "production" and not self.auth_cookie_secure:
            raise ValueError("production identity cookies must be secure")
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
        enabled_g4_capabilities = (
            self.g4_llm_intent_enabled or self.g4_llm_explanation_enabled
        )
        if enabled_g4_capabilities and not self.g4_http_enabled:
            raise ValueError(
                "G4 LLM capabilities require the explicit G4 HTTP composition"
            )
        if enabled_g4_capabilities and self.llm_provider != "deepseek":
            raise ValueError(
                "G4 LLM capabilities require the deepseek provider"
            )
        if enabled_g4_capabilities and self.app_env != "demo":
            raise ValueError("G4 LLM capabilities are restricted to the demo environment")
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

    @model_validator(mode="after")
    def validate_workspace_audit_configuration(self) -> "AppSettings":
        approval_fields = (
            self.agent_workspace_audit_plan_id,
            self.agent_workspace_audit_plan_hash,
            self.agent_workspace_audit_run_identity,
        )
        if not self.agent_workspace_audit_enabled:
            if any(value is not None for value in approval_fields):
                raise ValueError(
                    "workspace audit approval fields require the explicit audit switch"
                )
            return self
        if self.app_env != "demo":
            raise ValueError("workspace audit is restricted to the demo research runtime")
        if any(value is None for value in approval_fields):
            raise ValueError(
                "workspace audit requires successor plan id, plan hash, and run identity"
            )
        if self.agent_workspace_audit_plan_id in RETIRED_WORKSPACE_AUDIT_PLAN_IDS:
            raise ValueError("the previous workspace audit plan is retired")
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
