"""Bounded, read-only Neo4j queries for public graph exploration."""

from __future__ import annotations

import asyncio
import base64
import json
from hashlib import sha256
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


PUBLIC_LABELS = frozenset(
    {"Book", "Topic", "Author", "Publisher", "Category", "Keyword", "SubjectCode"}
)
PUBLIC_RELATIONSHIPS = frozenset(
    {
        "AUTHORED_BY",
        "PUBLISHED_BY",
        "CLASSIFIED_AS",
        "IN_TOPIC",
        "HAS_TOPIC",
        "HAS_SUBJECT_CODE",
        "HAS_KEYWORD",
    }
)
PUBLIC_PROPERTIES = frozenset(
    {"title", "name", "code", "isbn", "publication_year", "publisher", "pages", "physical_format"}
)

_GRAPH_STATS = (
    "MATCH (n {graph_version: $graph_version}) "
    "WHERE any(label IN labels(n) WHERE label IN $labels) "
    "WITH count(n) AS node_count "
    "MATCH (a {graph_version: $graph_version})-[r]->(b {graph_version: $graph_version}) "
    "WHERE type(r) IN $relationships "
    "RETURN node_count, count(r) AS relationship_count"
)
_SEARCH = (
    "MATCH (n {graph_version: $graph_version}) "
    "WHERE any(label IN labels(n) WHERE label IN $labels) "
    "AND toLower(coalesce(n.title, n.name, n.code, '')) CONTAINS toLower($query) "
    "WITH n ORDER BY coalesce(n.title, n.name, n.code, '') LIMIT $seed_limit "
    "OPTIONAL MATCH (n)-[r]-(m {graph_version: $graph_version}) "
    "WHERE type(r) IN $relationships AND any(label IN labels(m) WHERE label IN $labels) "
    "RETURN n.entity_id, labels(n)[0], properties(n), "
    "r.edge_key, type(r), startNode(r).entity_id, endNode(r).entity_id, "
    "m.entity_id, labels(m)[0], properties(m) LIMIT $edge_limit"
)
_NEIGHBORS = (
    "MATCH (n {graph_version: $graph_version, entity_id: $entity_id}) "
    "WHERE any(label IN labels(n) WHERE label IN $labels) "
    "OPTIONAL MATCH (n)-[r]-(m {graph_version: $graph_version}) "
    "WHERE type(r) IN $relationships AND any(label IN labels(m) WHERE label IN $labels) "
    "RETURN n.entity_id, labels(n)[0], properties(n), "
    "r.edge_key, type(r), startNode(r).entity_id, endNode(r).entity_id, "
    "m.entity_id, labels(m)[0], properties(m) LIMIT $edge_limit"
)


