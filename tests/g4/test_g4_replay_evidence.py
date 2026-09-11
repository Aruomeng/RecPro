from __future__ import annotations

import asyncio
from datetime import datetime
import json
import unittest
from uuid import UUID

from backend.app.api.recommendation import RecommendationExecutionResponse
from backend.app.recommendation.adapters.g4_mysql import (
    MySQLG4RecommendationTaskService,
)
from backend.app.shared_kernel.contracts.graph_evidence import (
    build_graph_path_reference,
)


TASK_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class ReplayCursor:
    def __init__(self, connection: "ReplayConnection") -> None:
        self._connection = connection
        self._result = ""

    async def __aenter__(self) -> "ReplayCursor":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def execute(self, query: str, params: tuple[object, ...]) -> None:
        normalized = " ".join(query.split())
        self._connection.queries.append((normalized, params))
        if normalized.startswith("SELECT t.trace_id"):
            self._result = "task"
        elif normalized.startswith("SELECT i.id"):
            self._result = "items"
        else:
            raise AssertionError(f"unexpected replay query: {normalized}")

    async def fetchone(self):
        return self._connection.task_row if self._result == "task" else None

    async def fetchall(self):
        return self._connection.item_rows if self._result == "items" else []


class ReplayConnection:
    def __init__(self, *, task_row: tuple[object, ...], item_rows: list[tuple[object, ...]]) -> None:
        self.task_row = task_row
        self.item_rows = item_rows
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def cursor(self) -> ReplayCursor:
        return ReplayCursor(self)


def replay_rows(*, graph_path_refs: list[str]) -> tuple[tuple[object, ...], list[tuple[object, ...]]]:
    graph_version = "lib-books-v2-20260828"
    task_row = (
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "COMPLETED",
        1,
        datetime(2026, 9, 10, 8, 0, 0),
        901,
        json.dumps(
            {
                "output_type": "READING_PATH",
                "delivery_strategy": "DIRECT",
                "explanation_level": "EVIDENCE",
                "adaptation_state": "NORMAL",
                "decision_reason_codes": ["DIRECT_PATH"],
                "decision_reason": "证据充分。",
                "policy_version": "policy-g4-v1",
            },
            ensure_ascii=False,
        ),
        "[]",
        json.dumps(
            {
                "config_bundle": "rec-1.0.0",
                "policy": "policy-g4-v1",
                "ranking": "ranking-g4-v1",
                "behavior_formula": "profile-g4-v1",
                "embedding": "lib-books-chroma-v1",
                "graph": graph_version,
                "prompt": None,
                "dataset": "lib-books-v1-20260810",
            }
        ),
    )
    score_detail = {
        "channel_scores": {"MYSQL": 0.7, "GRAPH": 0.85},
        "channel_ranks": {"MYSQL": 1, "GRAPH": 1},
        "rrf_score": 0.78,
        "negative_penalty": 0.0,
        "graph_path_refs": graph_path_refs,
        "graph_version": graph_version,
        "graph_path_coverage_state": "COVERED",
    }
    item_rows = [
        (
            1001,
            1,
            0.88,
            101,
            "BOOK",
            "多智能体推荐系统",
            json.dumps(["研究者"], ensure_ascii=False),
            2025,
            "AVAILABLE_BORROW",
            2,
            "图谱路径与主题语义共同支持该推荐。",
            0.78,
            "GRAPH",
            json.dumps(score_detail, ensure_ascii=False),
            json.dumps(["catalog:resource:101:metadata:1", *graph_path_refs]),
        )
    ]
    return task_row, item_rows


class G4ReplayEvidenceTests(unittest.TestCase):
    def test_replay_restores_v2_graph_evidence_and_reading_groups(self) -> None:
        path_reference = build_graph_path_reference(
            graph_version="lib-books-v2-20260828",
            node_ids=("topic:multi-agent", "work:one", "book:one"),
            edge_ids=("edge:topic", "edge:instance"),
        )
        task_row, item_rows = replay_rows(graph_path_refs=[path_reference])
        connection = ReplayConnection(task_row=task_row, item_rows=item_rows)
        service = object.__new__(MySQLG4RecommendationTaskService)

        payload = asyncio.run(service._load_execution(connection, task_id=TASK_ID))
        response = RecommendationExecutionResponse.model_validate(payload)

        self.assertEqual("FOUNDATION", response.groups[0].group_key)
        self.assertEqual(1, response.items[0].group_id)
        evidence = response.items[0].evidence
        self.assertEqual([path_reference], evidence.graph_path_refs)
        self.assertEqual("lib-books-v2-20260828", evidence.graph_version)
        self.assertEqual("COVERED", evidence.graph_path_coverage_state.value)
        self.assertEqual({"MYSQL", "GRAPH"}, set(evidence.channels))
        self.assertEqual([], response.agent_actions)
        self.assertEqual(2, len(connection.queries))

    def test_replay_fails_closed_when_persisted_v2_graph_score_lacks_path(self) -> None:
        task_row, item_rows = replay_rows(graph_path_refs=[])
        connection = ReplayConnection(task_row=task_row, item_rows=item_rows)
        service = object.__new__(MySQLG4RecommendationTaskService)

        with self.assertRaisesRegex(RuntimeError, "covered Graph evidence is inconsistent"):
            asyncio.run(service._load_execution(connection, task_id=TASK_ID))


if __name__ == "__main__":
    unittest.main()
