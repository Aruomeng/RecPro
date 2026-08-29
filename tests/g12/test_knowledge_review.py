from __future__ import annotations

from datetime import UTC, datetime
import unittest
from uuid import NAMESPACE_URL, uuid5

from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.composition import build_mysql_knowledge_review_service
from backend.app.knowledge_review import (
    InMemoryKnowledgeReviewRepository,
    KnowledgeReviewAction,
    KnowledgeReviewProposal,
    KnowledgeReviewService,
    MySQLKnowledgeReviewRepository,
)
from backend.app.main import create_app
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal
from scripts.execute_g12_knowledge_review_plan import dry_run_report, statements
from scripts.execute_g12_knowledge_review_successor import dry_run_report as successor_dry_run_report
from scripts.execute_g12_knowledge_review_finalizer import dry_run_report as finalizer_dry_run_report


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
PROPOSAL_ID = uuid5(NAMESPACE_URL, "recpro:test:knowledge-review")


def proposal() -> KnowledgeReviewProposal:
    return KnowledgeReviewProposal(
        proposal_uuid=PROPOSAL_ID,
        proposal_type="WORK_IDENTITY_REVIEW",
        graph_version="lib-books-v2-20260828",
        subject_id="book:one", relation_type="INSTANCE_OF",
        object_id="UNRESOLVED_WORK",
        source_refs=("graph:lib-books-v2-20260828:book:one",),
        reason_codes=("WORK_ISBN_CONFLICT",), confidence=0.6,
        agent_name="ResourceSemanticAgent", task_id=None, workspace_id=None,
        idempotency_sha256="a" * 64, occurred_at=NOW,
    )


def actor(*, allowed: bool) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=9001,
        roles=frozenset({"librarian"} if allowed else {"user"}),
        permissions=frozenset({"catalog.knowledge.review"} if allowed else set()),
    )


class KnowledgeReviewServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repo = InMemoryKnowledgeReviewRepository((proposal(),))
        self.service = KnowledgeReviewService(self.repo, clock=lambda: NOW)

    async def test_reader_cannot_list_or_act(self) -> None:
        with self.assertRaises(PermissionError):
            await self.service.list_reviews(actor=actor(allowed=False))
        with self.assertRaises(PermissionError):
            await self.service.act(
                PROPOSAL_ID, action=KnowledgeReviewAction.APPROVE,
                reason_code="READER_FORBIDDEN", idempotency_key="reader-denied-1",
                actor=actor(allowed=False),
            )

    async def test_action_is_append_only_idempotent_and_never_writes_neo4j(self) -> None:
        view, replayed = await self.service.act(
            PROPOSAL_ID, action=KnowledgeReviewAction.REQUEST_EVIDENCE,
            reason_code="MORE_EVIDENCE_REQUIRED", idempotency_key="review-action-0001",
            actor=actor(allowed=True),
        )
        self.assertFalse(replayed)
        self.assertEqual("EVIDENCE_REQUESTED", view["status"])
        replay, replayed = await self.service.act(
            PROPOSAL_ID, action=KnowledgeReviewAction.REQUEST_EVIDENCE,
            reason_code="MORE_EVIDENCE_REQUIRED", idempotency_key="review-action-0001",
            actor=actor(allowed=True),
        )
        self.assertTrue(replayed)
        self.assertEqual(1, len(replay["actions"]))
        self.assertFalse(hasattr(self.service, "neo4j"))

    async def test_mysql_builder_is_connection_free_and_uses_real_repository(self) -> None:
        opened = False

        async def connection_factory():
            nonlocal opened
            opened = True
            raise AssertionError("builder must not open MySQL")

        service = build_mysql_knowledge_review_service(
            AppSettings(app_env="demo", mysql_password="isolated-test-password"),
            connection_factory=connection_factory,
        )
        self.assertFalse(opened)
        self.assertIsInstance(service._repository, MySQLKnowledgeReviewRepository)


class KnowledgeReviewAPITests(unittest.TestCase):
    def app(self, principal: AuthenticatedPrincipal):
        service = KnowledgeReviewService(InMemoryKnowledgeReviewRepository((proposal(),)), clock=lambda: NOW)
        return create_app(
            settings=AppSettings(app_env="test", mysql_password="isolated-test-password"),
            principal_resolver=lambda _token: principal,
            knowledge_review_service=service,
            knowledge_review_api_enabled=True,
        )

    def test_reader_is_forbidden_and_librarian_action_reports_zero_graph_writes(self) -> None:
        with TestClient(self.app(actor(allowed=False))) as client:
            denied = client.get(
                "/api/v1/librarian/knowledge-reviews",
                headers={"Authorization": "Bearer reader-token"},
            )
            self.assertEqual(403, denied.status_code)
        with TestClient(self.app(actor(allowed=True))) as client:
            listed = client.get(
                "/api/v1/librarian/knowledge-reviews",
                headers={"Authorization": "Bearer librarian-token"},
            )
            self.assertEqual(200, listed.status_code, listed.text)
            action = client.post(
                f"/api/v1/librarian/knowledge-reviews/{PROPOSAL_ID}/actions",
                headers={
                    "Authorization": "Bearer librarian-token",
                    "Idempotency-Key": "knowledge-review-action-1",
                },
                json={"action": "APPROVE", "reason_code": "EVIDENCE_ACCEPTED"},
            )
            self.assertEqual(200, action.status_code, action.text)
            self.assertEqual(0, action.json()["neo4j_write_count"])
            self.assertEqual("APPROVED", action.json()["review"]["status"])

    def test_default_app_does_not_mount_review_api(self) -> None:
        default = create_app(settings=AppSettings(mysql_password="isolated-test-password"))
        self.assertNotIn("/api/v1/librarian/knowledge-reviews", default.openapi()["paths"])


class KnowledgeReviewMigrationTests(unittest.TestCase):
    def test_migration_is_append_only_and_dry_run_has_exact_budget(self) -> None:
        source = "\n".join(statements()).upper()
        for forbidden in ("DROP ", "TRUNCATE ", "DELETE FROM", "\nUPDATE ", "REPLACE INTO", "ON DELETE CASCADE", "ON UPDATE CASCADE"):
            self.assertNotIn(forbidden, source)
        report = dry_run_report()
        self.assertEqual(262, report["proposal_rows"])
        self.assertEqual(0, report["action_fact_rows"])
        self.assertEqual(266, report["maximum_rows"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["neo4j_writes"])

    def test_successor_requires_exact_partial_state_and_adds_no_privilege_grant(self) -> None:
        report = successor_dry_run_report()
        self.assertEqual(2, report["expected_existing_empty_tables"])
        self.assertEqual(1, report["view_statements"])
        self.assertEqual(262, report["proposal_rows"])
        self.assertEqual(266, report["maximum_rows"])
        self.assertEqual(0, report["privilege_grants"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_physical_deletions"])

    def test_finalizer_is_pure_append_without_schema_or_admin_operations(self) -> None:
        report = finalizer_dry_run_report()
        self.assertEqual(2, report["expected_existing_tables"])
        self.assertEqual(1, report["expected_existing_views"])
        self.assertEqual(266, report["maximum_rows"])
        self.assertEqual(0, report["admin_operations"])
        self.assertEqual(0, report["database_connections"])


if __name__ == "__main__":
    unittest.main()
