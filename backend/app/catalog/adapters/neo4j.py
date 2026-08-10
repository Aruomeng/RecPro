"""Read-only Neo4j graph recall adapter for the library graph boundary."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from backend.app.catalog.domain.models import GraphRecallEvidence


_GRAPH_VERSION_LIMIT = 64
_MAX_TERMS = 16
_MAX_LIMIT = 50
_RECALL_QUERY = (
    "MATCH (b:Book {graph_version: $graph_version})-[:IN_TOPIC|HAS_KEYWORD|CLASSIFIED_AS]->(term) "
    "WHERE term.name IN $terms OR term.code IN $terms "
    "WITH b, count(DISTINCT term) AS match_count, "
    "collect(DISTINCT coalesce(term.name, term.code, ''))[..8] AS matched_terms "
    "RETURN b.entity_id AS external_id, "
    "CASE WHEN size($terms) = 0 THEN 0.0 ELSE toFloat(match_count) / toFloat(size($terms)) END AS score, "
    "matched_terms ORDER BY score DESC, external_id ASC LIMIT $limit"
)


class Neo4jGraphReader:
    """Dependency-light HTTP reader with no Cypher write capability."""

    def __init__(
        self,
        *,
        endpoint: str,
        username: str,
        password: str,
        timeout: float = 5.0,
    ) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Neo4j graph endpoint must be an HTTP(S) URL")
        if not username or not password:
            raise ValueError("Neo4j graph credentials are required")
        if timeout <= 0 or timeout > 30:
            raise ValueError("Neo4j graph timeout must be between 0 and 30 seconds")
        self._endpoint = endpoint
        self._timeout = timeout
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self._authorization = f"Basic {token}"
        self._opener = build_opener(ProxyHandler({}))

    async def recall(
        self,
        *,
        terms: tuple[str, ...],
        graph_version: str,
        limit: int,
    ) -> tuple[GraphRecallEvidence, ...]:
        normalized_terms = tuple(dict.fromkeys(item.strip() for item in terms if item and item.strip()))
        if not normalized_terms:
            return ()
        if len(normalized_terms) > _MAX_TERMS:
            raise ValueError("graph recall accepts at most 16 terms")
        if not graph_version or len(graph_version) > _GRAPH_VERSION_LIMIT:
            raise ValueError("graph version is invalid")
        if not 1 <= limit <= _MAX_LIMIT:
            raise ValueError("graph recall limit must be between 1 and 50")
        rows = await asyncio.to_thread(
            self._run_query,
            {"graph_version": graph_version, "terms": list(normalized_terms), "limit": limit},
        )
        return tuple(self._parse_row(row, graph_version=graph_version) for row in rows)

    def _run_query(self, parameters: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        request = Request(
            self._endpoint,
            data=json.dumps(
                {"statements": [{"statement": _RECALL_QUERY, "parameters": dict(parameters)}]},
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Authorization": self._authorization,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ConnectionError(f"Neo4j graph query failed with status {exc.code}") from exc
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectionError(f"Neo4j graph query failed: {type(exc).__name__}") from exc
        if not isinstance(payload, Mapping) or payload.get("errors"):
            raise RuntimeError("Neo4j graph query returned an error")
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return []
        data = results[0].get("data") if isinstance(results[0], Mapping) else None
        return [row for row in data if isinstance(row, Mapping)] if isinstance(data, list) else []

    @staticmethod
    def _parse_row(row: Mapping[str, Any], *, graph_version: str) -> GraphRecallEvidence:
        values = row.get("row")
        if not isinstance(values, list) or len(values) != 3:
            raise RuntimeError("Neo4j graph recall returned an unexpected row shape")
        external_id, score, matched_terms = values
        if not isinstance(external_id, str) or not external_id:
            raise RuntimeError("Neo4j graph recall returned an invalid external ID")
        if not isinstance(score, (int, float)):
            raise RuntimeError("Neo4j graph recall returned an invalid score")
        if not isinstance(matched_terms, list):
            raise RuntimeError("Neo4j graph recall returned invalid evidence terms")
        bounded_score = max(0.0, min(1.0, float(score)))
        return GraphRecallEvidence(
            external_id=external_id,
            score=round(bounded_score, 6),
            matched_terms=tuple(str(term) for term in matched_terms if str(term).strip()),
            graph_version=graph_version,
        )


__all__ = ["Neo4jGraphReader"]
