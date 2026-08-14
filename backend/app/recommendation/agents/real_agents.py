"""Port-backed read-only Agents for the G4 composition-root slice."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid5

from backend.app.catalog.ports.public import (
    CatalogRepository,
    GraphRecallPort,
    QueryEmbeddingPort,
    VectorRecallPort,
)
from backend.app.shared_kernel.contracts.autonomy import (
    attach_decision,
    default_decision,
    validate_decision,
)
from backend.app.profile.ports.public import ProfileSnapshotReader
from backend.app.recommendation.agents.base import (
    Agent,
    DependencyCallFailed,
    RetryPolicy,
    call_with_retry,
)
from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult
from backend.app.shared_kernel.contracts.agent import AgentDecision
from backend.app.shared_kernel.contracts.enums import AgentActionType, AgentResultStatus


def _evaluation_at(message: AgentMessage) -> datetime:
    value = message.payload.get("evaluation_at")
    if not isinstance(value, str) or not value.strip():
        return message.created_at
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("evaluation_at must be timezone-aware")
    return parsed.astimezone(UTC)


def _result(
    message: AgentMessage,
    *,
    agent_name: str,
    agent_version: str,
    payload: dict[str, object],
    confidence: float,
    status: AgentResultStatus = AgentResultStatus.SUCCESS,
    warnings: tuple[str, ...] = (),
    fallback_used: bool = False,
    tool_calls: tuple[dict[str, object], ...] = (),
    decision: AgentDecision | None = None,
) -> AgentResult[dict[str, object]]:
    resolved_decision = validate_decision(
        agent_name,
        decision
        or default_decision(
            agent_name,
            status=status,
            fallback_used=fallback_used,
        ),
    )
    return AgentResult(
        result_id=uuid5(message.message_id, f"result:{agent_name}:{message.attempt}"),
        input_message_id=message.message_id,
        agent_name=agent_name,
        agent_version=agent_version,
        status=status,
        confidence=max(0.0, min(1.0, confidence)),
        payload=attach_decision(dict(payload), resolved_decision),
        evidence_refs=(f"port:{agent_name}:{agent_version}",),
        warnings=warnings,
        fallback_used=fallback_used,
        tool_calls=tool_calls,
        duration_ms=0,
        decision=resolved_decision,
    )


def _failure_metadata(error: DependencyCallFailed) -> tuple[dict[str, object], ...]:
    return (
        {
            "operation": error.operation,
            "attempts": error.attempts,
            "outcome": "TIMEOUT" if error.timed_out else "RETRY_EXHAUSTED",
        },
    )


class MySQLProfileAgent:
    """Read a versioned profile projection through a profile port."""

    name = "UserProfileAgent"
    version = "profile-mysql-v1"

    def __init__(
        self,
        reader: ProfileSnapshotReader,
        *,
        retry_policy: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._reader = reader
        self._retry_policy = retry_policy

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        as_of = _evaluation_at(message)
        try:
            snapshot, attempts = await call_with_retry(
                lambda: self._reader.get_snapshot(
                    user_id=int(message.payload["user_id"]), as_of=as_of
                ),
                operation_name="profile.get_snapshot",
                deadline_at=message.deadline_at,
                policy=self._retry_policy,
            )
        except DependencyCallFailed as error:
            return _result(
                message,
                agent_name=self.name,
                agent_version=self.version,
                payload={
                    "profile_version": "profile-fallback-v1",
                    "confidence": 0.0,
                    "event_count": 0,
                    "signals": [],
                    "negative_signals": [],
                    "profile_empty": True,
                },
                confidence=0.1,
                status=AgentResultStatus.PARTIAL,
                warnings=("PROFILE_READ_UNAVAILABLE",),
                fallback_used=True,
                tool_calls=_failure_metadata(error),
                decision=AgentDecision(
                    action=AgentActionType.FALLBACK,
                    target="RecommendationOrchestrator",
                    reason_code="PROFILE_READ_UNAVAILABLE",
                    confidence=0.1,
                ),
            )
        signals = [
            {"tag_id": signal.tag_id, "weight": signal.weight, "negative": False}
            for signal in snapshot.interests
        ]
        negative_signals = [
            {
                "tag_id": signal.tag_id,
                "weight": signal.weight,
                "negative": True,
                "reason_code": signal.reason_code,
            }
            for signal in snapshot.negatives
        ]
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "profile_version": f"{snapshot.formula_version}:{snapshot.event_count}",
                "confidence": snapshot.profile_confidence,
                "event_count": snapshot.event_count,
                "signals": signals,
                "negative_signals": negative_signals,
                "recent_focus_tag_id": snapshot.recent_focus_tag_id,
                "topic_focus_strength": snapshot.topic_focus_strength,
                "input_hash": snapshot.input_hash,
            },
            confidence=snapshot.profile_confidence,
            warnings=("PROFILE_PROJECTION_CURRENT_AS_OF",) if snapshot.as_of != as_of else (),
            fallback_used=False,
            tool_calls=({"operation": "profile.get_snapshot", "attempts": attempts, "outcome": "SUCCESS"},),
            decision=AgentDecision(
                action=AgentActionType.READ_PROFILE,
                target="RecommendationOrchestrator",
                reason_code="PROFILE_SNAPSHOT_READY",
                confidence=snapshot.profile_confidence,
            ),
        )


class CatalogResourceSemanticAgent:
    """Probe real Catalog metadata through read-only repository methods."""

    name = "ResourceSemanticAgent"
    version = "semantic-mysql-v1"

    def __init__(
        self,
        catalog: CatalogRepository,
        *,
        graph: GraphRecallPort | None = None,
        vector: VectorRecallPort | None = None,
        retry_policy: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._catalog = catalog
        self._graph_enabled = graph is not None
        self._vector_enabled = vector is not None
        self._retry_policy = retry_policy

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        as_of = _evaluation_at(message)
        try:
            resources, resource_attempts = await call_with_retry(
                lambda: self._catalog.list_resources(available_at=as_of),
                operation_name="catalog.list_resources.probe",
                deadline_at=message.deadline_at,
                policy=self._retry_policy,
            )
            tags, tag_attempts = await call_with_retry(
                lambda: self._catalog.list_resource_tags(
                    resource_ids=tuple(resource.id for resource in resources)
                ),
                operation_name="catalog.list_resource_tags.probe",
                deadline_at=message.deadline_at,
                policy=self._retry_policy,
            )
        except DependencyCallFailed as error:
            return _result(
                message,
                agent_name=self.name,
                agent_version=self.version,
                payload={
                    "metadata_coverage": 0.25,
                    "vector_coverage": 0.0,
                    "kg_path_coverage": 0.0,
                    "catalog_count": 0,
                    "tag_count": 0,
                    "required_slots": [],
                    "dependency_status": {
                        "MYSQL": "UNAVAILABLE",
                        "VECTOR": "READY" if self._vector_enabled else "DISABLED",
                        "GRAPH": "READY" if self._graph_enabled else "DISABLED",
                    },
                },
                confidence=0.2,
                status=AgentResultStatus.PARTIAL,
                warnings=("CATALOG_READ_UNAVAILABLE",),
                fallback_used=True,
                tool_calls=_failure_metadata(error),
                decision=AgentDecision(
                    action=AgentActionType.DEGRADE,
                    target="RecommendationPolicyAgent",
                    reason_code="CATALOG_READ_UNAVAILABLE",
                    confidence=0.2,
                ),
            )
        metadata_coverage = (
            sum(max(0.0, min(1.0, resource.metadata_quality)) for resource in resources)
            / len(resources)
            if resources
            else 0.0
        )
        tagged_resource_ids = {tag.resource_id for tag in tags}
        tag_coverage = len(tagged_resource_ids) / len(resources) if resources else 0.0
        warnings = ("CATALOG_EMPTY",) if not resources else ()
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "metadata_coverage": metadata_coverage,
                "vector_coverage": 0.0,
                "kg_path_coverage": 0.0,
                "catalog_count": len(resources),
                "tag_count": len(tags),
                "tag_coverage": tag_coverage,
                "required_slots": [],
                "dependency_status": {
                    "MYSQL": "READY",
                    "VECTOR": "READY" if self._vector_enabled else "DISABLED",
                    "GRAPH": "READY" if self._graph_enabled else "DISABLED",
                },
            },
            confidence=metadata_coverage,
            status=AgentResultStatus.PARTIAL if not resources else AgentResultStatus.SUCCESS,
            warnings=warnings,
            fallback_used=False,
            tool_calls=(
                {"operation": "catalog.list_resources.probe", "attempts": resource_attempts, "outcome": "SUCCESS"},
                {"operation": "catalog.list_resource_tags.probe", "attempts": tag_attempts, "outcome": "SUCCESS"},
            ),
            decision=AgentDecision(
                action=AgentActionType.PROBE_RESOURCES,
                target="RecommendationPolicyAgent",
                reason_code="RESOURCE_PROBE_READY" if resources else "CATALOG_EMPTY",
                confidence=metadata_coverage,
            ),
        )


class CatalogCandidateRecallAgent:
    """Recall deterministic candidates from the real Catalog port."""

    name = "CandidateRecallAgent"
    version = "recall-mysql-v3"

    def __init__(
        self,
        catalog: CatalogRepository,
        *,
        graph: GraphRecallPort | None = None,
        graph_version: str | None = None,
        vector: VectorRecallPort | None = None,
        query_embedder: QueryEmbeddingPort | None = None,
        embedding_version: str | None = None,
        index_version: str | None = None,
        retry_policy: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._catalog = catalog
        self._graph = graph
        self._graph_version = graph_version
        self._vector = vector
        self._query_embedder = query_embedder
        self._embedding_version = embedding_version
        self._index_version = index_version
        self._retry_policy = retry_policy

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        as_of = _evaluation_at(message)
        intent = message.payload.get("intent", {})
        requested_types = {
            str(value) for value in intent.get("resource_types", [])
        } if isinstance(intent, dict) else set()
        terms = {
            str(value).lower()
            for value in (intent.get("topic_terms", []) if isinstance(intent, dict) else [])
            if str(value).strip()
        }
        limit = max(1, min(int(message.payload.get("limit", 5)), 20))
        try:
            resources, resource_attempts = await call_with_retry(
                lambda: self._catalog.list_resources(available_at=as_of),
                operation_name="catalog.list_resources.recall",
                deadline_at=message.deadline_at,
                policy=self._retry_policy,
            )
            eligible = tuple(
                resource for resource in resources
                if not requested_types or resource.resource_type in requested_types
            )
            tags, tag_attempts = await call_with_retry(
                lambda: self._catalog.list_resource_tags(
                    resource_ids=tuple(resource.id for resource in eligible)
                ),
                operation_name="catalog.list_resource_tags.recall",
                deadline_at=message.deadline_at,
                policy=self._retry_policy,
            )
        except DependencyCallFailed as error:
            return _result(
                message,
                agent_name=self.name,
                agent_version=self.version,
                payload={"candidates": [], "candidate_count": 0, "channels": ["MYSQL"]},
                confidence=0.1,
                status=AgentResultStatus.PARTIAL,
                warnings=("CATALOG_RECALL_UNAVAILABLE",),
                fallback_used=True,
                tool_calls=_failure_metadata(error),
                decision=AgentDecision(
                    action=AgentActionType.DEGRADE,
                    target="RankingAgent",
                    reason_code="CATALOG_RECALL_UNAVAILABLE",
                    confidence=0.1,
                ),
            )
        tags_by_resource: dict[int, list[Any]] = {}
        for tag in tags:
            tags_by_resource.setdefault(tag.resource_id, []).append(tag)
        profile = message.payload.get("profile", {})
        profile_weights = {
            int(signal["tag_id"]): float(signal.get("weight", 0.0))
            for signal in (profile.get("signals", []) if isinstance(profile, dict) else [])
            if isinstance(signal, dict) and signal.get("tag_id") is not None
        }
        negative_profile_weights = {
            int(signal["tag_id"]): float(signal.get("weight", 0.0))
            for signal in (
                profile.get("negative_signals", []) if isinstance(profile, dict) else []
            )
            if isinstance(signal, dict) and signal.get("tag_id") is not None
        }
        graph_hits: dict[str, Any] = {}
        graph_attempts = 0
        graph_warning: tuple[str, ...] = ()
        graph_tool_calls: tuple[dict[str, object], ...] = ()
        if self._graph is not None and self._graph_version and terms:
            try:
                graph_results, graph_attempts = await call_with_retry(
                    lambda: self._graph.recall(
                        terms=tuple(sorted(terms)),
                        graph_version=self._graph_version or "",
                        limit=limit,
                    ),
                    operation_name="catalog.graph_recall",
                    deadline_at=message.deadline_at,
                    policy=self._retry_policy,
                )
                graph_hits = {item.external_id: item for item in graph_results}
                graph_tool_calls = (
                    {
                        "operation": "catalog.graph_recall",
                        "attempts": graph_attempts,
                        "outcome": "SUCCESS",
                    },
                )
            except DependencyCallFailed as error:
                graph_warning = ("GRAPH_RECALL_UNAVAILABLE",)
                graph_attempts = error.attempts
                graph_tool_calls = _failure_metadata(error)
        vector_hits: dict[str, Any] = {}
        vector_attempts = 0
        vector_warning: tuple[str, ...] = ()
        vector_tool_calls: tuple[dict[str, object], ...] = ()
        vector_configured = all(
            value is not None
            for value in (
                self._vector,
                self._query_embedder,
                self._embedding_version,
                self._index_version,
            )
        )
        query_text = str(message.payload.get("query_text") or " ".join(sorted(terms))).strip()
        if vector_configured and query_text:
            try:
                query_vector = self._query_embedder.embed(query_text)  # type: ignore[union-attr]
                vector_results, vector_attempts = await call_with_retry(
                    lambda: self._vector.recall(  # type: ignore[union-attr]
                        query_vector=query_vector,
                        embedding_version=self._embedding_version or "",
                        index_version=self._index_version or "",
                        limit=limit,
                    ),
                    operation_name="catalog.vector_recall",
                    deadline_at=message.deadline_at,
                    policy=self._retry_policy,
                )
                vector_hits = {item.external_id: item for item in vector_results}
                vector_tool_calls = (
                    {
                        "operation": "catalog.vector_recall",
                        "attempts": vector_attempts,
                        "outcome": "SUCCESS",
                    },
                )
            except DependencyCallFailed as error:
                vector_warning = ("VECTOR_RECALL_UNAVAILABLE",)
                vector_attempts = error.attempts
                vector_tool_calls = _failure_metadata(error)
            except ValueError:
                vector_warning = ("VECTOR_QUERY_UNAVAILABLE",)
        graph_configured = self._graph is not None and bool(self._graph_version)
        optional_channel_configured = graph_configured or vector_configured
        graph_channel_ready = graph_configured and not graph_warning and bool(terms)
        vector_channel_ready = vector_configured and not vector_warning and bool(query_text)
        candidates: list[dict[str, object]] = []
        resources_by_id = {resource.id: resource for resource in eligible}
        for resource in eligible:
            searchable = " ".join((resource.title, *resource.keywords)).lower()
            keyword_score = (
                sum(1 for term in terms if term in searchable) / max(1, len(terms))
                if terms
                else 0.0
            )
            profile_score = min(
                1.0,
                sum(
                    tag.weight * tag.confidence * profile_weights.get(tag.tag_id, 0.0)
                    for tag in tags_by_resource.get(resource.id, ())
                ),
            )
            negative_penalty = min(
                1.0,
                sum(
                    tag.weight
                    * tag.confidence
                    * negative_profile_weights.get(tag.tag_id, 0.0)
                    for tag in tags_by_resource.get(resource.id, ())
                ),
            )
            graph_hit = graph_hits.get(resource.external_id)
            graph_score = float(graph_hit.score) if graph_hit is not None else 0.0
            vector_hit = vector_hits.get(resource.external_id)
            vector_score = float(vector_hit.score) if vector_hit is not None else 0.0
            mysql_weighted_score = 0.50 * keyword_score + 0.25 * profile_score
            weighted_score = mysql_weighted_score
            effective_weight = 0.75
            if graph_channel_ready:
                weighted_score += 0.15 * graph_score
                effective_weight += 0.15
            if vector_channel_ready:
                weighted_score += 0.10 * vector_score
                effective_weight += 0.10
            base_score = (
                weighted_score / effective_weight
                if optional_channel_configured
                else weighted_score
            )
            score = max(0.0, min(1.0, base_score - 0.35 * negative_penalty))
            channels = ["MYSQL"]
            channel_scores: dict[str, float] = {
                "MYSQL": round(min(1.0, mysql_weighted_score / 0.75), 6)
            }
            evidence_ref = f"catalog:resource:{resource.id}:metadata:{resource.metadata_version}"
            if graph_hit is not None:
                channels.append("GRAPH")
                channel_scores["GRAPH"] = round(max(0.0, min(1.0, graph_score)), 6)
                evidence_ref += f":graph:{graph_hit.graph_version}"
            if vector_hit is not None:
                channels.append("VECTOR")
                channel_scores["VECTOR"] = round(max(0.0, min(1.0, vector_score)), 6)
                evidence_ref += f":vector:{vector_hit.index_version}"
            candidates.append(
                {
                    "resource_id": resource.id,
                    "channel": "+".join(channels),
                    "score": round(score, 6),
                    "negative_penalty": round(negative_penalty, 6),
                    "evidence_ref": evidence_ref,
                    "channel_scores": channel_scores,
                    # ``None`` means the optional channel was unavailable or
                    # did not participate.  A successful graph query with no
                    # hit is represented by ``0.0`` instead, so downstream
                    # explanations cannot turn a timeout into a graph fact.
                    "kg_score": (
                        round(max(0.0, min(1.0, graph_score)), 6)
                        if graph_channel_ready
                        else None
                    ),
                    "semantic_score": (
                        round(max(0.0, min(1.0, vector_score)), 6)
                        if vector_channel_ready
                        else None
                    ),
                }
            )
        channel_ranks: dict[str, dict[int, int]] = {}
        for channel in sorted(
            {
                str(name)
                for candidate in candidates
                for name in dict(candidate["channel_scores"]).keys()
            }
        ):
            ranked = sorted(
                candidates,
                key=lambda item: (
                    -float(dict(item["channel_scores"]).get(channel, 0.0)),
                    int(item["resource_id"]),
                ),
            )
            channel_ranks[channel] = {
                int(item["resource_id"]): index
                for index, item in enumerate(ranked, start=1)
            }
        for candidate in candidates:
            resource_id = int(candidate["resource_id"])
            scores = {
                str(name): float(value)
                for name, value in dict(candidate["channel_scores"]).items()
            }
            ranks = {
                channel: channel_ranks[channel][resource_id]
                for channel in scores
            }
            metadata_quality = max(
                0.0,
                min(1.0, float(resources_by_id[resource_id].metadata_quality)),
            )
            coverage = len(scores) / 3.0
            candidate["channel_ranks"] = ranks
            candidate["primary_channel"] = max(
                scores,
                key=lambda channel: (scores[channel], -ranks[channel], channel),
            )
            candidate["evidence_confidence"] = round(
                max(
                    0.0,
                    min(
                        1.0,
                        0.55 * metadata_quality
                        + 0.25 * max(scores.values(), default=0.0)
                        + 0.20 * coverage
                        - 0.20 * float(candidate.get("negative_penalty", 0.0)),
                    ),
                ),
                6,
            )
        candidates.sort(key=lambda item: (-float(item["score"]), int(item["resource_id"])))
        positive_candidates = [
            candidate for candidate in candidates if float(candidate["score"]) > 0.0
        ]
        selected = positive_candidates[:limit]
        coverage_warning = (
            ("INSUFFICIENT_POSITIVE_SCORE_COVERAGE",)
            if 0 < len(selected) < limit
            else ()
        )
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "candidates": selected,
                "candidate_count": len(selected),
                "channels": ["MYSQL"]
                + (["GRAPH"] if graph_hits else [])
                + (["VECTOR"] if vector_hits else []),
                "dependency_status": {
                    "MYSQL": "READY",
                    "GRAPH": "READY" if graph_channel_ready else ("UNAVAILABLE" if graph_warning else "DISABLED"),
                    "VECTOR": "READY" if vector_channel_ready else ("UNAVAILABLE" if vector_warning else "DISABLED"),
                },
            },
            confidence=0.8 if selected else 0.3,
            status=AgentResultStatus.PARTIAL
            if (not selected or coverage_warning or graph_warning or vector_warning)
            else AgentResultStatus.SUCCESS,
            warnings=(("CATALOG_EMPTY",) if not selected else ())
            + coverage_warning
            + graph_warning
            + vector_warning,
            fallback_used=bool(coverage_warning or graph_warning or vector_warning),
            tool_calls=(
                {"operation": "catalog.list_resources.recall", "attempts": resource_attempts, "outcome": "SUCCESS"},
                {"operation": "catalog.list_resource_tags.recall", "attempts": tag_attempts, "outcome": "SUCCESS"},
            )
            + graph_tool_calls
            + vector_tool_calls,
            decision=AgentDecision(
                action=AgentActionType.DEGRADE
                if (coverage_warning or graph_warning or vector_warning or not selected)
                else AgentActionType.SELECT_CHANNELS,
                target="RankingAgent",
                reason_code=(
                    "OPTIONAL_CHANNEL_DEGRADED"
                    if (graph_warning or vector_warning)
                    else "INSUFFICIENT_POSITIVE_SCORE_COVERAGE"
                    if coverage_warning
                    else "CATALOG_EMPTY"
                    if not selected
                    else "RECALL_CHANNELS_SELECTED"
                ),
                confidence=0.3 if not selected else 0.8,
            ),
        )


__all__ = [
    "CatalogCandidateRecallAgent",
    "CatalogResourceSemanticAgent",
    "MySQLProfileAgent",
]
