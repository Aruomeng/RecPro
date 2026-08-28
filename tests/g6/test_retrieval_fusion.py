from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest
from uuid import uuid4

from backend.app.catalog.adapters.embedding import HashCharNgramQueryEmbedder
from backend.app.catalog.domain.models import (
    GraphRecallEvidence,
    ResourceSummary,
    ResourceTagEvidence,
    VectorRecallEvidence,
)
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.real_agents import CatalogCandidateRecallAgent
from backend.app.recommendation.agents.rule_agents import RuleExplanationAgent
from backend.app.shared_kernel.contracts.agent import AgentMessage
from backend.app.shared_kernel.contracts.enums import AgentResultStatus, MessageType
from scripts.build_vector_index_plan import embedding_vector


EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"


def resource(resource_id: int, external_id: str, title: str) -> ResourceSummary:
    return ResourceSummary(
        id=resource_id,
        resource_type="BOOK",
        external_id=external_id,
        title=title,
        authors=("Author",),
        abstract_text=f"{title} abstract",
        keywords=("多智能体",),
        category_code="TP",
        publication_year=2025,
        availability_status="AVAILABLE_BORROW",
        available_from=datetime(2024, 1, 1),
        access_url=None,
        metadata_quality=0.9,
        is_classic=False,
        metadata_version=1,
        language="zh-CN",
        difficulty_level=2,
    )


class FakeCatalog:
    async def list_resources(self, *, available_at=None, resource_type=None):
        return (resource(1, "book:one", "多智能体基础"), resource(2, "book:two", "智慧图书馆"))

    async def list_resource_tags(self, *, resource_ids):
        return tuple(
            ResourceTagEvidence(
                resource_id=resource_id,
                tag_id=1,
                normalized_name="多智能体",
                weight=0.9,
                confidence=0.9,
                source="RULE",
            )
            for resource_id in resource_ids
        )


class FakeGraph:
    async def recall(self, *, terms, graph_version, limit):
        return (
            GraphRecallEvidence(
                external_id="book:one",
                score=0.8,
                matched_terms=("多智能体",),
                graph_version=graph_version,
            ),
        )


class FakeV2GraphWithoutPath:
    async def recall(self, *, terms, graph_version, limit):
        return (
            GraphRecallEvidence(
                external_id="book:one",
                score=0.95,
                matched_terms=("多智能体",),
                graph_version=graph_version,
                graph_path_refs=(),
            ),
        )


class FakeGraphTimeout:
    def __init__(self) -> None:
        self.calls = 0

    async def recall(self, *, terms, graph_version, limit):
        self.calls += 1
        raise TimeoutError("graph fixture timed out")


class FakeVector:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def recall(self, *, query_vector, embedding_version, index_version, limit):
        self.calls.append(
            {
                "dimension": len(query_vector),
                "embedding_version": embedding_version,
                "index_version": index_version,
                "limit": limit,
            }
        )
        if self.fail:
            raise TimeoutError("vector fixture timed out")
        return (
            VectorRecallEvidence(
                external_id="book:two",
                vector_id="vec-two",
                score=0.9,
                embedding_version=embedding_version,
                index_version=index_version,
                namespace_name="library_resources__hash_char_ngram_v1",
            ),
        )


def recall_message(*, query_text: str = "多智能体") -> AgentMessage:
    now = datetime.now(UTC)
    return AgentMessage(
        schema_version="g4-orchestrator-v1",
        message_id=uuid4(),
        trace_id=uuid4(),
        task_id=uuid4(),
        sender="RecommendationOrchestrator",
        receiver="CandidateRecallAgent",
        message_type=MessageType.RECALL_EXECUTE,
        payload={
            "intent": {"topic_terms": ["多智能体"], "resource_types": ["BOOK"]},
            "profile": {"signals": []},
            "limit": 2,
            "query_text": query_text,
        },
        deadline_at=now + timedelta(seconds=3),
        idempotency_key=str(uuid4()),
        context_version=1,
        created_at=now,
    )


