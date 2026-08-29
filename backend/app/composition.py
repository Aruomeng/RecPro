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
from backend.app.catalog.ports.public import (
    GraphRecallPort,
    QueryEmbeddingPort,
    VectorRecallPort,
)
from backend.app.feedback.adapters.mysql import MySQLFeedbackStore
from backend.app.exploration import ExplorationService
from backend.app.exploration.graph_reader import PublicGraphReader
from backend.app.exploration.mysql_reader import MySQLCatalogReader
from backend.app.feedback.application.service import (
    BehaviorApplicationService,
    FeedbackApplicationService,
)
from backend.app.profile.adapters.behavior_mysql import MySQLBehaviorAppender
from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.profile.adapters.refresh_mysql import MySQLProfileRefreshAdapter
from backend.app.profile.application.refresh import ProfileOutboxWorker
from backend.app.observability.adapters.mysql_transition import MySQLStateTransitionWriter
from backend.app.observability.adapters import AsyncOperationReadinessProbe
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.platform.auth import (
    HMACBearerTokenResolver,
    build_formal_principal_resolver,
)
from backend.app.identity import IdentityService
from backend.app.identity.adapters import MySQLIdentityRepository
from backend.app.identity.security import (
    Argon2idPasswordService,
    HMACIdentifierService,
    HMACSecretTokenService,
    LocalJWTIssuer,
    VersionedPrincipalResolver,
)
from backend.app.agent_workspace import AgentWorkspaceAuditBuffer
from backend.app.agent_workspace.adapters.mysql_audit import MySQLAgentWorkspaceAuditAdapter
from backend.app.agent_workspace.application.audit_worker import AgentWorkspaceAuditWorker
from backend.app.agent_workspace.adapters.profile_reader import MySQLWorkspaceProfileReader
from backend.app.knowledge_review import (
    InMemoryKnowledgeReviewRepository,
    KnowledgeReviewService,
    MySQLKnowledgeReviewRepository,
)
from backend.app.knowledge_review.loader import load_v2_review_proposals
from backend.app.recommendation.adapters.agent_logging_mysql import MySQLAgentExecutionLogWriter
from backend.app.recommendation.adapters.g4_mysql import (
    MySQLG4RecommendationTaskService,
)
from backend.app.recommendation.adapters.mysql import MySQLRecommendationTaskService
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.orchestrator import RecommendationOrchestrator
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from backend.app.recommendation.application.persistent_orchestration import (
    ConnectionFactory,
    PersistentOrchestrationService,
)
from backend.app.catalog.runtime.g4_ports import G4ReadOnlyRuntime


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


def _identity_mysql_connection_factory(settings: AppSettings) -> ConnectionFactory:
    if settings.identity_mysql_user is None or settings.identity_mysql_password is None:
        raise ValueError("identity MySQL credentials are not configured")
    options = {
        "host": settings.mysql_host,
        "port": settings.mysql_port,
        "db": settings.mysql_database,
        "user": settings.identity_mysql_user,
        "password": settings.identity_mysql_password.get_secret_value(),
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


def build_local_identity_service(
    settings: AppSettings, *, connection_factory: ConnectionFactory | None = None,
) -> IdentityService:
    """Construct local IAM without opening a database connection."""

    if not settings.local_identity_api_enabled or not settings.auth_enabled:
        raise ValueError("local identity service is disabled by configuration")
    if (
        settings.auth_jwt_secret is None or settings.auth_identifier_pepper is None
        or settings.auth_token_pepper is None
    ):
        raise ValueError("local identity cryptographic secrets are incomplete")
    factory = connection_factory or _identity_mysql_connection_factory(settings)
    return IdentityService(
        repository=MySQLIdentityRepository(factory),
        passwords=Argon2idPasswordService(),
        identifiers=HMACIdentifierService(
            settings.auth_identifier_pepper.get_secret_value().encode(),
        ),
        secrets=HMACSecretTokenService(
            settings.auth_token_pepper.get_secret_value().encode(),
        ),
        access_tokens=LocalJWTIssuer(
            secret=settings.auth_jwt_secret.get_secret_value().encode(),
            issuer=settings.auth_jwt_issuer, audience=settings.auth_jwt_audience,
            ttl_seconds=settings.auth_access_ttl_seconds,
        ),
        refresh_ttl_seconds=settings.auth_refresh_ttl_seconds,
    )


def build_local_identity_principal_resolver(
    settings: AppSettings, service: IdentityService,
) -> VersionedPrincipalResolver:
    token_resolver = build_formal_auth_resolver(settings)
    if token_resolver is None:
        raise ValueError("formal JWT resolver is unavailable")
    return VersionedPrincipalResolver(token_resolver, service)


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
        recommendation_readiness_enabled=True,
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        feedback_api_enabled=True,
        principal_resolver=principal_resolver,
        debug_api_enabled=False,
    )


