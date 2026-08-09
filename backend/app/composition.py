"""Explicit Demo/Research composition roots.

The default FastAPI app intentionally does not call these builders.  A caller
must opt into one of these roots and provide validated settings, which keeps
the runnable health skeleton separate from the research recommendation path.
"""

from __future__ import annotations

from typing import Any

import asyncmy

from backend.app.config import AppSettings
from backend.app.catalog.adapters.mysql import MySQLCatalogRepository
from backend.app.feedback.adapters.mysql import MySQLFeedbackStore
from backend.app.feedback.application.service import FeedbackApplicationService
from backend.app.profile.adapters.behavior_mysql import MySQLBehaviorAppender
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.profile.adapters.refresh_mysql import MySQLProfileRefreshAdapter
from backend.app.profile.application.refresh import ProfileOutboxWorker
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


def _build_mysql_orchestration_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
    retry_policy: RetryPolicy = RetryPolicy(max_attempts=2),
) -> PersistentOrchestrationService:
    factory = connection_factory or _mysql_connection_factory(settings)

    def orchestrator_factory(connection: Any):
        return build_port_orchestrator(
            MySQLCatalogRepository(connection),
            MySQLProfileSnapshotReader(connection),
            retry_policy=retry_policy,
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
) -> PersistentOrchestrationService:
    """Build the opt-in local demo path; never wire it into the default app."""

    if settings.app_env != "demo":
        raise ValueError("demo orchestration requires RECPRO_APP_ENV=demo")
    return _build_mysql_orchestration_service(
        settings,
        connection_factory=connection_factory,
    )


def build_research_orchestration_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> PersistentOrchestrationService:
    """Build the explicit research path while rejecting production by default."""

    if settings.app_env == "production":
        raise ValueError("research orchestration requires a non-production environment")
    return _build_mysql_orchestration_service(
        settings,
        connection_factory=connection_factory,
    )


def build_research_feedback_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> FeedbackApplicationService:
    """Build the opt-in feedback path with one shared transaction boundary."""

    if settings.app_env == "production":
        raise ValueError("research feedback requires a non-production environment")
    return FeedbackApplicationService(
        connection_factory=connection_factory or _mysql_connection_factory(settings),
        feedback_store=MySQLFeedbackStore(),
        behavior_port=MySQLBehaviorAppender(),
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
        refresh_port=MySQLProfileRefreshAdapter(),
        worker_id=worker_id,
        formula_version=formula_version,
    )


__all__ = [
    "build_profile_outbox_worker",
    "build_demo_orchestration_service",
    "build_research_feedback_service",
    "build_research_orchestration_service",
]
