from __future__ import annotations

import unittest

from scripts.architecture_guard import check_source


class DependencyRulesTest(unittest.TestCase):
    def test_domain_standard_library_imports_pass(self) -> None:
        source = "from dataclasses import dataclass\nfrom enum import StrEnum\n"
        self.assertEqual(
            [],
            check_source("backend/app/catalog/domain/resource.py", source),
        )

    def test_domain_framework_import_is_rejected(self) -> None:
        source = "from sqlalchemy.orm import Mapped\n"
        violations = check_source("backend/app/catalog/domain/resource.py", source)
        self.assertEqual("DOMAIN_INFRA_DEPENDENCY", violations[0].code)

    def test_agent_infrastructure_import_is_rejected(self) -> None:
        source = "from backend.app.platform.mysql import session\n"
        violations = check_source(
            "backend/app/recommendation/agents/ranking_agent.py", source
        )
        self.assertEqual("AGENT_INFRA_DEPENDENCY", violations[0].code)

    def test_api_orm_import_is_rejected(self) -> None:
        source = "from backend.app.catalog.db.models import ResourceRow\n"
        violations = check_source("backend/app/api/v1/resources.py", source)
        self.assertEqual("API_ORM_DEPENDENCY", violations[0].code)

    def test_domain_cannot_import_project_adapter(self) -> None:
        source = "from backend.app.catalog.adapters.mysql import ResourceRow\n"
        violations = check_source("backend/app/catalog/domain/resource.py", source)
        self.assertIn("DOMAIN_INFRA_DEPENDENCY", {item.code for item in violations})

    def test_domain_cannot_import_relative_adapter(self) -> None:
        source = "from ..adapters.mysql import ResourceRow\n"
        violations = check_source("backend/app/catalog/domain/resource.py", source)
        self.assertEqual("DOMAIN_INFRA_DEPENDENCY", violations[0].code)

    def test_domain_cannot_import_own_application_or_ports(self) -> None:
        sources = (
            "from backend.app.catalog.application.public import CatalogQuery\n",
            "from backend.app.catalog.ports.public import CatalogPort\n",
        )
        for source in sources:
            with self.subTest(source=source):
                violations = check_source(
                    "backend/app/catalog/domain/resource.py",
                    source,
                )
                self.assertEqual("DOMAIN_INFRA_DEPENDENCY", violations[0].code)

    def test_domain_can_import_own_domain_and_shared_contract(self) -> None:
        sources = (
            "from backend.app.catalog.domain.value import ResourceId\n",
            "from backend.app.shared_kernel.contracts.enums import ResourceType\n",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(
                    [],
                    check_source("backend/app/catalog/domain/resource.py", source),
                )

    def test_shared_kernel_cannot_import_business_domain(self) -> None:
        source = "from backend.app.profile.domain.profile import UserProfile\n"
        violations = check_source(
            "backend/app/shared_kernel/contracts/profile.py",
            source,
        )
        self.assertEqual("SHARED_KERNEL_DOMAIN_DEPENDENCY", violations[0].code)

    def test_shared_kernel_rejects_unknown_project_module(self) -> None:
        source = "from backend.app.unbounded_helpers import magic\n"
        violations = check_source(
            "backend/app/shared_kernel/contracts/helper.py",
            source,
        )
        self.assertEqual("DOMAIN_INFRA_DEPENDENCY", violations[0].code)

    def test_cross_module_internal_import_is_rejected(self) -> None:
        source = "from backend.app.profile.domain.profile import UserProfile\n"
        violations = check_source(
            "backend/app/recommendation/application/recommend.py",
            source,
        )
        self.assertEqual("CROSS_MODULE_INTERNAL_DEPENDENCY", violations[0].code)

    def test_cross_module_public_port_is_allowed(self) -> None:
        source = "from backend.app.profile.ports.public import ProfileSnapshotPort\n"
        violations = check_source(
            "backend/app/recommendation/application/recommend.py",
            source,
        )
        self.assertEqual([], violations)

    def test_api_framework_session_is_rejected(self) -> None:
        source = "from sqlalchemy.orm import Session\n"
        violations = check_source("backend/app/api/v1/tasks.py", source)
        self.assertEqual("API_ORM_DEPENDENCY", violations[0].code)

    def test_agent_sdk_import_is_rejected(self) -> None:
        source = "from chromadb import Client\n"
        violations = check_source(
            "backend/app/recommendation/agents/ranking.py",
            source,
        )
        self.assertEqual("AGENT_INFRA_DEPENDENCY", violations[0].code)

    def test_agent_to_agent_import_is_rejected(self) -> None:
        source = "from backend.app.recommendation.agents.ranking import RankingAgent\n"
        violations = check_source(
            "backend/app/recommendation/agents/policy.py",
            source,
        )
        self.assertEqual("AGENT_TO_AGENT_IMPORT", violations[0].code)

    def test_relative_cross_module_internal_import_is_rejected(self) -> None:
        source = "from ...profile.domain.profile import UserProfile\n"
        violations = check_source(
            "backend/app/recommendation/application/recommend.py",
            source,
        )
        self.assertEqual("CROSS_MODULE_INTERNAL_DEPENDENCY", violations[0].code)

    def test_domain_llm_sdk_import_is_rejected(self) -> None:
        source = "from openai import OpenAI\n"
        violations = check_source("backend/app/catalog/domain/resource.py", source)
        self.assertEqual("DOMAIN_INFRA_DEPENDENCY", violations[0].code)

    def test_ranking_cannot_import_retrieval_implementation(self) -> None:
        source = "from backend.app.recommendation.retrieval.fusion import rrf\n"
        violations = check_source(
            "backend/app/recommendation/ranking/ranker.py",
            source,
        )
        self.assertEqual("RANKING_RETRIEVAL_DEPENDENCY", violations[0].code)

    def test_explanation_cannot_import_ranking_implementation(self) -> None:
        source = "from backend.app.recommendation.ranking.ranker import rank\n"
        violations = check_source(
            "backend/app/recommendation/explanation/service.py",
            source,
        )
        self.assertEqual("EXPLANATION_RANKING_DEPENDENCY", violations[0].code)

    def test_syntax_error_fails_closed(self) -> None:
        violations = check_source(
            "backend/app/catalog/domain/resource.py",
            "def broken(:\n",
        )
        self.assertEqual("PYTHON_SYNTAX_ERROR", violations[0].code)

    def test_agent_cannot_import_filesystem_or_shell(self) -> None:
        for imported in ("os", "pathlib", "shutil", "subprocess", "sqlite3", "httpx"):
            with self.subTest(imported=imported):
                violations = check_source(
                    "backend/app/recommendation/agents/policy.py",
                    f"import {imported}\n",
                )
                self.assertEqual("AGENT_INFRA_DEPENDENCY", violations[0].code)

    def test_agent_package_reexport_cannot_bypass_boundary(self) -> None:
        source = "from backend.app.recommendation.agents import RankingAgent\n"
        violations = check_source(
            "backend/app/recommendation/agents/policy.py",
            source,
        )
        self.assertEqual("AGENT_TO_AGENT_IMPORT", violations[0].code)

    def test_api_cannot_import_platform_or_repository(self) -> None:
        sources = (
            "from backend.app.platform.mysql import session\n",
            "from backend.app.recommendation.repository import TaskRepository\n",
        )
        for source in sources:
            with self.subTest(source=source):
                violations = check_source("backend/app/api/v1/tasks.py", source)
                self.assertEqual("API_ORM_DEPENDENCY", violations[0].code)

    def test_api_cannot_import_business_domain_implementation(self) -> None:
        source = "from backend.app.recommendation.domain.task import RecommendationTask\n"
        violations = check_source("backend/app/api/v1/tasks.py", source)
        self.assertEqual("API_ORM_DEPENDENCY", violations[0].code)

    def test_api_can_import_public_application_boundary(self) -> None:
        source = (
            "from backend.app.recommendation.application.public "
            "import CreateRecommendationTask\n"
        )
        self.assertEqual([], check_source("backend/app/api/v1/tasks.py", source))

    def test_application_cannot_import_own_adapter(self) -> None:
        source = "from backend.app.catalog.adapters.mysql import ResourceRepository\n"
        violations = check_source(
            "backend/app/catalog/application/import_resources.py",
            source,
        )
        self.assertEqual("APPLICATION_INFRA_DEPENDENCY", violations[0].code)

    def test_explanation_cannot_import_repository(self) -> None:
        source = "from backend.app.recommendation.repository import ItemRepository\n"
        violations = check_source(
            "backend/app/recommendation/explanation/service.py",
            source,
        )
        self.assertEqual(
            "DETERMINISTIC_SERVICE_INFRA_DEPENDENCY",
            violations[0].code,
        )


if __name__ == "__main__":
    unittest.main()