def build_demo_http_app(
    settings: AppSettings,
    *,
    recommendation_service: object | None,
    feedback_service: object | None = None,
    behavior_service: object | None = None,
    readiness_probe: object | None = None,
    config_bundle_probe: object | None = None,
    feedback_api_enabled: bool = False,
) -> FastAPI:
    """Build an explicitly enabled local demo HTTP graph.

    The module-level ``backend.app.main:app`` remains health-only.  This
    builder is the only non-production path that marks recommendation
    readiness true, and it still requires the caller to provide the concrete
    service.  Construction opens no database connection; request execution
    retains the service's normal transaction boundary.
    """

    if settings.app_env != "demo":
        raise ValueError("demo HTTP composition requires RECPRO_APP_ENV=demo")
    if recommendation_service is None:
        raise ValueError("demo HTTP composition requires recommendation service")
    if feedback_api_enabled and (feedback_service is None or behavior_service is None):
        raise ValueError(
            "demo feedback API requires both feedback and behavior services"
        )

    from backend.app.main import create_app

    return create_app(
        settings=settings,
        readiness_probe=readiness_probe,
        config_bundle_probe=config_bundle_probe,
        recommendation_service=recommendation_service,
        recommendation_api_enabled=True,
        recommendation_readiness_enabled=True,
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        feedback_api_enabled=feedback_api_enabled,
        debug_api_enabled=False,
    )


def _build_mysql_orchestration_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
    retry_policy: RetryPolicy = RetryPolicy(max_attempts=2),
    enable_llm_provider: bool = False,
    graph: GraphRecallPort | None = None,
    graph_version: str | None = None,
    vector: VectorRecallPort | None = None,
    query_embedder: QueryEmbeddingPort | None = None,
    embedding_version: str | None = None,
    index_version: str | None = None,
) -> PersistentOrchestrationService:
    factory = connection_factory or _mysql_connection_factory(settings)
    llm_provider = build_llm_provider(settings) if enable_llm_provider else None

    def orchestrator_factory(connection: Any):
        return build_port_orchestrator(
            MySQLCatalogRepository(connection),
            MySQLProfileSnapshotReader(connection),
            graph=graph,
            graph_version=graph_version,
            vector=vector,
            query_embedder=query_embedder,
            embedding_version=embedding_version,
            index_version=index_version,
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
    graph: GraphRecallPort | None = None,
    graph_version: str | None = None,
    vector: VectorRecallPort | None = None,
    query_embedder: QueryEmbeddingPort | None = None,
    embedding_version: str | None = None,
    index_version: str | None = None,
) -> PersistentOrchestrationService:
    """Build the opt-in local demo path; never wire it into the default app."""

    if settings.app_env != "demo":
        raise ValueError("demo orchestration requires RECPRO_APP_ENV=demo")
    return _build_mysql_orchestration_service(
        settings,
        connection_factory=connection_factory,
        enable_llm_provider=enable_llm_provider,
        graph=graph,
        graph_version=graph_version,
        vector=vector,
        query_embedder=query_embedder,
        embedding_version=embedding_version,
        index_version=index_version,
    )


