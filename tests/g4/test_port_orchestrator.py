from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.app.catalog.domain.models import ResourceSummary, ResourceTagEvidence
from backend.app.profile.replay import InterestSignal, ProfileSnapshot
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.orchestrator import (
    OrchestrationDeadlineExceeded,
    OrchestrationRequest,
)
from backend.app.recommendation.application.orchestration import build_port_orchestrator
from backend.app.shared_kernel.contracts.enums import TaskStatus


EVALUATION_AT = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)


def resource(resource_id: int, title: str) -> ResourceSummary:
    return ResourceSummary(
        id=resource_id,
        resource_type="BOOK" if resource_id % 2 else "PAPER",
        external_id=f"port-resource-{resource_id}",
        title=title,
        authors=("Author",),
        abstract_text=f"{title} abstract",
        keywords=("multi-agent",),
        category_code="G25",
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
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.resource_calls = 0
        self.tag_calls = 0
        self.resources = (resource(1, "多智能体推荐"), resource(2, "智慧图书馆"))

    async def list_resources(self, *, available_at=None, resource_type=None):
        self.resource_calls += 1
        if self.failures:
            self.failures -= 1
            raise ConnectionError("catalog fixture unavailable")
        return tuple(
            item for item in self.resources
            if resource_type is None or item.resource_type == resource_type
        )

    async def list_resource_tags(self, *, resource_ids):
        self.tag_calls += 1
        return tuple(
            ResourceTagEvidence(resource_id=item_id, tag_id=1, normalized_name="multi-agent", weight=0.9, confidence=0.9, source="RULE")
            for item_id in resource_ids
        )


class AlwaysFailCatalog(FakeCatalog):
    def __init__(self) -> None:
        super().__init__(failures=100)


class FakeProfile:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures

    async def get_snapshot(self, *, user_id: int, as_of: datetime):
        if self.failures:
            self.failures -= 1
            raise TimeoutError("profile fixture timed out")
        return ProfileSnapshot(
            user_id=user_id,
            as_of=as_of,
            formula_version="profile-port-test-v1",
            event_count=4,
            profile_confidence=0.8,
            recent_focus_tag_id=1,
            topic_focus_strength=0.7,
            interests=(InterestSignal(1, 2.0, 0.7, 2, as_of),),
            negatives=(),
            input_hash="a" * 64,
        )


def request(*, deadline_at: datetime | None = None) -> OrchestrationRequest:
    return OrchestrationRequest(
        task_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        trace_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        session_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        user_id=1001,
        input_text="多智能体推荐",
        resource_types=("BOOK", "PAPER"),
        limit=2,
        evaluation_at=EVALUATION_AT,
        deadline_at=deadline_at or datetime.now(UTC) + timedelta(seconds=5),
    )


class G4PortOrchestratorTests(unittest.TestCase):
    def test_port_composition_reads_catalog_and_profile(self) -> None:
        catalog = FakeCatalog()
        result = asyncio.run(
            build_port_orchestrator(catalog, FakeProfile()).run(request())
        )
        self.assertEqual(TaskStatus.COMPLETED, result.status)
        self.assertGreaterEqual(catalog.resource_calls, 2)
        profile = next(item for item in result.dispatches if item.message.receiver == "UserProfileAgent")
        self.assertEqual("profile-port-test-v1:4", profile.result.payload["profile_version"])
        recall = next(item for item in result.dispatches if item.message.receiver == "CandidateRecallAgent")
        self.assertEqual(2, recall.result.payload["candidate_count"])
        self.assertIn("semantic-mysql-v1", {item.result.agent_version for item in result.dispatches})

    def test_transient_catalog_failure_retries_once_then_succeeds(self) -> None:
        catalog = FakeCatalog(failures=1)
        result = asyncio.run(
            build_port_orchestrator(
                catalog,
                FakeProfile(),
                retry_policy=RetryPolicy(max_attempts=2),
            ).run(request())
        )
        self.assertEqual(TaskStatus.COMPLETED, result.status)
        semantic = next(item for item in result.dispatches if item.message.receiver == "ResourceSemanticAgent")
        attempts = [call["attempts"] for call in semantic.result.tool_calls]
        self.assertIn(2, attempts)

    def test_exhausted_catalog_retry_falls_back_to_degraded_result(self) -> None:
        result = asyncio.run(
            build_port_orchestrator(
                AlwaysFailCatalog(),
                FakeProfile(),
                retry_policy=RetryPolicy(max_attempts=2),
            ).run(request())
        )
        self.assertEqual(TaskStatus.DEGRADED_COMPLETED, result.status)
        self.assertIn("CATALOG_READ_UNAVAILABLE", result.payload["warnings"])
        semantic = next(item for item in result.dispatches if item.message.receiver == "ResourceSemanticAgent")
        self.assertEqual(2, semantic.result.tool_calls[0]["attempts"])

    def test_profile_timeout_is_bounded_and_warns(self) -> None:
        result = asyncio.run(
            build_port_orchestrator(
                FakeCatalog(),
                FakeProfile(failures=10),
                retry_policy=RetryPolicy(max_attempts=2),
            ).run(request())
        )
        self.assertEqual(TaskStatus.DEGRADED_COMPLETED, result.status)
        self.assertIn("PROFILE_READ_UNAVAILABLE", result.payload["warnings"])

    def test_expired_deadline_fails_before_dispatch(self) -> None:
        with self.assertRaises(OrchestrationDeadlineExceeded):
            asyncio.run(
                build_port_orchestrator(FakeCatalog(), FakeProfile()).run(
                    request(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            )


if __name__ == "__main__":
    unittest.main()