class RetrievalFusionTests(unittest.TestCase):
    def test_query_embedder_matches_versioned_offline_vector_contract(self) -> None:
        text = "多智能体系统与智慧图书馆"
        self.assertEqual(embedding_vector(text), HashCharNgramQueryEmbedder().embed(text))

    def test_graph_and_vector_are_optional_fusion_channels(self) -> None:
        vector = FakeVector()
        agent = CatalogCandidateRecallAgent(
            FakeCatalog(),
            graph=FakeGraph(),
            graph_version="lib-books-v1-20260810",
            vector=vector,
            query_embedder=HashCharNgramQueryEmbedder(),
            embedding_version=EMBEDDING_VERSION,
            index_version=INDEX_VERSION,
        )
        result = asyncio.run(agent.handle(recall_message()))
        self.assertEqual(AgentResultStatus.SUCCESS, result.status)
        self.assertEqual(("MYSQL", "GRAPH", "VECTOR"), tuple(result.payload["channels"]))
        self.assertEqual("READY", result.payload["dependency_status"]["VECTOR"])
        self.assertTrue(
            any(
                "vector:" + INDEX_VERSION in candidate["evidence_ref"]
                for candidate in result.payload["candidates"]
            )
        )
        self.assertTrue(
            any(candidate["kg_score"] is not None for candidate in result.payload["candidates"])
        )
        self.assertTrue(
            any(candidate["semantic_score"] is not None for candidate in result.payload["candidates"])
        )
        self.assertEqual(
            {"dimension": 384, "embedding_version": EMBEDDING_VERSION, "index_version": INDEX_VERSION, "limit": 2},
            vector.calls[0],
        )

    def test_vector_failure_is_bounded_and_falls_back_to_mysql(self) -> None:
        vector = FakeVector(fail=True)
        agent = CatalogCandidateRecallAgent(
            FakeCatalog(),
            vector=vector,
            query_embedder=HashCharNgramQueryEmbedder(),
            embedding_version=EMBEDDING_VERSION,
            index_version=INDEX_VERSION,
            retry_policy=RetryPolicy(max_attempts=2),
        )
        result = asyncio.run(agent.handle(recall_message()))
        self.assertEqual(AgentResultStatus.PARTIAL, result.status)
        self.assertTrue(result.fallback_used)
        self.assertIn("VECTOR_RECALL_UNAVAILABLE", result.warnings)
        self.assertEqual("UNAVAILABLE", result.payload["dependency_status"]["VECTOR"])
        self.assertEqual(2, len(vector.calls))
        self.assertTrue(all("VECTOR" not in item["channel"] for item in result.payload["candidates"]))
        self.assertTrue(all(item["semantic_score"] is None for item in result.payload["candidates"]))

    def test_v2_graph_without_path_evidence_cannot_contribute(self) -> None:
        agent = CatalogCandidateRecallAgent(
            FakeCatalog(),
            graph=FakeV2GraphWithoutPath(),
            graph_version="lib-books-v2-20260828",
        )
        result = asyncio.run(agent.handle(recall_message()))
        candidates = list(result.payload["candidates"])
        self.assertTrue(candidates)
        self.assertTrue(all("GRAPH" not in item["channel"] for item in candidates))
        self.assertTrue(all(item["graph_path_refs"] == [] for item in candidates))
        self.assertTrue(all(":graph:" not in item["evidence_ref"] for item in candidates))

    def test_graph_and_vector_outage_keeps_sufficient_mysql_candidates(self) -> None:
        graph = FakeGraphTimeout()
        vector = FakeVector(fail=True)
        agent = CatalogCandidateRecallAgent(
            FakeCatalog(),
            graph=graph,
            graph_version="lib-books-v1-20260810",
            vector=vector,
            query_embedder=HashCharNgramQueryEmbedder(),
            embedding_version=EMBEDDING_VERSION,
            index_version=INDEX_VERSION,
            retry_policy=RetryPolicy(max_attempts=2),
        )
        result = asyncio.run(agent.handle(recall_message()))
        self.assertEqual(AgentResultStatus.PARTIAL, result.status)
        self.assertTrue(result.fallback_used)
        self.assertIn("GRAPH_RECALL_UNAVAILABLE", result.warnings)
        self.assertIn("VECTOR_RECALL_UNAVAILABLE", result.warnings)
        self.assertEqual("UNAVAILABLE", result.payload["dependency_status"]["GRAPH"])
        self.assertEqual("UNAVAILABLE", result.payload["dependency_status"]["VECTOR"])
        candidates = list(result.payload["candidates"])
        self.assertEqual(2, len(candidates))
        self.assertTrue(all(item["channel"] == "MYSQL" for item in candidates))
        self.assertTrue(all(item["kg_score"] is None for item in candidates))
        self.assertTrue(all(item["semantic_score"] is None for item in candidates))
        self.assertTrue(all(":graph:" not in item["evidence_ref"] for item in candidates))
        self.assertTrue(all(":vector:" not in item["evidence_ref"] for item in candidates))
        self.assertEqual((2, 2), (graph.calls, len(vector.calls)))
        self.assertEqual(
            {"operation": "catalog.graph_recall", "attempts": 2, "outcome": "TIMEOUT"},
            result.tool_calls[-2],
        )
        self.assertEqual(
            {"operation": "catalog.vector_recall", "attempts": 2, "outcome": "TIMEOUT"},
            result.tool_calls[-1],
        )

    def test_graph_timeout_is_null_and_explanation_cannot_invent_graph_path(self) -> None:
        graph = FakeGraphTimeout()
        agent = CatalogCandidateRecallAgent(
            FakeCatalog(),
            graph=graph,
            graph_version="lib-books-v1-20260810",
            retry_policy=RetryPolicy(max_attempts=2),
        )
        result = asyncio.run(agent.handle(recall_message()))
        self.assertEqual(AgentResultStatus.PARTIAL, result.status)
        self.assertIn("GRAPH_RECALL_UNAVAILABLE", result.warnings)
        self.assertEqual("UNAVAILABLE", result.payload["dependency_status"]["GRAPH"])
        self.assertEqual(2, graph.calls)
        self.assertEqual(
            {
                "operation": "catalog.graph_recall",
                "attempts": 2,
                "outcome": "TIMEOUT",
            },
            result.tool_calls[-1],
        )
        candidates = list(result.payload["candidates"])
        self.assertTrue(candidates)
        self.assertTrue(all(candidate["kg_score"] is None for candidate in candidates))
        self.assertTrue(all(":graph:" not in candidate["evidence_ref"] for candidate in candidates))

        ranked_items = [
            {**candidate, "rank_no": rank}
            for rank, candidate in enumerate(candidates, start=1)
        ]
        explanation_message = replace(
            recall_message(),
            receiver="ExplanationAgent",
            message_type=MessageType.EXPLAIN_EXECUTE,
            payload={"ranked_items": ranked_items},
        )
        explanation = asyncio.run(RuleExplanationAgent().handle(explanation_message))
        for item in explanation.payload["explanations"]:
            self.assertTrue(all(":graph:" not in ref for ref in item["evidence_refs"]))
            self.assertNotIn("graph:", item["summary"].lower())


if __name__ == "__main__":
    unittest.main()