def build_demo_mysql_http_app(
    settings: AppSettings,
    *,
    dataset_version: str = "lib-books-v1-20260810",
    feedback_service: object | None = None,
    behavior_service: object | None = None,
    readiness_probe: object | None = None,
    config_bundle_probe: object | None = None,
    feedback_api_enabled: bool = False,
) -> FastAPI:
    """Compose the local MySQL-backed G3 HTTP graph without opening a connection.

    The HTTP port is implemented by ``MySQLRecommendationTaskService`` and is
    therefore distinct from the G4 ``PersistentOrchestrationService`` run port.
    The default module-level app never calls this function.
    """

    recommendation_service = MySQLRecommendationTaskService(
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        user=settings.mysql_user,
        password=settings.mysql_password.get_secret_value(),
        connect_timeout=settings.mysql_connect_timeout_seconds,
        catalog_repository_factory=MySQLCatalogRepository,
        config_bundle_version=settings.config_bundle_version,
        dataset_version=dataset_version,
    )
    return build_demo_http_app(
        settings,
        recommendation_service=recommendation_service,
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        readiness_probe=readiness_probe,
        config_bundle_probe=config_bundle_probe,
        feedback_api_enabled=feedback_api_enabled,
    )


def build_research_orchestration_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
    enable_llm_provider: bool = False,
    graph: GraphRecallPort | None = None,
    graph_version: str | None = None,
    vector: VectorRecallPort | None = None,
    query_embedder: QueryEmbeddingPort | None = None,
    embedding_version: str | None = None,
    index_version: str | None = None,
) -> PersistentOrchestrationService:
    """Build the explicit research path while rejecting production by default."""

    if settings.app_env == "production":
        raise ValueError("research orchestration requires a non-production environment")
    return _build_mysql_orchestration_service(
        settings,
        connection_factory=connection_factory,
        enable_llm_provider=enable_llm_provider,
        graph=graph,
        graph_version=graph_version,
        vector=vector,
        query_embedder=query_embedder,
        embedding_version=embedding_version,
        index_version=index_version,
    )


def build_research_g4_recommendation_service(
    settings: AppSettings,
    *,
    dataset_version: str = "lib-books-v1-20260810",
    connection_factory: ConnectionFactory | None = None,
    graph: GraphRecallPort | None = None,
    graph_version: str | None = None,
    vector: VectorRecallPort | None = None,
    query_embedder: QueryEmbeddingPort | None = None,
    embedding_version: str | None = None,
    index_version: str | None = None,
    enable_llm_provider: bool = False,
    enable_llm_intent_provider: bool = False,
    enable_llm_explanation_provider: bool = False,
    deadline_seconds: float = 30.0,
) -> MySQLG4RecommendationTaskService:
    """Build the explicit G4 RecommendationTaskService without HTTP wiring.

    This composition root is intentionally separate from
    ``build_demo_mysql_http_app``.  It opens no connection during construction;
    the caller must explicitly pass the resulting service to a reviewed HTTP
    graph and keep the default health-only app unchanged.
    """

    if settings.app_env == "production":
        raise ValueError("G4 recommendation composition requires a non-production environment")
    llm_provider = (
        build_llm_provider(settings)
        if (
            enable_llm_provider
            or enable_llm_intent_provider
            or enable_llm_explanation_provider
        )
        else None
    )

    def orchestrator_factory(connection: Any) -> RecommendationOrchestrator:
        return build_port_orchestrator(
            MySQLCatalogRepository(connection),
            MySQLProfileSnapshotReader(connection),
            graph=graph,
            graph_version=graph_version,
            vector=vector,
            query_embedder=query_embedder,
            embedding_version=embedding_version,
            index_version=index_version,
            retry_policy=RetryPolicy(max_attempts=2),
            llm_provider=llm_provider if enable_llm_provider else None,
            llm_intent_provider=(
                llm_provider if enable_llm_intent_provider else None
            ),
            llm_explanation_provider=(
                llm_provider if enable_llm_explanation_provider else None
            ),
        )

    return MySQLG4RecommendationTaskService(
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        user=settings.mysql_user,
        password=settings.mysql_password.get_secret_value(),
        catalog_repository_factory=MySQLCatalogRepository,
        orchestrator_factory=orchestrator_factory,
        config_bundle_version=getattr(settings, "config_bundle_version", "rec-1.0.0"),
        dataset_version=dataset_version,
        graph_version=graph_version,
        embedding_version=embedding_version,
        index_version=index_version,
        prompt_version=getattr(settings, "prompt_bundle_version", None),
        deadline_seconds=deadline_seconds,
        connect_timeout=settings.mysql_connect_timeout_seconds,
        connection_factory=connection_factory,
    )


