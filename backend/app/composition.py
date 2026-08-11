"""Explicit Demo/Research composition roots.

The default FastAPI app intentionally does not call these builders.  A caller
must opt into one of these roots and provide validated settings, which keeps
the runnable health skeleton separate from the research recommendation path.
"""

from __future__ import annotations

from typing import Any

import asyncmy
from fastapi import FastAPI

from backend.app.config import AppSettings
from backend.app.llm.factory import build_llm_provider
from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.feedback.adapters.mysql import MySQLFeedbackStore
from backend.app.feedback.application.service import (
    BehaviorApplicationService,
    FeedbackApplicationService,
)
from backend.app.profile.adapters.behavior_mysql import MySQLBehaviorAppender
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.profile.adapters.refresh_mysql import MySQLProfileRefreshAdapter
from backend.app.profile.application.refresh import ProfileOutboxWorker
from backend.app.observability.adapters.mysql_transition import MySQLStateTransitionWriter
from backend.app.platform.auth import (
    HMACBearerTokenResolver,
    build_formal_principal_resolver,
)
from backend.app.recommendation.adapters.agent_logging_mysql import MySQLAgentExecutionLogWriter
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from backend.app.recommendation.application.persistent_orchestration import (
    ConnectionFactory,
    PersistentOrchestrationService,
)


def _mysql_connection_factory(settings: AppSettings) -> ConnectionFactory:
    options = {
        "host": settings.mysql_host,
        "port": settings.mysql_port,
        "db": settings.mysql_database,
        "user": settings.mysql_user,
        "password": settings.mysql_password.get_secret_value(),
        "connect_timeout": settings.mysql_connect_timeout_seconds,
        "read_timeout": max(settings.mysql_connect_timeout_seconds, 3.0),
        "charset": "utf8mb4",
        "autocommit": False,
    }

    async def connect() -> Any:
        return await asyncmy.connect(**options)

    return connect


def build_formal_auth_resolver(
    settings: AppSettings,
) -> HMACBearerTokenResolver | None:
    """Build the explicit formal Bearer resolver without enabling any route.

    Authentication construction is kept in the composition root.  Callers
    still have to opt into recommendation/interaction services and their API
    flags separately, so setting ``RECPRO_AUTH_ENABLED=true`` alone cannot
    expose a business endpoint.
    """

    return build_formal_principal_resolver(settings)


def build_production_http_app(
    settings: AppSettings,
    *,
    recommendation_service: object | None,
    feedback_service: object | None,
    behavior_service: object | None,
    readiness_probe: object | None = None,
    config_bundle_probe: object | None = None,
) -> FastAPI:
    """Build the complete production HTTP graph behind explicit fail-closed gates.

    This function is intentionally separate from :func:`create_app`: the
    default module-level app remains health-only, while a deployment must opt
    into the production flag, formal authentication, all G3/G5 services, and
    both business API flags in one reviewed call.  No database connection is
    opened while constructing the graph.
    """

    if settings.app_env != "production":
        raise ValueError("production HTTP composition requires RECPRO_APP_ENV=production")
    if not settings.production_http_enabled:
        raise ValueError("production HTTP composition is disabled by configuration")
    if not settings.auth_enabled or settings.auth_jwt_secret is None:
        raise ValueError("production HTTP composition requires formal bearer authentication")
    if recommendation_service is None:
        raise ValueError("production HTTP composition requires recommendation service")
    if feedback_service is None or behavior_service is None:
        raise ValueError("production HTTP composition requires feedback and behavior services")
    principal_resolver = build_formal_auth_resolver(settings)
    if principal_resolver is None:
        raise ValueError("production HTTP composition could not build bearer resolver")

    # Import locally to keep the main module's default app and this explicit
    # production graph free of an import cycle.
    from backend.app.main import create_app

    return create_app(
        settings=settings,
        readiness_probe=readiness_probe,
        config_bundle_probe=config_bundle_probe,
        recommendation_service=recommendation_service,
        recommendation_api_enabled=True,
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        feedback_api_enabled=True,
        principal_resolver=principal_resolver,
        debug_api_enabled=False,
    )


def _build_mysql_orchestration_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
    retry_policy: RetryPolicy = RetryPolicy(max_attempts=2),
    enable_llm_provider: bool = False,
) -> PersistentOrchestrationService:
    factory = connection_factory or _mysql_connection_factory(settings)
    llm_provider = build_llm_provider(settings) if enable_llm_provider else None

    def orchestrator_factory(connection: Any):
        return build_port_orchestrator(
            MySQLCatalogRepository(connection),
            MySQLProfileSnapshotReader(connection),
            retry_policy=retry_policy,
            llm_provider=llm_provider,
        )

    return PersistentOrchestrationService(
        connection_factory=factory,
        orchestrator_factory=orchestrator_factory,
        log_port=MySQLAgentExecutionLogWriter(),
    )


def build_demo_orchestration_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
    enable_llm_provider: bool = False,
) -> PersistentOrchestrationService:
    """Build the opt-in local demo path; never wire it into the default app."""

    if settings.app_env != "demo":
        raise ValueError("demo orchestration requires RECPRO_APP_ENV=demo")
    return _build_mysql_orchestration_service(
        settings,
        connection_factory=connection_factory,
        enable_llm_provider=enable_llm_provider,
    )


def build_research_orchestration_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
    enable_llm_provider: bool = False,
) -> PersistentOrchestrationService:
    """Build the explicit research path while rejecting production by default."""

    if settings.app_env == "production":
        raise ValueError("research orchestration requires a non-production environment")
    return _build_mysql_orchestration_service(
        settings,
        connection_factory=connection_factory,
        enable_llm_provider=enable_llm_provider,
    )


def build_research_feedback_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> FeedbackApplicationService:
    """Build the opt-in feedback path with one shared transaction boundary."""

    if settings.app_env == "production":
        raise ValueError("research feedback requires a non-production environment")
    transition_sink = MySQLStateTransitionWriter()
    return FeedbackApplicationService(
        connection_factory=connection_factory or _mysql_connection_factory(settings),
        feedback_store=MySQLFeedbackStore(transition_sink=transition_sink),
        behavior_port=MySQLBehaviorAppender(transition_sink=transition_sink),
    )


def build_research_behavior_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> BehaviorApplicationService:
    """Build the opt-in direct-behavior path with one shared transaction boundary."""

    if settings.app_env == "production":
        raise ValueError("research behavior ingestion requires a non-production environment")
    transition_sink = MySQLStateTransitionWriter()
    return BehaviorApplicationService(
        connection_factory=connection_factory or _mysql_connection_factory(settings),
        append_port=MySQLBehaviorAppender(transition_sink=transition_sink),
        ownership_reader=MySQLFeedbackStore(),
    )


def build_profile_outbox_worker(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory,
    worker_id: str,
    formula_version: str = "profile-g2-v1",
) -> ProfileOutboxWorker:
    """Build a worker with an explicitly supplied, controlled-write connection."""

    if settings.app_env == "production":
        raise ValueError("profile worker requires a non-production environment")
    return ProfileOutboxWorker(
        connection_factory=connection_factory,
        refresh_port=MySQLProfileRefreshAdapter(
            transition_sink=MySQLStateTransitionWriter()
        ),
        worker_id=worker_id,
        formula_version=formula_version,
    )


__all__ = [
    "build_formal_auth_resolver",
    "build_production_http_app",
    "build_profile_outbox_worker",
    "build_demo_orchestration_service",
    "build_research_behavior_service",
    "build_research_feedback_service",
    "build_research_orchestration_service",
]
