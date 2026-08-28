"""Read-only Neo4j graph recall adapter for the library graph boundary."""

from __future__ import annotations

import asyncio
import base64
import json
from hashlib import sha256
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
_V2_RECALL_QUERY = (
    "MATCH p=(b:Book {graph_version: $graph_version})-[:INSTANCE_OF|IN_TOPIC|HAS_TOPIC|HAS_KEYWORD|CLASSIFIED_AS|AUTHORED_BY|PUBLISHED_BY|HAS_SUBJECT_CODE*1..3]-(term) "
    "WHERE (term.name IN $terms OR term.code IN $terms) "
    "AND all(node IN nodes(p) WHERE node.graph_version = $graph_version) "
    "WITH b, p, term ORDER BY length(p), b.entity_id, coalesce(term.name, term.code, '') "
    "WITH b, collect({matched_term: coalesce(term.name, term.code, ''), hop_count: length(p), "
    "node_ids: [node IN nodes(p) | node.entity_id], "
    "edge_ids: [rel IN relationships(p) | rel.edge_key]})[..32] AS path_evidence "
    "RETURN b.entity_id AS external_id, path_evidence "
    "ORDER BY external_id LIMIT $limit"
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
        v2 = graph_version.startswith("lib-books-v2-")
        parameters = {
            "graph_version": graph_version,
            "terms": list(normalized_terms),
            "limit": limit,
        }
        # Keep the established one-argument adapter seam for v1 fixtures and
        # deployments.  Only the explicitly versioned v2 path uses the second
        # constant statement; caller input is never accepted as Cypher.
        rows = await asyncio.to_thread(
            self._run_query,
            parameters,
            _V2_RECALL_QUERY,
        ) if v2 else await asyncio.to_thread(self._run_query, parameters)
        if v2:
            return tuple(
                self._parse_v2_row(
                    row,
                    graph_version=graph_version,
                    requested_terms=normalized_terms,
                )
                for row in rows
            )
        return tuple(self._parse_row(row, graph_version=graph_version) for row in rows)

    def _run_query(
        self,
        parameters: Mapping[str, Any],
        statement: str = _RECALL_QUERY,
    ) -> list[Mapping[str, Any]]:
        request = Request(
            self._endpoint,
            data=json.dumps(
                {"statements": [{"statement": statement, "parameters": dict(parameters)}]},
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

    @staticmethod
    def _parse_v2_row(
        row: Mapping[str, Any],
        *,
        graph_version: str,
        requested_terms: tuple[str, ...],
    ) -> GraphRecallEvidence:
        values = row.get("row")
        if not isinstance(values, list) or len(values) != 2:
            raise RuntimeError("Neo4j v2 graph recall returned an unexpected row shape")
        external_id, raw_paths = values
        if not isinstance(external_id, str) or not external_id or not isinstance(raw_paths, list):
            raise RuntimeError("Neo4j v2 graph recall returned invalid path evidence")
        valid: list[tuple[int, str, str]] = []
        for raw in raw_paths[:32]:
            if not isinstance(raw, Mapping):
                continue
            term = str(raw.get("matched_term", "")).strip()
            hop_count = raw.get("hop_count")
            node_ids = raw.get("node_ids")
            edge_ids = raw.get("edge_ids")
            if (
                term not in requested_terms
                or not isinstance(hop_count, int)
                or not 1 <= hop_count <= 3
                or not isinstance(node_ids, list)
                or len(node_ids) != hop_count + 1
                or not isinstance(edge_ids, list)
                or len(edge_ids) != hop_count
                or any(not isinstance(item, str) or not item for item in node_ids + edge_ids)
            ):
                continue
            path_ref = "graphpath:" + sha256(
                f"{graph_version}:{':'.join(node_ids)}:{':'.join(edge_ids)}".encode()
            ).hexdigest()[:32]
            valid.append((hop_count, term, path_ref))
        if not valid:
            return GraphRecallEvidence(
                external_id=external_id,
                score=0.0,
                matched_terms=(),
                graph_version=graph_version,
                graph_path_refs=(),
            )
        valid.sort(key=lambda item: (item[0], item[1], item[2]))
        matched_terms = tuple(dict.fromkeys(item[1] for item in valid))
        match_ratio = len(matched_terms) / max(1, len(requested_terms))
        score = max(match_ratio * (0.85 ** (item[0] - 1)) for item in valid)
        path_refs = tuple(dict.fromkeys(item[2] for item in valid))[:3]
        return GraphRecallEvidence(
            external_id=external_id,
            score=round(max(0.0, min(1.0, score)), 6),
            matched_terms=matched_terms,
            graph_version=graph_version,
            graph_path_refs=path_refs,
        )


__all__ = ["Neo4jGraphReader"]