def build_research_g4_http_app(
    settings: AppSettings,
    *,
    recommendation_service: object | None,
    feedback_service: object | None = None,
    behavior_service: object | None = None,
    readiness_probe: object | None = None,
    config_bundle_probe: object | None = None,
    component_readiness_probes: dict[str, object] | None = None,
    component_readiness_overrides: dict[str, ComponentReadiness] | None = None,
    feedback_api_enabled: bool = False,
    exploration_service: object | None = None,
    recommendation_progress_broker: object | None = None,
    agent_workspace_broker: object | None = None,
    identity_service: IdentityService | None = None,
    knowledge_review_service: KnowledgeReviewService | None = None,
) -> FastAPI:
    """Compose the explicit G4 HTTP graph around injected application ports.

    This boundary deliberately does not construct a Neo4j/Chroma client or
    enable the DeepSeek provider. The caller must inject version-pinned,
    read-only graph/vector ports into ``recommendation_service`` and choose
    the LLM policy in the separate G4 service composition. The default
    ``backend.app.main:app`` and Compose command never call this function.
    """

    if settings.app_env == "production":
        raise ValueError("G4 research HTTP composition requires a non-production environment")
    if not bool(getattr(settings, "g4_http_enabled", False)):
        raise ValueError("G4 HTTP composition is disabled by configuration")
    if recommendation_service is None:
        raise ValueError("G4 HTTP composition requires recommendation service")
    if feedback_api_enabled and (feedback_service is None or behavior_service is None):
        raise ValueError(
            "G4 feedback API requires both feedback and behavior services"
        )
    if identity_service is not None and not settings.local_identity_api_enabled:
        raise ValueError("identity service requires the explicit local identity API switch")
    principal_resolver = (
        build_local_identity_principal_resolver(settings, identity_service)
        if identity_service is not None else None
    )

    from backend.app.main import create_app

    return create_app(
        settings=settings,
        readiness_probe=readiness_probe,
        config_bundle_probe=config_bundle_probe,
        recommendation_service=recommendation_service,
        recommendation_api_enabled=True,
        recommendation_readiness_enabled=True,
        recommendation_version="recommendation-g4-graph-vector-v1",
        component_readiness_probes=component_readiness_probes,
        component_readiness_overrides=component_readiness_overrides,
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        feedback_api_enabled=feedback_api_enabled,
        debug_api_enabled=False,
        exploration_service=exploration_service,
        exploration_api_enabled=exploration_service is not None,
        recommendation_progress_broker=recommendation_progress_broker,
        agent_workspace_broker=agent_workspace_broker,
        identity_service=identity_service,
        identity_api_enabled=identity_service is not None,
        principal_resolver=principal_resolver,
        knowledge_review_service=knowledge_review_service,
        knowledge_review_api_enabled=knowledge_review_service is not None,
    )


def build_research_g4_recommendation_service_from_runtime(
    settings: AppSettings,
    *,
    runtime: G4ReadOnlyRuntime,
    dataset_version: str = "lib-books-v1-20260810",
    connection_factory: ConnectionFactory | None = None,
    enable_llm_provider: bool = False,
    enable_llm_intent_provider: bool = False,
    enable_llm_explanation_provider: bool = False,
    deadline_seconds: float = 120.0,
) -> MySQLG4RecommendationTaskService:
    """Build G4 service with an explicit, version-pinned read-only runtime."""

    return build_research_g4_recommendation_service(
        settings,
        dataset_version=dataset_version,
        connection_factory=connection_factory,
        graph=runtime.graph,
        graph_version=runtime.graph_version,
        vector=runtime.vector,
        query_embedder=runtime.query_embedder,
        embedding_version=runtime.embedding_version,
        index_version=runtime.index_version,
        enable_llm_provider=enable_llm_provider,
        enable_llm_intent_provider=enable_llm_intent_provider,
        enable_llm_explanation_provider=enable_llm_explanation_provider,
        deadline_seconds=deadline_seconds,
    )


