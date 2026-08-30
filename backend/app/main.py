"""FastAPI composition root for the G1 runnable skeleton."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.agent_workspaces import create_agent_workspace_router
from backend.app.api.errors import register_exception_handlers
from backend.app.api.exploration import create_exploration_router
from backend.app.api.auth import PrincipalResolver
from backend.app.api.debug import create_debug_router
from backend.app.api.feedback import create_feedback_router
from backend.app.api.health import create_health_router
from backend.app.api.identity import create_identity_router
from backend.app.api.knowledge_reviews import create_knowledge_review_router
from backend.app.api.middleware import RequestContextMiddleware
from backend.app.api.recommendation import create_recommendation_router
from backend.app.api.recommendation_runs import create_recommendation_run_router
from backend.app.composition import build_configured_auth_resolver
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
from backend.app.observability.domain import ComponentReadiness
from backend.app.observability.ports import ReadinessProbe
from backend.app.platform.lifecycle import RuntimeResourceRegistry


def create_app(
    *,
    settings: AppSettings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    config_bundle_probe: ReadinessProbe | None = None,
    configuration_state: ConfigurationState | None = None,
    recommendation_service: object | None = None,
    recommendation_api_enabled: bool = False,
    recommendation_readiness_enabled: bool = False,
    recommendation_version: str = "recommendation-g3-mysql-v1",
    background_planning_enabled: bool = False,
    background_planning_version: str = "background-planning-v1",
    background_planning_provider: str = "FixtureBackgroundPlanner",
    component_readiness_probes: Mapping[str, ReadinessProbe] | None = None,
    component_readiness_overrides: Mapping[str, ComponentReadiness] | None = None,
    feedback_service: object | None = None,
    behavior_service: object | None = None,
    feedback_api_enabled: bool = False,
    principal_resolver: PrincipalResolver | None = None,
    oidc_jwks_fetcher: object | None = None,
    oidc_identity_mapper: object | None = None,
    debug_api_enabled: bool | None = None,
    exploration_service: object | None = None,
    exploration_api_enabled: bool = False,
    recommendation_progress_broker: object | None = None,
    agent_workspace_broker: object | None = None,
    identity_service: object | None = None,
    identity_api_enabled: bool = False,
    knowledge_review_service: object | None = None,
    knowledge_review_api_enabled: bool = False,
    managed_resources: Sequence[object] | None = None,
) -> FastAPI:
    if recommendation_readiness_enabled and (
        recommendation_service is None or not recommendation_api_enabled
    ):
        raise ValueError(
            "recommendation readiness requires an explicit service and API enable flag"
        )
    if identity_api_enabled and identity_service is None:
        raise ValueError("identity API requires an explicit identity service")
    if knowledge_review_api_enabled and knowledge_review_service is None:
        raise ValueError("knowledge review API requires an explicit service")
    state = configuration_state or (
        ConfigurationState(settings=settings, is_valid=True)
        if settings is not None
        else load_configuration()
    )
    runtime = state.settings
    formal_auth_enabled = bool(getattr(runtime, "auth_enabled", False))
    effective_principal_resolver = principal_resolver
    if effective_principal_resolver is None and formal_auth_enabled:
        effective_principal_resolver = build_configured_auth_resolver(
            runtime,
            oidc_jwks_fetcher=oidc_jwks_fetcher,  # type: ignore[arg-type]
            oidc_identity_mapper=oidc_identity_mapper,  # type: ignore[arg-type]
        )
    effective_debug_api_enabled = (
        runtime.debug_api_enabled
        if debug_api_enabled is None
        else debug_api_enabled
    )
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
        recommendation_enabled=recommendation_readiness_enabled,
        recommendation_version=recommendation_version,
        background_planning_enabled=background_planning_enabled,
        background_planning_version=background_planning_version,
        background_planning_provider=background_planning_provider,
        component_probes=component_readiness_probes,
        component_overrides=component_readiness_overrides,
    )

    # Resources are registered only by an explicit composition root.  Keeping
    # this registry separate from FastAPI dependencies prevents a test double
    # or a caller-owned client from being closed implicitly at shutdown.
    resource_registry = RuntimeResourceRegistry(managed_resources or ())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await resource_registry.close()

    application = FastAPI(
        title="LibraMAS Recommendation API",
        version=runtime.app_version,
        description=(
            "Health API plus an explicitly composed recommendation graph. "
            "The module-level default remains health-only."
        ),
        lifespan=lifespan,
    )
    application.state.configuration = state
    application.state.runtime_resources = resource_registry
    application.state.runtime_metrics = resource_registry.snapshots
    application.add_middleware(RequestContextMiddleware)
    cors_methods = ["GET"]
    cors_headers = ["X-Request-Id", "Content-Type"]
    interaction_api_enabled = (
        (feedback_service is not None or behavior_service is not None)
        and feedback_api_enabled
    )
    if (recommendation_service is not None and recommendation_api_enabled) or interaction_api_enabled:
        cors_methods.append("POST")
        cors_headers.extend(["Idempotency-Key", "X-Demo-User-Id"])
    if identity_service is not None and identity_api_enabled:
        if "POST" not in cors_methods:
            cors_methods.append("POST")
        if "PUT" not in cors_methods:
            cors_methods.append("PUT")
        cors_headers.extend(["Idempotency-Key", "X-CSRF-Token"])
    if knowledge_review_service is not None and knowledge_review_api_enabled:
        if "POST" not in cors_methods:
            cors_methods.append("POST")
        if "Idempotency-Key" not in cors_headers:
            cors_headers.append("Idempotency-Key")
    if effective_principal_resolver is not None or effective_debug_api_enabled:
        cors_headers.append("Authorization")
    if recommendation_progress_broker is not None or agent_workspace_broker is not None:
        cors_headers.append("Last-Event-ID")
    if agent_workspace_broker is not None:
        cors_headers.append("X-Agent-Workspace-Id")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.cors_origins),
        allow_credentials=True,
        allow_methods=cors_methods,
        allow_headers=cors_headers,
    )
    register_exception_handlers(application)
    application.include_router(
        create_health_router(
            readiness_service=readiness_service,
            app_version=runtime.app_version,
        )
    )
    if recommendation_service is not None:
        application.include_router(
            create_recommendation_router(
                service=recommendation_service,
                app_env=runtime.app_env,
                demo_identity_enabled=runtime.app_env == "demo",
                pipeline_enabled=recommendation_api_enabled,
                principal_resolver=effective_principal_resolver,
            )
        )
        if recommendation_progress_broker is not None:
            application.include_router(
                create_recommendation_run_router(
                    service=recommendation_service,
                    broker=recommendation_progress_broker,
                    app_env=runtime.app_env,
                    demo_identity_enabled=runtime.app_env == "demo",
                    pipeline_enabled=recommendation_api_enabled,
                    principal_resolver=effective_principal_resolver,
                    workspace_broker=agent_workspace_broker,
                )
            )
        if effective_debug_api_enabled:
            application.include_router(
                create_debug_router(
                    service=recommendation_service,
                    principal_resolver=effective_principal_resolver,
                    runtime_metrics_provider=resource_registry.diagnostics_snapshot,
                )
            )
    if feedback_service is not None or behavior_service is not None:
        application.include_router(
            create_feedback_router(
                feedback_service=feedback_service,
                behavior_service=behavior_service,
                app_env=runtime.app_env,
                demo_identity_enabled=runtime.app_env == "demo",
                pipeline_enabled=feedback_api_enabled,
                principal_resolver=effective_principal_resolver,
                workspace_broker=agent_workspace_broker,
            )
        )
    if exploration_service is not None and exploration_api_enabled:
        application.include_router(create_exploration_router(service=exploration_service))
    if agent_workspace_broker is not None:
        application.include_router(
            create_agent_workspace_router(
                broker=agent_workspace_broker,
                app_env=runtime.app_env,
                demo_identity_enabled=runtime.app_env == "demo",
                principal_resolver=effective_principal_resolver,
            )
        )
    if identity_service is not None and identity_api_enabled:
        if effective_principal_resolver is None:
            raise ValueError("identity API requires a formal principal resolver")
        application.include_router(
            create_identity_router(
                service=identity_service,  # type: ignore[arg-type]
                principal_resolver=effective_principal_resolver,
                secure_cookies=runtime.auth_cookie_secure,
            )
        )
    if knowledge_review_service is not None and knowledge_review_api_enabled:
        if effective_principal_resolver is None:
            raise ValueError("knowledge review API requires formal authentication")
        application.include_router(create_knowledge_review_router(
            service=knowledge_review_service,  # type: ignore[arg-type]
            principal_resolver=effective_principal_resolver,
        ))
    return application


app = create_app()
