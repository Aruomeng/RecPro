from __future__ import annotations

import unittest
from uuid import NAMESPACE_URL, uuid5

from scripts.execute_g4_recommendation_projection import (
    SHARED_TABLES,
    TARGET_TABLES,
    canonical,
    load_request_payload,
    plan_requires_v2_graph_paths,
    validate_persisted_status_projection,
    validate_post_counts,
    validate_pre_counts,
    sha256_bytes,
)


class G4ProjectionExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        request_run_id = "g4-projection-plan-test"
        request_id = uuid5(
            NAMESPACE_URL,
            f"g4-recommendation-projection-request:{request_run_id}",
        )
        request_payload = {
            "request_id": str(request_id),
            "session_id": str(
                uuid5(
                    NAMESPACE_URL,
                    f"g4-recommendation-projection-session:{request_run_id}",
                )
            ),
            "user_id": 1001,
            "scene": "SEARCH_AFTER",
            "input_text": "多智能体系统与智慧图书馆",
            "requested_resource_types": ["BOOK"],
            "requested_output_type": "TOPIC_RESOURCES",
            "limit": 8,
            "g4_channels": ["MYSQL", "GRAPH", "VECTOR"],
        }
        targets = []
        for index, table in enumerate(TARGET_TABLES):
            before = 100 + index
            delta = (1, 8, 24, 1, 8, 8, 1, 1, 7, 7, 1, 1)[index]
            targets.append(
                {
                    "kind": "MYSQL",
                    "identifier": f"recpro.recpro.{table}",
                    "operation": "APPEND",
                    "expected_before_count": before,
                    "expected_after_min_count": before + delta,
                }
            )
        cls.plan = {
            "idempotency_key": str(request_id),
            "input_hashes": {"request_payload": sha256_bytes(canonical(request_payload))},
            "targets": targets,
            "max_changes": 68,
        }
        cls.request_run_id = request_run_id

    def test_rebuilds_frozen_request_from_reviewed_run_id(self) -> None:
        plan = self.plan
        payload = load_request_payload(
            plan, request_run_id=self.request_run_id
        )
        self.assertEqual(plan["idempotency_key"], payload["request_id"])
        self.assertEqual("SEARCH_AFTER", payload["scene"])
        self.assertEqual(["BOOK"], payload["requested_resource_types"])
        self.assertEqual(["MYSQL", "GRAPH", "VECTOR"], payload["g4_channels"])

    def test_preflight_accepts_exact_plan_counts(self) -> None:
        target_counts = {
            str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: int(
                target["expected_before_count"]
            )
            for target in self.plan["targets"]
        }
        shared_counts = {
            table: int(self.plan["targets"][0]["expected_before_count"])
            for table in (
                "resource_catalog",
                "resource_book_detail",
                "resource_index_state",
                "resource_tag",
                "tag_dictionary",
            )
        }
        before = {**target_counts, **shared_counts}
        baseline = {"before_counts": shared_counts}
        validate_pre_counts(
            plan=self.plan,
            before_counts=before,
            mysql_baseline=baseline,
            g4_baseline={"before_counts": shared_counts},
        )

    def test_postflight_requires_exact_append_and_protected_counts(self) -> None:
        before = {
            str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: int(
                target["expected_before_count"]
            )
            for target in self.plan["targets"]
        }
        before.update({table: 10 for table in SHARED_TABLES})
        before["unrelated_table"] = 3
        after = dict(before)
        for target in self.plan["targets"]:
            table = str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
            after[table] += int(target["expected_after_min_count"]) - int(
                target["expected_before_count"]
            )
        deltas = validate_post_counts(
            plan=self.plan,
            before_table_names=tuple(before),
            before_counts=before,
            after_table_names=tuple(after),
            after_counts=after,
        )
        self.assertEqual(68, sum(deltas.values()))
        self.assertEqual(24, deltas["recommendation_candidate"])

    def test_target_table_contract_is_bounded(self) -> None:
        self.assertEqual(
            set(TARGET_TABLES),
            {
                str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
                for target in self.plan["targets"]
            },
        )

    def test_stage2_plan_marker_is_explicit_and_not_inferred_from_v1_plan(self) -> None:
        self.assertFalse(plan_requires_v2_graph_paths(self.plan))
        marked = {
            **self.plan,
            "preconditions": [
                "Stage 2 v2 Graph scoring requires 100% routeable graphpath:v2 evidence; queries remain bounded to 3 hops, 10 paths, 60 nodes, 120 edges, and 3 seconds"
            ],
        }
        self.assertTrue(plan_requires_v2_graph_paths(marked))

    def test_stage2_status_projection_does_not_require_full_result_items(self) -> None:
        full = {
            "task_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "trace_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "status": "COMPLETED",
            "context_version": 1,
            "record_id": 91,
            "warnings": [],
            "items": [{"evidence": {"channels": ["MYSQL", "GRAPH"]}}],
            "versions": {
                "config_bundle": "rec-1.0.0",
                "policy": "policy-rule-v1",
                "ranking": "ranking-g4-v1",
                "behavior_formula": "profile-g4-v1",
                "dataset": "lib-books-v1-20260810",
                "embedding": "hash-char-ngram-v1",
                "graph": "lib-books-v2-20260828",
                "prompt": "prompt-v1",
            },
        }
        status = {
            key: full[key]
            for key in (
                "task_id",
                "trace_id",
                "status",
                "context_version",
                "record_id",
                "warnings",
            )
        }
        status["versions"] = {
            key: full["versions"][key]
            for key in (
                "config_bundle",
                "policy",
                "ranking",
                "behavior_formula",
                "dataset",
            )
        }

        summary = validate_persisted_status_projection(full, status)

        self.assertEqual(91, summary["record_id"])
        self.assertNotIn("items", status)
        self.assertNotIn("graph", status["versions"])

    def test_stage2_status_projection_rejects_identity_drift(self) -> None:
        full = {
            "task_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "trace_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "status": "COMPLETED",
            "context_version": 1,
            "record_id": 91,
            "warnings": [],
            "versions": {
                "config_bundle": "rec-1.0.0",
                "policy": "policy-rule-v1",
                "ranking": "ranking-g4-v1",
                "behavior_formula": "profile-g4-v1",
                "dataset": "lib-books-v1-20260810",
            },
        }
        status = {**full, "task_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}

        with self.assertRaisesRegex(RuntimeError, "task_id"):
            validate_persisted_status_projection(full, status)


if __name__ == "__main__":
    unittest.main()