def build_research_g4_http_app_from_runtime(
    settings: AppSettings,
    *,
    runtime: G4ReadOnlyRuntime,
    dataset_version: str = "lib-books-v1-20260810",
    connection_factory: ConnectionFactory | None = None,
    enable_llm_provider: bool = False,
    enable_llm_intent_provider: bool = False,
    enable_llm_explanation_provider: bool = False,
    deadline_seconds: float = 120.0,
    feedback_service: object | None = None,
    behavior_service: object | None = None,
    readiness_probe: object | None = None,
    config_bundle_probe: object | None = None,
    feedback_api_enabled: bool = False,
    exploration_service: object | None = None,
    recommendation_progress_broker: object | None = None,
    agent_workspace_broker: object | None = None,
    identity_service: IdentityService | None = None,
    knowledge_review_service: KnowledgeReviewService | None = None,
    knowledge_review_provider: str | None = None,
) -> FastAPI:
    """Compose G4 HTTP from explicit Graph/Vector ports and one service."""

    recommendation_service = build_research_g4_recommendation_service_from_runtime(
        settings,
        runtime=runtime,
        dataset_version=dataset_version,
        connection_factory=connection_factory,
        enable_llm_provider=enable_llm_provider,
        enable_llm_intent_provider=enable_llm_intent_provider,
        enable_llm_explanation_provider=enable_llm_explanation_provider,
        deadline_seconds=deadline_seconds,
    )

    async def check_graph() -> object:
        return await runtime.graph.recall(
            terms=("__recpro_readiness__",),
            graph_version=runtime.graph_version,
            limit=1,
        )

    async def check_vector() -> object:
        return await runtime.vector.recall(
            query_vector=runtime.query_embedder.embed("recpro readiness"),
            embedding_version=runtime.embedding_version,
            index_version=runtime.index_version,
            limit=1,
        )

    llm_enabled = (
        enable_llm_provider
        or enable_llm_intent_provider
        or enable_llm_explanation_provider
    )
    component_probes = {
        "neo4j": AsyncOperationReadinessProbe(
            operation=check_graph,
            required=False,
            active_version=runtime.graph_version,
            error_code="GRAPH_READINESS_FAILED",
        ),
        "chroma": AsyncOperationReadinessProbe(
            operation=check_vector,
            required=False,
            active_version=runtime.index_version,
            error_code="VECTOR_READINESS_FAILED",
        ),
    }
    component_overrides = {
        "llm": ComponentReadiness(
            status=ComponentStatus.UP if llm_enabled else ComponentStatus.MOCK,
            required=False,
            active_version=settings.llm_model if llm_enabled else "mock-v1",
            provider=settings.llm_provider if llm_enabled else "MockLLMProvider",
        ),
        "interaction_pipeline": ComponentReadiness(
            status=ComponentStatus.UP if feedback_api_enabled else ComponentStatus.DISABLED,
            required=False,
            active_version="feedback-g5-v1" if feedback_api_enabled else None,
            provider="FeedbackLearningAgent" if feedback_api_enabled else None,
        ),
    }
    if knowledge_review_service is not None:
        component_overrides["knowledge_review"] = ComponentReadiness(
            status=ComponentStatus.UP,
            required=False,
            active_version="knowledge-review-g12-v1",
            provider=knowledge_review_provider or "configured-repository",
        )
    return build_research_g4_http_app(
        settings,
        recommendation_service=recommendation_service,
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        readiness_probe=readiness_probe,
        config_bundle_probe=config_bundle_probe,
        component_readiness_probes=component_probes,
        component_readiness_overrides=component_overrides,
        feedback_api_enabled=feedback_api_enabled,
        exploration_service=exploration_service,
        recommendation_progress_broker=recommendation_progress_broker,
        agent_workspace_broker=agent_workspace_broker,
        identity_service=identity_service,
        knowledge_review_service=knowledge_review_service,
    )


