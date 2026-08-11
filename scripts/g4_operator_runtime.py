"""Operator-only loading of an existing, versioned Chroma collection.

The base backend deliberately does not import ``chromadb``.  This module is
kept under ``scripts`` and is only used by explicit operator verification
commands.  It can open an existing collection and inspect its metadata/count;
it never calls ``get_or_create_collection`` or any collection mutation API.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib
from pathlib import Path
import re
import sys
from typing import Any


COLLECTION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,254}$")


@dataclass(frozen=True, slots=True)
class LoadedChromaCollection:
    """A handle to one already-existing collection and its read-only facts."""

    client: object
    collection: object
    path: Path
    name: str
    count: int
    metadata: Mapping[str, object]


def _load_chromadb(site_packages: Path | None) -> Any:
    """Load Chroma only from the explicitly selected operator environment."""

    resolved_site_packages: Path | None = None
    if site_packages is not None:
        resolved_site_packages = site_packages.resolve(strict=True)
        if not resolved_site_packages.is_dir():
            raise ValueError("Chroma site-packages must be an existing directory")
        if str(resolved_site_packages) not in sys.path:
            sys.path.insert(0, str(resolved_site_packages))
    try:
        chromadb = importlib.import_module("chromadb")
    except ModuleNotFoundError as exc:  # pragma: no cover - operator environment
        raise RuntimeError(
            "chromadb is unavailable; pass the locked operator site-packages path"
        ) from exc
    if resolved_site_packages is not None:
        module_path = Path(str(getattr(chromadb, "__file__", ""))).resolve()
        if resolved_site_packages not in module_path.parents:
            raise RuntimeError("loaded chromadb is outside the selected operator environment")
    if not callable(getattr(chromadb, "PersistentClient", None)):
        raise RuntimeError("selected chromadb package has no PersistentClient")
    return chromadb


def load_existing_chroma_collection(
    *,
    chroma_path: Path,
    collection_name: str,
    expected_metadata: Mapping[str, object],
    expected_count: int | None = None,
    site_packages: Path | None = None,
    client_factory: Callable[[str], object] | None = None,
) -> LoadedChromaCollection:
    """Open one existing collection and validate its immutable read facts.

    ``client_factory`` is a test seam only.  In the operator path the factory
    is ``chromadb.PersistentClient`` and the collection is obtained with
    ``get_collection`` (never ``get_or_create_collection``).  The path must
    already exist, so a typo cannot silently create a new Chroma database.
    """

    if COLLECTION_NAME_PATTERN.fullmatch(collection_name) is None:
        raise ValueError("Chroma collection name has an unsafe format")
    path = chroma_path.expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Chroma path must be an existing directory")
    if expected_count is not None and expected_count < 1:
        raise ValueError("expected Chroma count must be positive")
    for key in expected_metadata:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("expected Chroma metadata keys must be non-blank strings")

    if client_factory is None:
        chromadb = _load_chromadb(site_packages)
        client_factory = lambda raw_path: chromadb.PersistentClient(path=raw_path)
    client = client_factory(str(path))
    getter = getattr(client, "get_collection", None)
    if not callable(getter):
        raise RuntimeError("Chroma client must expose get_collection")
    collection = getter(collection_name, embedding_function=None)
    actual_name = getattr(collection, "name", collection_name)
    if actual_name != collection_name:
        raise RuntimeError("Chroma collection name does not match the requested version")
    metadata = getattr(collection, "metadata", None)
    if not isinstance(metadata, Mapping):
        raise RuntimeError("Chroma collection metadata is unavailable")
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise RuntimeError(
                f"Chroma metadata mismatch for {key}: expected {expected!r}"
            )
    count_reader = getattr(collection, "count", None)
    if not callable(count_reader):
        raise RuntimeError("Chroma collection must expose count")
    count = count_reader()
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise RuntimeError("Chroma collection count is invalid or empty")
    if expected_count is not None and count != expected_count:
        raise RuntimeError(
            f"Chroma collection count mismatch: expected {expected_count}, got {count}"
        )
    return LoadedChromaCollection(
        client=client,
        collection=collection,
        path=path,
        name=collection_name,
        count=count,
        metadata=dict(metadata),
    )


__all__ = ["LoadedChromaCollection", "load_existing_chroma_collection"]
