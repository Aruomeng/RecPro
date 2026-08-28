from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_experiment_report import build as build_report
from scripts.evaluate_results import evaluate
from scripts.evaluation_runtime import sha256_file, write_json_exclusive, write_jsonl_exclusive
from scripts.run_experiment import execute as run_experiment


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DevelopmentExperimentRunnerTest(unittest.TestCase):
    def _split(self, root: Path) -> Path:
        split = root / "split"
        split.mkdir()
        resources = [
            {"resource_id": 1, "title": "知识图谱导论", "topic": "知识图谱", "category_code": "T", "category_label": "工业技术", "subject_codes": ["TP18"], "keywords": ["图谱"], "popularity_proxy": 0.7},
            {"resource_id": 2, "title": "多智能体推荐", "topic": "推荐系统", "category_code": "T", "category_label": "工业技术", "subject_codes": ["TP18"], "keywords": ["智能体"], "popularity_proxy": 0.8},
            {"resource_id": 3, "title": "智慧图书馆", "topic": "图书馆学", "category_code": "G", "category_label": "文化教育", "subject_codes": ["G250"], "keywords": ["图书馆"], "popularity_proxy": 0.5},
            {"resource_id": 4, "title": "普通心理学", "topic": "心理学", "category_code": "B", "category_label": "哲学", "subject_codes": ["B84"], "keywords": ["心理"], "popularity_proxy": 0.9},
        ]
        tasks = [
            {"task_id": "proxy-topic-knowledge", "entity_type": "TOPIC", "entity_key": "知识图谱", "query": "知识图谱", "expected_output_type": "TOPIC_RESOURCES", "expected_delivery_strategy": "DIRECT", "evaluation_at": "2026-08-28T00:00:00Z", "judgments": [{"resource_id": 1, "relevance": 3, "graph_hops": 1}, {"resource_id": 2, "relevance": 1, "graph_hops": 3}]},
            {"task_id": "proxy-subject-tp18", "entity_type": "SUBJECT_CODE", "entity_key": "TP18", "query": "TP18", "expected_output_type": "READING_PATH", "expected_delivery_strategy": "CLARIFY", "evaluation_at": "2026-08-28T00:00:00Z", "judgments": [{"resource_id": 1, "relevance": 3, "graph_hops": 1}, {"resource_id": 2, "relevance": 3, "graph_hops": 1}]},
        ]
        resource_count, resource_sha = write_jsonl_exclusive(split / "resources.jsonl", resources)
        test_count, test_sha = write_jsonl_exclusive(split / "test.jsonl", tasks)
        write_json_exclusive(split / "manifest.json", {
            "classification": "DEVELOPMENT_PROXY", "confirmation_eligible": False,
            "resources": {"path": "resources.jsonl", "count": resource_count, "sha256": resource_sha},
            "splits": {"test": {"path": "test.jsonl", "count": test_count, "sha256": test_sha}},
        })
        return split

    def test_suite_is_deterministic_fair_and_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split = self._split(root)
            output = root / "runs"
            config = PROJECT_ROOT / "experiments" / "configs" / "development_suite.json"
            first = run_experiment(config_path=config, split_dir=split, output_root=output, run_id="development-run-one", seed=7, write=True, include_fault_matrix=True)
            second = run_experiment(config_path=config, split_dir=split, output_root=output, run_id="development-run-two", seed=7, write=False, include_fault_matrix=True)
            self.assertEqual(first["semantic_result_sha256"], second["semantic_result_sha256"])
            self.assertEqual(0, first["safety"]["deepseek_requests"])
            metrics = evaluate(output / "development-run-one", write=True)
            self.assertTrue(metrics["fairness_checks"]["B2_vs_Proposed"]["same_candidates_and_scores"])
            self.assertTrue(metrics["fairness_checks"]["B3_vs_Proposed"]["same_candidates_and_scores"])
            self.assertTrue(metrics["fault_matrix"]["fair_tool_contract"])
            report = build_report(output / "development-run-one", write=True)
            self.assertEqual("DEVELOPMENT_PROXY", report["classification"])
            with self.assertRaises(FileExistsError):
                run_experiment(config_path=config, split_dir=split, output_root=output, run_id="development-run-one", seed=7, write=True, include_fault_matrix=False)
            with self.assertRaises(FileExistsError):
                evaluate(output / "development-run-one", write=True)
            self.assertTrue((output / "development-run-one" / "ndcg-at-10.svg").is_file())


if __name__ == "__main__":
    unittest.main()
