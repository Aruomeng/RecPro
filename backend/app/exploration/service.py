"""Application service for bounded, read-only library exploration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import time
from backend.app.exploration.ports import LibraryCatalogReadPort, PublicGraphReadPort


class ExplorationService:
    def __init__(self, *, catalog_reader: LibraryCatalogReadPort, graph_reader: PublicGraphReadPort, cache_seconds: float = 300.0) -> None:
        if cache_seconds <= 0:
            raise ValueError("cache_seconds must be positive")
        self._catalog = catalog_reader
        self._graph = graph_reader
        self._cache_seconds = cache_seconds
        self._overview_cache: tuple[float, dict[str, object]] | None = None
        self._cache_lock = asyncio.Lock()

    async def overview(self) -> dict[str, object]:
        now = time.monotonic()
        if self._overview_cache and now - self._overview_cache[0] < self._cache_seconds:
            return dict(self._overview_cache[1])
        async with self._cache_lock:
            now = time.monotonic()
            if self._overview_cache and now - self._overview_cache[0] < self._cache_seconds:
                return dict(self._overview_cache[1])
            mysql, graph = await asyncio.gather(self._catalog.overview(), self._graph.stats())
            payload = {
                "schema_version": "library-overview-v1",
                "dataset_version": "lib-books-v1-20260810",
                "graph_version": "lib-books-v1-20260810",
                "generated_at": datetime.now(UTC),
                **mysql,
                "graph": graph,
            }
            self._overview_cache = (now, payload)
            return dict(payload)

    async def resource(self, resource_id: int) -> dict[str, object]:
        return await self._catalog.resource(resource_id)

    async def search_graph(self, query: str, *, limit: int) -> dict[str, object]:
        return await self._catalog.map_resource_ids(await self._graph.search(query, limit=limit))

    async def graph_neighbors(self, entity_id: str, *, limit: int) -> dict[str, object]:
        return await self._catalog.map_resource_ids(await self._graph.neighbors(entity_id, limit=limit))

    async def graph_paths(
        self, source_id: str, target_id: str, *, max_hops: int, limit: int,
    ) -> dict[str, object]:
        view = await self._graph.paths(
            source_id, target_id, max_hops=max_hops, limit=limit,
        )
        view["graph"] = await self._catalog.map_resource_ids(dict(view["graph"]))
        return view


__all__ = ["ExplorationService"]
