from __future__ import annotations

import unittest

from pydantic import SecretStr
from fastapi.testclient import TestClient

from backend.app.composition import build_research_g4_http_app_from_runtime
from backend.app.config import AppSettings
from backend.app.catalog.runtime.g4_ports import build_g4_readonly_runtime
from backend.app.catalog.runtime.g4_ports import G4ReadOnlyRuntime


class _Collection:
    def query(self, **_: object) -> dict[str, list[list[object]]]:
        return {"ids": [[]], "distances": [[]], "metadatas": [[]]}


class _Graph:
    async def recall(self, **_: object) -> tuple[object, ...]:
        return ()


class _Vector:
    async def recall(self, **_: object) -> tuple[object, ...]:
        return ()


class _Embedder:
    embedding_version = "hash-char-ngram-v1"
    dimension = 384

    def embed(self, _: str) -> tuple[float, ...]:
        return (1.0,) + (0.0,) * 383


def runtime():
    return build_g4_readonly_runtime(
        graph_endpoint="http://127.0.0.1:62475/db/neo4j/tx/commit",
        graph_username="neo4j",
        graph_password="local-graph-password",
        chroma_collection=_Collection(),
        graph_version="lib-books-v1-20260810",
        embedding_version="hash-char-ngram-v1",
        index_version="lib-books-vector-v1-20260811",
        namespace_name="library_resources__hash_char_ngram_v1",
    )


def ready_runtime() -> G4ReadOnlyRuntime:
    return G4ReadOnlyRuntime(
        graph=_Graph(),
        vector=_Vector(),
        query_embedder=_Embedder(),
        graph_version="lib-books-v1-20260810",
        embedding_version="hash-char-ngram-v1",
        index_version="lib-books-vector-v1-20260811",
        namespace_name="library_resources__hash_char_ngram_v1",
        dimension=384,
    )


class G4RuntimePortTests(unittest.TestCase):
    def test_runtime_factory_is_version_pinned_without_store_access(self) -> None:
        value = runtime()
        self.assertEqual("lib-books-v1-20260810", value.graph_version)
        self.assertEqual("hash-char-ngram-v1", value.embedding_version)
        self.assertEqual("lib-books-vector-v1-20260811", value.index_version)
        self.assertEqual(384, value.dimension)

    def test_runtime_rejects_embedder_version_drift(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedder version"):
            build_g4_readonly_runtime(
                graph_endpoint="http://127.0.0.1:62475/db/neo4j/tx/commit",
                graph_username="neo4j",
                graph_password="local-graph-password",
                chroma_collection=_Collection(),
                graph_version="lib-books-v1-20260810",
                embedding_version="other-embedding-v1",
                index_version="lib-books-vector-v1-20260811",
                namespace_name="library_resources__hash_char_ngram_v1",
            )

    def test_http_from_runtime_is_explicit_and_does_not_connect_on_build(self) -> None:
        opened = False

        async def connection_factory():
            nonlocal opened
            opened = True
            raise AssertionError("G4 runtime composition must not connect during build")

        application = build_research_g4_http_app_from_runtime(
            AppSettings(
                app_env="demo",
                mysql_password=SecretStr("RecProMysqlRuntime.20260802"),
                g4_http_enabled=True,
            ),
            runtime=ready_runtime(),
            connection_factory=connection_factory,
        )
        self.assertFalse(opened)
        self.assertIn("/api/v1/recommendation-tasks", application.openapi()["paths"])

    def test_g4_http_readiness_identifies_the_g4_pipeline_version(self) -> None:
        class Probe:
            async def check(self):
                from backend.app.observability.domain import ComponentReadiness, ComponentStatus

                return ComponentReadiness(ComponentStatus.UP, required=True)

        application = build_research_g4_http_app_from_runtime(
            AppSettings(
                app_env="demo",
                mysql_password=SecretStr("RecProMysqlRuntime.20260802"),
                g4_http_enabled=True,
                g4_llm_intent_enabled=True,
                llm_provider="deepseek",
                llm_api_key=SecretStr("local-test-deepseek-key-001"),
            ),
            runtime=ready_runtime(),
            connection_factory=lambda: None,
            enable_llm_intent_provider=True,
            readiness_probe=Probe(),
            config_bundle_probe=Probe(),
        )
        with TestClient(application) as client:
            body = client.get("/api/v1/health/ready").json()
        self.assertTrue(body["can_recommend"])
        self.assertEqual("READY", body["status"])
        self.assertEqual("UP", body["components"]["neo4j"]["status"])
        self.assertEqual("UP", body["components"]["chroma"]["status"])
        self.assertEqual("UP", body["components"]["llm"]["status"])
        self.assertEqual("deepseek", body["components"]["llm"]["provider"])
        self.assertEqual(
            "recommendation-g4-graph-vector-v1",
            body["components"]["recommendation_pipeline"]["active_version"],
        )


if __name__ == "__main__":
    unittest.main()