class PublicGraphReader:
    """Executes only constant MATCH statements against one graph version."""

    def __init__(self, *, endpoint: str, username: str, password: str, graph_version: str, timeout: float = 3.0) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("graph endpoint must be HTTP(S)")
        if not username or not password or not graph_version:
            raise ValueError("graph credentials and version are required")
        if not 0 < timeout <= 10:
            raise ValueError("graph timeout must be between zero and ten seconds")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._endpoint = endpoint
        self._authorization = f"Basic {token}"
        self._graph_version = graph_version
        self._timeout = timeout
        self._opener = build_opener(ProxyHandler({}))

    async def stats(self) -> dict[str, int]:
        rows = await asyncio.to_thread(self._query, _GRAPH_STATS, self._base_params())
        if not rows:
            return {"nodes": 0, "relationships": 0}
        values = rows[0].get("row", [])
        if not isinstance(values, list) or len(values) != 2:
            raise RuntimeError("graph stats returned an invalid shape")
        return {"nodes": int(values[0]), "relationships": int(values[1])}

    async def search(self, query: str, *, limit: int = 30) -> dict[str, object]:
        normalized = query.strip()
        if not normalized or len(normalized) > 120:
            raise ValueError("graph query must contain 1 to 120 characters")
        if not 1 <= limit <= 30:
            raise ValueError("graph search limit must be between 1 and 30")
        params = self._base_params() | {
            "query": normalized,
            "seed_limit": min(limit, 12),
            "edge_limit": min(120, max(limit * 4, 24)),
        }
        rows = await asyncio.to_thread(self._query, _SEARCH, params)
        return self._view(rows, query=normalized, limit=min(60, limit * 2))

    async def neighbors(self, entity_id: str, *, limit: int = 40) -> dict[str, object]:
        normalized = entity_id.strip()
        if not normalized or len(normalized) > 256:
            raise ValueError("graph entity id must contain 1 to 256 characters")
        if not 1 <= limit <= 40:
            raise ValueError("neighbor limit must be between 1 and 40")
        params = self._base_params() | {"entity_id": normalized, "edge_limit": min(120, limit)}
        rows = await asyncio.to_thread(self._query, _NEIGHBORS, params)
        return self._view(rows, query=normalized, limit=min(60, limit + 1))

    def _base_params(self) -> dict[str, object]:
        return {
            "graph_version": self._graph_version,
            "labels": sorted(PUBLIC_LABELS),
            "relationships": sorted(PUBLIC_RELATIONSHIPS),
        }

    def _query(self, statement: str, parameters: Mapping[str, object]) -> list[Mapping[str, Any]]:
        body = {
            "statements": [{"statement": statement, "parameters": dict(parameters), "resultDataContents": ["row"]}]
        }
        request = Request(
            self._endpoint,
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": self._authorization, "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode())
        except HTTPError as exc:
            raise ConnectionError(f"graph query failed with HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectionError(f"graph query failed: {type(exc).__name__}") from exc
        if not isinstance(payload, Mapping) or payload.get("errors"):
            raise RuntimeError("graph query returned an error")
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return []
        data = results[0].get("data") if isinstance(results[0], Mapping) else None
        return [row for row in data if isinstance(row, Mapping)] if isinstance(data, list) else []

    def _view(self, rows: list[Mapping[str, Any]], *, query: str, limit: int) -> dict[str, object]:
        nodes: dict[str, dict[str, object]] = {}
        edges: dict[str, dict[str, str]] = {}
        truncated = len(rows) >= 120

        def add_node(entity_id: object, node_type: object, properties: object) -> None:
            if not isinstance(entity_id, str) or not entity_id or not isinstance(node_type, str):
                return
            if node_type not in PUBLIC_LABELS or len(nodes) >= limit:
                return
            safe = {
                str(key): value
                for key, value in dict(properties or {}).items()
                if str(key) in PUBLIC_PROPERTIES and isinstance(value, (str, int, float, bool))
            }
            label = str(safe.get("title") or safe.get("name") or safe.get("code") or entity_id)
            nodes[entity_id] = {
                "id": entity_id,
                "type": node_type,
                "label": label[:180],
                "subtitle": self._subtitle(node_type, safe),
                "resource_id": None,
                "properties": safe,
            }

        for row in rows:
            values = row.get("row")
            if not isinstance(values, list) or len(values) != 10:
                continue
            add_node(values[0], values[1], values[2])
            add_node(values[7], values[8], values[9])
            edge_type, source, target = values[4], values[5], values[6]
            if not all(isinstance(value, str) and value for value in (edge_type, source, target)):
                continue
            if edge_type not in PUBLIC_RELATIONSHIPS or source not in nodes or target not in nodes:
                continue
            edge_id = values[3] if isinstance(values[3], str) and values[3] else sha256(
                f"{source}:{edge_type}:{target}".encode()
            ).hexdigest()[:32]
            edges[str(edge_id)] = {
                "id": str(edge_id), "source": source, "target": target, "type": edge_type, "label": edge_type
            }
        return {
            "graph_version": self._graph_version,
            "query": query,
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "truncated": truncated or len(nodes) >= limit,
        }

    @staticmethod
    def _subtitle(node_type: str, properties: Mapping[str, object]) -> str | None:
        if node_type == "Book":
            parts = [properties.get("publisher"), properties.get("publication_year")]
            text = " · ".join(str(item) for item in parts if item)
            return text or None
        return {"Topic": "主题", "Author": "作者", "Publisher": "出版社", "Category": "分类", "Keyword": "关键词", "SubjectCode": "中图分类"}.get(node_type)


__all__ = ["PUBLIC_LABELS", "PUBLIC_RELATIONSHIPS", "PublicGraphReader"]
