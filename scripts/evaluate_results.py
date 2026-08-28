"""Compute reproducible metrics from immutable experiment predictions."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts.evaluation_runtime import percentile, read_json, read_jsonl, sha256_file, write_json_exclusive
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from evaluation_runtime import percentile, read_json, read_jsonl, sha256_file, write_json_exclusive


def _dcg(resource_ids: list[int], relevance: Mapping[int, int], k: int) -> float:
    return sum((2 ** relevance.get(resource_id, 0) - 1) / math.log2(rank + 2) for rank, resource_id in enumerate(resource_ids[:k]))


def _ndcg(resource_ids: list[int], relevance: Mapping[int, int], k: int) -> float:
    actual = _dcg(resource_ids, relevance, k)
    ideal_values = sorted(relevance.values(), reverse=True)[:k]
    ideal = sum((2 ** value - 1) / math.log2(rank + 2) for rank, value in enumerate(ideal_values))
    return actual / ideal if ideal else 0.0


def _recall(resource_ids: list[int], relevance: Mapping[int, int], k: int) -> float:
    positives = {resource_id for resource_id, value in relevance.items() if value >= 2}
    return len(positives & set(resource_ids[:k])) / len(positives) if positives else 0.0


def _mrr(resource_ids: list[int], relevance: Mapping[int, int]) -> float:
    for rank, resource_id in enumerate(resource_ids, 1):
        if relevance.get(resource_id, 0) >= 2:
            return 1.0 / rank
    return 0.0


def _macro_f1(expected: list[str], actual: list[str]) -> float:
    labels = sorted(set(expected) | set(actual))
    scores: list[float] = []
    for label in labels:
        tp = sum(1 for truth, prediction in zip(expected, actual) if truth == label and prediction == label)
        fp = sum(1 for truth, prediction in zip(expected, actual) if truth != label and prediction == label)
        fn = sum(1 for truth, prediction in zip(expected, actual) if truth == label and prediction != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def evaluate(run_dir: Path, *, write: bool) -> dict[str, Any]:
    manifest_path = run_dir / "run-manifest.json"
    manifest = read_json(manifest_path)
    prediction_path = run_dir / str(manifest["predictions"]["path"])
    if sha256_file(prediction_path) != manifest["predictions"]["sha256"]:
        raise ValueError("prediction hash does not match the frozen run manifest")
    if manifest.get("classification") != "DEVELOPMENT_PROXY":
        raise ValueError("this evaluator requires an explicitly classified input")
    split_dir = Path(str(manifest["split"]["path"]))
    split_manifest = read_json(split_dir / "manifest.json")
    tasks = {str(row["task_id"]): row for row in read_jsonl(split_dir / str(split_manifest["splits"]["test"]["path"]))}
    resources = {int(row["resource_id"]): row for row in read_jsonl(split_dir / str(split_manifest["resources"]["path"]))}
    predictions = read_jsonl(prediction_path)
    by_system: dict[str, list[dict[str, Any]]] = {}
    for row in predictions:
        if row["task_id"] not in tasks:
            raise ValueError("prediction references a task outside the frozen test split")
        by_system.setdefault(str(row["system_id"]), []).append(row)
    metrics: dict[str, Any] = {}
    for system_id, rows in sorted(by_system.items()):
        rows.sort(key=lambda item: item["task_id"])
        ndcg5: list[float] = []; ndcg10: list[float] = []; recall5: list[float] = []; recall10: list[float] = []; mrr: list[float] = []
        output_expected: list[str] = []; output_actual: list[str] = []; delivery_expected: list[str] = []; delivery_actual: list[str] = []
        unique_resources: set[int] = set(); diversity: list[float] = []; latencies: list[float] = []
        for row in rows:
            task = tasks[str(row["task_id"])]
            relevance = {int(item["resource_id"]): int(item["relevance"]) for item in task["judgments"]}
            resource_ids = [int(item) for item in row["resource_ids"]]
            ndcg5.append(_ndcg(resource_ids, relevance, 5)); ndcg10.append(_ndcg(resource_ids, relevance, 10))
            recall5.append(_recall(resource_ids, relevance, 5)); recall10.append(_recall(resource_ids, relevance, 10)); mrr.append(_mrr(resource_ids, relevance))
            unique_resources.update(resource_ids)
            topics = {str(resources[item]["topic"]) for item in resource_ids if item in resources}
            diversity.append(len(topics) / max(1, len(resource_ids)))
            output_expected.append(str(task["expected_output_type"])); output_actual.append(str(row["output_type"]))
            delivery_expected.append(str(task["expected_delivery_strategy"])); delivery_actual.append(str(row["delivery_strategy"]))
            latencies.append(float(row["latency_ms"]))
        metrics[system_id] = {
            "tasks": len(rows), "ndcg_at_5": _mean(ndcg5), "ndcg_at_10": _mean(ndcg10),
            "recall_at_5": _mean(recall5), "recall_at_10": _mean(recall10), "mrr": _mean(mrr),
            "resource_coverage": round(len(unique_resources) / max(1, len(resources)), 6),
            "intra_list_topic_diversity": _mean(diversity),
            "output_type_macro_f1": round(_macro_f1(output_expected, output_actual), 6),
            "delivery_strategy_macro_f1": round(_macro_f1(delivery_expected, delivery_actual), 6),
            "trace_completeness": _mean([1.0 if row.get("trace_complete") else 0.0 for row in rows]),
            "latency_ms": {"p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95), "p99": percentile(latencies, 0.99), "kind": "DETERMINISTIC_PROXY_ESTIMATE"},
        }
    fairness: dict[str, Any] = {}
    for left, right in (("B2", "Proposed"), ("B3", "Proposed")):
        left_rows = {row["task_id"]: row for row in by_system.get(left, [])}
        right_rows = {row["task_id"]: row for row in by_system.get(right, [])}
        fairness[f"{left}_vs_{right}"] = {
            "same_tasks": set(left_rows) == set(right_rows),
            "same_candidates_and_scores": set(left_rows) == set(right_rows) and all(left_rows[key]["resource_ids"] == right_rows[key]["resource_ids"] and left_rows[key]["scores"] == right_rows[key]["scores"] for key in left_rows),
        }
    fault_summary: dict[str, Any] = {"rows": 0, "degradation_success_rate": None, "trace_completeness": None, "fair_tool_contract": None}
    fault_meta = manifest.get("fault_predictions")
    if isinstance(fault_meta, Mapping):
        fault_path = run_dir / str(fault_meta["path"])
        if sha256_file(fault_path) != fault_meta["sha256"]:
            raise ValueError("fault prediction hash does not match the frozen manifest")
        fault_rows = read_jsonl(fault_path)
        pairs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in fault_rows:
            pairs.setdefault((str(row["fault_id"]), str(row["task_id"])), []).append(row)
        fault_summary = {
            "rows": len(fault_rows),
            "faults": dict(Counter(str(row["fault_id"]) for row in fault_rows)),
            "degradation_success_rate": _mean([1.0 if row["degradation_success"] else 0.0 for row in fault_rows]),
            "trace_completeness": _mean([1.0 if row["trace_complete"] else 0.0 for row in fault_rows]),
            "fair_tool_contract": all(len(rows) == 2 and rows[0]["tools"] == rows[1]["tools"] and rows[0]["timeout_ms"] == rows[1]["timeout_ms"] for rows in pairs.values()),
        }
    result = {
        "schema_version": "experiment-metrics-v1", "classification": "DEVELOPMENT_PROXY", "confirmation_eligible": False,
        "run_id": manifest["run_id"], "prediction_sha256": manifest["predictions"]["sha256"],
        "metrics": metrics, "fairness_checks": fairness, "fault_matrix": fault_summary,
        "interpretation_limit": "Runner correctness and mechanism differences only; not evidence of real-user recommendation accuracy.",
        "safety": {"database_writes": 0, "deepseek_requests": 0, "deletions": 0},
    }
    if write:
        write_json_exclusive(run_dir / "metrics.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = evaluate(args.run_dir.resolve(), write=args.write)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[FAIL] experiment metrics were not produced: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
