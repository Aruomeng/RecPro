from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.g4_operator_runtime import load_existing_chroma_collection


class _Collection:
    name = "library_resources__hash_char_ngram_v1"
    metadata = {
        "recpro_namespace_name": "library_resources__hash_char_ngram_v1",
        "recpro_graph_version": "lib-books-v1-20260810",
        "recpro_embedding_version": "hash-char-ngram-v1",
        "recpro_index_version": "lib-books-vector-v1-20260811",
        "hnsw:space": "cosine",
    }

    def count(self) -> int:
        return 14983


class _Client:
    def __init__(self, raw_path: str) -> None:
        self.raw_path = raw_path
        self.get_collection_calls: list[tuple[str, object]] = []

    def get_collection(self, name: str, *, embedding_function: object) -> _Collection:
        self.get_collection_calls.append((name, embedding_function))
        return _Collection()


class OperatorChromaRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.expected = dict(_Collection.metadata)

    def test_loader_requires_existing_path_and_existing_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            clients: list[_Client] = []

            def factory(raw_path: str) -> _Client:
                client = _Client(raw_path)
                clients.append(client)
                return client

            loaded = load_existing_chroma_collection(
                chroma_path=path,
                collection_name=_Collection.name,
                expected_metadata=self.expected,
                expected_count=14983,
                client_factory=factory,
            )

            self.assertEqual(14983, loaded.count)
            self.assertEqual(_Collection.name, loaded.name)
            self.assertEqual(1, len(clients))
            self.assertEqual(
                [(_Collection.name, None)], clients[0].get_collection_calls
            )

    def test_loader_rejects_count_drift_before_runtime_use(self) -> None:
        class DriftCollection(_Collection):
            def count(self) -> int:
                return 14982

        class DriftClient(_Client):
            def get_collection(self, name: str, *, embedding_function: object) -> DriftCollection:
                return DriftCollection()

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "count mismatch"):
                load_existing_chroma_collection(
                    chroma_path=Path(directory),
                    collection_name=_Collection.name,
                    expected_metadata=self.expected,
                    expected_count=14983,
                    client_factory=DriftClient,
                )

    def test_loader_rejects_metadata_drift(self) -> None:
        class DriftCollection(_Collection):
            metadata = {**_Collection.metadata, "hnsw:space": "l2"}

        class DriftClient(_Client):
            def get_collection(self, name: str, *, embedding_function: object) -> DriftCollection:
                return DriftCollection()

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "metadata mismatch"):
                load_existing_chroma_collection(
                    chroma_path=Path(directory),
                    collection_name=_Collection.name,
                    expected_metadata=self.expected,
                    client_factory=DriftClient,
                )

    def test_loader_rejects_unsafe_collection_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unsafe format"):
                load_existing_chroma_collection(
                    chroma_path=Path(directory),
                    collection_name="../not-a-collection",
                    expected_metadata=self.expected,
                    client_factory=_Client,
                )


if __name__ == "__main__":
    unittest.main()