def build_local_knowledge_review_service(
    proposal_path: str | None = None,
) -> KnowledgeReviewService:
    """Build the pre-migration, bounded in-memory librarian review service."""

    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    path = Path(proposal_path) if proposal_path else project_root / (
        "artifacts/verification/book-graph-v2/lib-books-v2-20260828/review-proposals.jsonl"
    )
    proposals = load_v2_review_proposals(path)
    return KnowledgeReviewService(InMemoryKnowledgeReviewRepository(proposals))


def build_mysql_knowledge_review_service(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> KnowledgeReviewService:
    """Build the real G12 repository without opening a database connection.

    Reads use SELECT and librarian actions use the adapter's append-only
    ``INSERT IGNORE`` boundary.  Keeping construction connection-free lets the
    research composition remain fail-closed until an authenticated request
    reaches the explicitly mounted librarian API.
    """

    factory = connection_factory or _mysql_connection_factory(settings)
    return KnowledgeReviewService(MySQLKnowledgeReviewRepository(factory))


def build_research_exploration_service(
    settings: AppSettings,
    *,
    graph_endpoint: str,
    graph_username: str,
    graph_password: str,
    graph_version: str,
) -> ExplorationService:
    """Compose read-only MySQL/Neo4j exploration without mounting routes."""

    if settings.app_env == "production":
        raise ValueError("research exploration requires a non-production environment")
    return ExplorationService(
        catalog_reader=MySQLCatalogReader(connection_factory=_mysql_connection_factory(settings)),
        graph_reader=PublicGraphReader(
            endpoint=graph_endpoint,
            username=graph_username,
            password=graph_password,
            graph_version=graph_version,
            timeout=3.0,
        ),
        cache_seconds=300.0,
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


def build_agent_workspace_audit_worker(
    settings: AppSettings,
    *,
    buffer: AgentWorkspaceAuditBuffer,
    connection_factory: ConnectionFactory | None = None,
) -> AgentWorkspaceAuditWorker:
    """Construct, but never start, the separately approved append-only worker.

    The returned worker opens no connection until an explicit operator calls
    ``drain_once``.  Runtime configuration validation supplies the independent
    plan/hash/run-identity gate before this builder can be reached.
    """

    if not settings.agent_workspace_audit_enabled:
        raise ValueError("workspace audit worker requires the explicit audit switch")
    if settings.app_env != "demo":
        raise ValueError("workspace audit worker requires the demo research runtime")
    return AgentWorkspaceAuditWorker(
        buffer=buffer,
        adapter=MySQLAgentWorkspaceAuditAdapter(),
        connection_factory=connection_factory or _mysql_connection_factory(settings),
        max_batch=settings.agent_workspace_audit_batch_limit,
    )


def build_agent_workspace_profile_reader(
    settings: AppSettings,
) -> MySQLWorkspaceProfileReader:
    """Build a connection-on-use, rollback-only profile summary reader."""

    if settings.app_env == "production":
        raise ValueError("workspace profile reader requires a reviewed non-production root")
    return MySQLWorkspaceProfileReader(_mysql_connection_factory(settings))


def build_profile_outbox_worker(
    settings: AppSettings,
    *,
    connection_factory: ConnectionFactory,
    worker_id: str,
    formula_version: str = "profile-g2-v1",
    lease_seconds: int = 60,
    max_attempts: int = 3,
    allowed_outbox_ids: tuple[int, ...] | None = None,
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
        lease_seconds=lease_seconds,
        max_attempts=max_attempts,
        allowed_outbox_ids=allowed_outbox_ids,
    )


__all__ = [
    "build_agent_workspace_audit_worker",
    "build_agent_workspace_profile_reader",
    "build_local_knowledge_review_service",
    "build_formal_auth_resolver",
    "build_production_http_app",
    "build_demo_http_app",
    "build_profile_outbox_worker",
    "build_demo_orchestration_service",
    "build_demo_mysql_http_app",
    "build_research_behavior_service",
    "build_research_feedback_service",
    "build_research_orchestration_service",
    "build_research_g4_recommendation_service",
    "build_research_g4_http_app",
    "build_research_g4_recommendation_service_from_runtime",
    "build_research_g4_http_app_from_runtime",
    "build_research_exploration_service",
]
