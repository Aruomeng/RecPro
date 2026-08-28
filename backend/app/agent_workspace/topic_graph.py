"""Bounded, public session topic graph used by the global Agent workspace."""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Mapping


NODE_TYPES = frozenset({"QUERY", "TOPIC", "RESOURCE", "ROUTE", "RECOMMENDATION_TASK"})
EDGE_TYPES = frozenset({"MENTIONS", "EXPLORED", "OPENED", "RECOMMENDED", "REJECTED", "CONTINUES"})
_SEPARATORS = re.compile(r"[\s,，。；;、/|+]+")
_KNOWN_TOPICS = (
    "多智能体", "推荐系统", "知识图谱", "智慧图书馆", "人工智能", "机器学习",
)


def _stable_id(kind: str, value: str) -> str:
    digest = sha256(f"{kind}:{value.strip().lower()}".encode()).hexdigest()[:20]
    return f"{kind.lower()}:{digest}"


class SessionTopicGraph:
    """Accumulate only public session concepts without persistence or LLM use."""

    def __init__(self, *, max_nodes: int = 64, max_edges: int = 128) -> None:
        if not 1 <= max_nodes <= 64 or not 1 <= max_edges <= 128:
            raise ValueError("session topic graph bounds exceed the public contract")
        self._max_nodes = max_nodes
        self._max_edges = max_edges
        self._nodes: dict[str, dict[str, object]] = {}
        self._edges: dict[str, dict[str, object]] = {}
        self._version = 1
        self._truncated = False
        self._last_node_id: str | None = None

    def observe(
        self,
        event_type: str,
        payload: Mapping[str, object],
        *,
        observed_at: str,
    ) -> None:
        before = (len(self._nodes), len(self._edges))
        if event_type == "QUERY_SUBMITTED":
            query = str(payload.get("query", "")).strip()[:200]
            if query:
                query_id = self._node("QUERY", query, query, observed_at, ("session:query",))
                self._continue(query_id, observed_at)
                for topic in self.extract_topics(query, payload):
                    topic_id = self._node("TOPIC", topic, topic, observed_at, ("session:query",))
                    self._edge(query_id, topic_id, "MENTIONS")
        elif event_type == "GRAPH_NODE_SELECTED":
            label = str(payload.get("label") or payload.get("title") or "知识实体").strip()[:120]
            entity_id = str(payload.get("entity_id") or _stable_id("TOPIC", label))[:160]
            node_type = "RESOURCE" if str(payload.get("type", "")).upper() in {"BOOK", "WORK"} else "TOPIC"
            node_id = self._node(node_type, entity_id, label, observed_at, (f"neo4j:{entity_id}",))
            self._continue(node_id, observed_at, edge_type="EXPLORED")
        elif event_type == "RESOURCE_OPENED":
            resource_id = str(payload.get("resource_id") or payload.get("entity_id") or "").strip()
            title = str(payload.get("title") or payload.get("label") or f"资源 {resource_id}").strip()[:120]
            if resource_id:
                node_id = self._node("RESOURCE", f"resource:{resource_id}", title, observed_at, (f"resource:{resource_id}",))
                self._continue(node_id, observed_at, edge_type="OPENED")
        elif event_type == "ROUTE_CHANGED":
            route = str(payload.get("route", "/")).strip()[:80]
            node_id = self._node("ROUTE", route, route, observed_at, ("session:route",))
            self._continue(node_id, observed_at)
        elif event_type == "RECOMMENDATION_COMPLETED":
            task_id = str(payload.get("task_id", "")).strip()
            if task_id:
                node_id = self._node(
                    "RECOMMENDATION_TASK", f"task:{task_id}", "推荐任务", observed_at,
                    (f"task:{task_id}",),
                )
                self._continue(node_id, observed_at, edge_type="RECOMMENDED")
        elif event_type == "FEEDBACK_RECORDED" and str(payload.get("feedback_type", "")).upper() in {
            "DISLIKE", "NOT_INTERESTED",
        }:
            resource_id = str(payload.get("resource_id", "")).strip()
            if resource_id:
                node_id = self._node(
                    "RESOURCE", f"resource:{resource_id}",
                    str(payload.get("title") or f"资源 {resource_id}")[:120], observed_at,
                    (f"resource:{resource_id}",),
                )
                if self._last_node_id and self._last_node_id != node_id:
                    self._edge(self._last_node_id, node_id, "REJECTED")
        if before != (len(self._nodes), len(self._edges)):
            self._version += 1

    @staticmethod
    def extract_topics(query: str, payload: Mapping[str, object] | None = None) -> tuple[str, ...]:
        topics: list[str] = []
        raw_topics = (payload or {}).get("topics", [])
        if isinstance(raw_topics, list):
            topics.extend(str(item).strip() for item in raw_topics[:8])
        topics.extend(topic for topic in _KNOWN_TOPICS if topic in query)
        topics.extend(
            token for token in _SEPARATORS.split(query) if 2 <= len(token) <= 24
        )
        unique: list[str] = []
        for topic in topics:
            clean = topic.strip()[:80]
            if clean and clean not in unique:
                unique.append(clean)
        return tuple(unique[:8])

    def top_topics(self, *, limit: int = 8) -> tuple[str, ...]:
        topics = [node for node in self._nodes.values() if node["type"] == "TOPIC"]
        topics.sort(key=lambda item: (-float(item["weight"]), str(item["label"])))
        return tuple(str(item["label"]) for item in topics[:limit])

    def snapshot(self) -> dict[str, object]:
        return {
            "version": self._version,
            "nodes": list(self._nodes.values()),
            "edges": list(self._edges.values()),
            "truncated": self._truncated,
        }

    def _node(
        self,
        node_type: str,
        node_id: str,
        label: str,
        observed_at: str,
        evidence_refs: tuple[str, ...],
    ) -> str:
        if node_type not in NODE_TYPES:
            raise ValueError("session topic node type is not allowed")
        stable_id = node_id if ":" in node_id else _stable_id(node_type, node_id)
        existing = self._nodes.get(stable_id)
        if existing is not None:
            existing["weight"] = min(10.0, float(existing["weight"]) + 1.0)
            existing["last_seen_at"] = observed_at
            return stable_id
        if len(self._nodes) >= self._max_nodes:
            self._truncated = True
            return stable_id
        self._nodes[stable_id] = {
            "id": stable_id,
            "type": node_type,
            "label": label[:120],
            "weight": 1.0,
            "first_seen_at": observed_at,
            "last_seen_at": observed_at,
            "evidence_refs": list(evidence_refs[:8]),
        }
        return stable_id

    def _continue(self, node_id: str, observed_at: str, *, edge_type: str = "CONTINUES") -> None:
        if node_id not in self._nodes:
            return
        if self._last_node_id and self._last_node_id != node_id:
            self._edge(self._last_node_id, node_id, edge_type)
        self._last_node_id = node_id

    def _edge(self, source: str, target: str, edge_type: str) -> None:
        if edge_type not in EDGE_TYPES or source not in self._nodes or target not in self._nodes:
            return
        edge_id = _stable_id("EDGE", f"{source}:{edge_type}:{target}")
        existing = self._edges.get(edge_id)
        if existing is not None:
            existing["weight"] = min(10.0, float(existing["weight"]) + 1.0)
            return
        if len(self._edges) >= self._max_edges:
            self._truncated = True
            return
        self._edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "type": edge_type,
            "weight": 1.0,
        }


__all__ = ["EDGE_TYPES", "NODE_TYPES", "SessionTopicGraph"]
