"""FastAPI composition root for the G1 runnable skeleton."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.errors import register_exception_handlers
from backend.app.api.health import create_health_router
from backend.app.api.middleware import RequestContextMiddleware
from backend.app.config import (
    CONFIG_BUNDLE_SCHEMA_PATH,
    CONFIG_BUNDLE_SCHEMA_SHA256,
    AppSettings,
    ConfigurationState,
    load_configuration,
)
from backend.app.logging import configure_logging
from backend.app.observability.adapters import (
    AsyncMySQLReadinessProbe,
    JsonConfigBundleReadinessProbe,
)
from backend.app.observability.application import ReadinessService
from backend.app.observability.ports import ReadinessProbe


def create_app(
    *,
    settings: AppSettings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    config_bundle_probe: ReadinessProbe | None = None,
    configuration_state: ConfigurationState | None = None,
) -> FastAPI:
    state = configuration_state or (
        ConfigurationState(settings=settings, is_valid=True)
        if settings is not None
        else load_configuration()
    )
    runtime = state.settings
    configure_logging(runtime.log_level)

    mysql_probe = readiness_probe or AsyncMySQLReadinessProbe(
        host=runtime.mysql_host,
        port=runtime.mysql_port,
        database=runtime.mysql_database,
        user=runtime.mysql_user,
        password=runtime.mysql_password,
        connect_timeout_seconds=runtime.mysql_connect_timeout_seconds,
        persistence_probe_id=runtime.persistence_probe_id,
    )
    bundle_probe = config_bundle_probe or JsonConfigBundleReadinessProbe(
        path=runtime.config_bundle_path,
        schema_path=CONFIG_BUNDLE_SCHEMA_PATH,
        expected_sha256=runtime.config_bundle_sha256,
        expected_schema_sha256=CONFIG_BUNDLE_SCHEMA_SHA256,
        expected_version=runtime.config_bundle_version,
    )
    readiness_service = ReadinessService(
        mysql_probe=mysql_probe,
        config_bundle_probe=bundle_probe,
        config_bundle_version=runtime.config_bundle_version,
        configuration_valid=state.is_valid,
        configuration_error_code=state.error_code,
    )

    application = FastAPI(
        title="LibraMAS Recommendation API",
        version=runtime.app_version,
        description=(
            "G1 runnable skeleton. Recommendation execution is intentionally disabled."
        ),
    )
    application.state.configuration = state
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.cors_origins),
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["X-Request-Id", "Content-Type"],
    )
    register_exception_handlers(application)
    application.include_router(
        create_health_router(
            readiness_service=readiness_service,
            app_version=runtime.app_version,
        )
    )
    return application


app = create_app()
