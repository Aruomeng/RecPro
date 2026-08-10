"""Port-backed read-only Agents for the G4 composition-root slice."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid5

from backend.app.catalog.ports.public import CatalogRepository, GraphRecallPort
from backend.app.profile.ports.public import ProfileSnapshotReader
from backend.app.recommendation.agents.base import (
    Agent,
    DependencyCallFailed,
    RetryPolicy,
    call_with_retry,
)
from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult
from backend.app.shared_kernel.contracts.enums import AgentResultStatus


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
) -> AgentResult[dict[str, object]]:
    return AgentResult(
        result_id=uuid5(message.message_id, f"result:{agent_name}:{message.attempt}"),
        input_message_id=message.message_id,
        agent_name=agent_name,
        agent_version=agent_version,
        status=status,
        confidence=max(0.0, min(1.0, confidence)),
        payload=payload,
        evidence_refs=(f"port:{agent_name}:{agent_version}",),
        warnings=warnings,
        fallback_used=fallback_used,
        tool_calls=tool_calls,
        duration_ms=0,
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
        )


class CatalogResourceSemanticAgent:
    """Probe real Catalog metadata through read-only repository methods."""

    name = "ResourceSemanticAgent"
    version = "semantic-mysql-v1"

    def __init__(
        self,
        catalog: CatalogRepository,
        *,
        retry_policy: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._catalog = catalog
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
                    "dependency_status": {"MYSQL": "UNAVAILABLE", "VECTOR": "DISABLED", "GRAPH": "DISABLED"},
                },
                confidence=0.2,
                status=AgentResultStatus.PARTIAL,
                warnings=("CATALOG_READ_UNAVAILABLE",),
                fallback_used=True,
                tool_calls=_failure_metadata(error),
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
                "dependency_status": {"MYSQL": "READY", "VECTOR": "DISABLED", "GRAPH": "DISABLED"},
            },
            confidence=metadata_coverage,
            status=AgentResultStatus.PARTIAL if not resources else AgentResultStatus.SUCCESS,
            warnings=warnings,
            fallback_used=False,
            tool_calls=(
                {"operation": "catalog.list_resources.probe", "attempts": resource_attempts, "outcome": "SUCCESS"},
                {"operation": "catalog.list_resource_tags.probe", "attempts": tag_attempts, "outcome": "SUCCESS"},
            ),
        )


class CatalogCandidateRecallAgent:
    """Recall deterministic candidates from the real Catalog port."""

    name = "CandidateRecallAgent"
    version = "recall-mysql-v1"

    def __init__(
        self,
        catalog: CatalogRepository,
        *,
        graph: GraphRecallPort | None = None,
        graph_version: str | None = None,
        retry_policy: RetryPolicy = RetryPolicy(),
    ) -> None:
        self._catalog = catalog
        self._graph = graph
        self._graph_version = graph_version
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
        graph_hits: dict[str, Any] = {}
        graph_attempts = 0
        graph_warning: tuple[str, ...] = ()
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
            except DependencyCallFailed:
                graph_warning = ("GRAPH_RECALL_UNAVAILABLE",)
        candidates: list[dict[str, object]] = []
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
            graph_hit = graph_hits.get(resource.external_id)
            graph_score = float(graph_hit.score) if graph_hit is not None else 0.0
            score = max(0.0, min(1.0, 0.50 * keyword_score + 0.25 * profile_score + 0.25 * graph_score))
            channels = ["MYSQL"]
            evidence_ref = f"catalog:resource:{resource.id}:metadata:{resource.metadata_version}"
            if graph_hit is not None:
                channels.append("GRAPH")
                evidence_ref += f":graph:{graph_hit.graph_version}"
            candidates.append(
                {
                    "resource_id": resource.id,
                    "channel": "+".join(channels),
                    "score": round(score, 6),
                    "evidence_ref": evidence_ref,
                }
            )
        candidates.sort(key=lambda item: (-float(item["score"]), int(item["resource_id"])))
        selected = candidates[:limit]
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "candidates": selected,
                "candidate_count": len(selected),
                "channels": ["MYSQL"] + (["GRAPH"] if graph_hits else []),
            },
            confidence=0.8 if selected else 0.3,
            status=AgentResultStatus.SUCCESS if selected else AgentResultStatus.PARTIAL,
            warnings=(("CATALOG_EMPTY",) if not selected else ()) + graph_warning,
            fallback_used=False,
            tool_calls=(
                {"operation": "catalog.list_resources.recall", "attempts": resource_attempts, "outcome": "SUCCESS"},
                {"operation": "catalog.list_resource_tags.recall", "attempts": tag_attempts, "outcome": "SUCCESS"},
            ) + (({"operation": "catalog.graph_recall", "attempts": graph_attempts, "outcome": "SUCCESS"},) if graph_hits else ()),
        )


__all__ = [
    "CatalogCandidateRecallAgent",
    "CatalogResourceSemanticAgent",
    "MySQLProfileAgent",
]
