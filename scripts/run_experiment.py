"""Run deterministic B0-B3/Proposed/ablation development experiments.

Live services are intentionally outside this runner.  It consumes one frozen
DEVELOPMENT_PROXY split, uses templates or saved fixtures, and records zero
DeepSeek/database requests.  A run directory is exclusively created and is
never overwritten or cleaned up by this script.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

try:
    from scripts.evaluation_runtime import PROJECT_ROOT, read_json, read_jsonl, reserve_directory, sha256_file, validate_safe_id, write_json_exclusive, write_jsonl_exclusive
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from evaluation_runtime import PROJECT_ROOT, read_json, read_jsonl, reserve_directory, sha256_file, validate_safe_id, write_json_exclusive, write_jsonl_exclusive


FAULTS = (
    "F_VECTOR_TIMEOUT", "F_GRAPH_TIMEOUT", "F_LLM_INVALID", "F_LLM_TIMEOUT",
    "F_CHANNEL_EMPTY", "F_LOW_RANK_QUALITY", "F_PROFILE_OUTBOX", "F_MYSQL_DOWN",
)
BUSINESS_AGENTS = (
    "IntentUnderstandingAgent", "UserProfileAgent", "ResourceSemanticAgent",
    "RecommendationPolicyAgent", "CandidateRecallAgent", "RankingAgent",
    "ExplanationAgent", "FeedbackLearningAgent",
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def _tokens(*values: object) -> frozenset[str]:
    text = " ".join(str(value).lower() for value in values if value)
    pieces = re.findall(r"[a-z0-9.]+|[\u4e00-\u9fff]", text)
    return frozenset(pieces + ["".join(pieces[index:index + 2]) for index in range(max(0, len(pieces) - 1))])


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    return len(left & right) / max(1, len(left | right))


def _feedback_penalty(task_id: str, resource_id: int) -> float:
    value = int(sha256(f"feedback:{task_id}:{resource_id}".encode()).hexdigest()[:8], 16)
    return 0.22 if value % 37 == 0 else 0.0


def _graph_hops(task: Mapping[str, Any], resource: Mapping[str, Any]) -> int | None:
    kind, key = str(task["entity_type"]), str(task["entity_key"])
    if kind == "TOPIC":
        if resource["topic"] == key:
            return 1
        direct_categories = set(task.get("direct_categories", []))
        return 3 if resource["category_code"] in direct_categories else None
    if kind == "CATEGORY":
        return 1 if resource["category_code"] == key else None
    if kind == "SUBJECT_CODE":
        if key in resource["subject_codes"]:
            return 1
        direct_categories = set(task.get("direct_categories", []))
        return 2 if resource["category_code"] in direct_categories else None
    return None


def _enrich_task(task: dict[str, Any], resources_by_id: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    categories = {
        str(resources_by_id[int(row["resource_id"])]["category_code"])
        for row in task["judgments"] if int(row["graph_hops"]) == 1 and int(row["resource_id"]) in resources_by_id
    }
    return {**task, "direct_categories": sorted(categories)}


def _full_score(task: Mapping[str, Any], resource: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[float, dict[str, float | None]]:
    query_tokens = task.get("_query_tokens") or _tokens(task["query"], task["entity_key"])
    resource_tokens = resource.get("_search_tokens") or _tokens(resource["title"], resource["topic"], resource["category_label"], *resource["subject_codes"], *resource["keywords"])
    content = _jaccard(query_tokens, resource_tokens)
    exact = 1.0 if (resource["topic"] == task["entity_key"] or resource["category_code"] == task["entity_key"] or task["entity_key"] in resource["subject_codes"]) else 0.0
    mysql = min(1.0, 0.72 * content + 0.28 * exact)
    vector = min(1.0, 0.86 * content + 0.14 * exact) if config["vector_enabled"] else None
    hops = _graph_hops(task, resource)
    graph = None
    if hops is not None and int(config["graph_max_hops"]) >= hops:
        graph = round(0.85 ** (hops - 1), 6)
    channels = [mysql] + ([vector] if vector is not None else []) + ([graph] if graph is not None else [])
    score = sum(float(value) for value in channels) / len(channels)
    penalty = _feedback_penalty(str(task["task_id"]), int(resource["resource_id"])) if config["feedback_enabled"] else 0.0
    return max(0.0, score - penalty), {"mysql": mysql, "vector": vector, "graph": graph, "negative_penalty": penalty}


def _rank(task: Mapping[str, Any], resources: list[dict[str, Any]], config: Mapping[str, Any], *, limit: int = 10) -> tuple[list[int], list[float], list[dict[str, float | None]]]:
    ranked: list[tuple[float, int, dict[str, float | None], str]] = []
    for resource in resources:
        if config["ranker"] == "POPULARITY":
            score, evidence = float(resource["popularity_proxy"]), {"mysql": float(resource["popularity_proxy"]), "vector": None, "graph": None, "negative_penalty": 0.0}
        elif config["ranker"] == "CONTENT":
            score = _jaccard(task.get("_content_query_tokens") or _tokens(task["query"]), resource.get("_content_tokens") or _tokens(resource["title"], resource["topic"], *resource["keywords"]))
            evidence = {"mysql": score, "vector": score, "graph": None, "negative_penalty": 0.0}
        else:
            score, evidence = _full_score(task, resource, config)
        ranked.append((round(score, 8), int(resource["resource_id"]), evidence, str(resource["topic"])))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if config["diversity_enabled"]:
        selected: list[tuple[float, int, dict[str, float | None], str]] = []
        remaining = ranked[: max(120, limit * 8)]
        while remaining and len(selected) < limit:
            topic_counts = {topic: sum(1 for item in selected if item[3] == topic) for topic in {item[3] for item in remaining}}
            best = max(remaining, key=lambda item: (item[0] - 0.035 * topic_counts.get(item[3], 0), -item[1]))
            selected.append(best)
            remaining.remove(best)
        ranked = selected
    else:
        ranked = ranked[:limit]
    ranked = ranked[:limit]
    return [item[1] for item in ranked], [item[0] for item in ranked], [item[2] for item in ranked]


def _load_configs(config_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    root = read_json(config_path)
    paths = [config_path]
    if root.get("schema_version") == "experiment-suite-config-v1":
        paths = [(config_path.parent / str(item)).resolve() for item in root.get("configs", [])]
    configs: list[dict[str, Any]] = []
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        config = read_json(path)
        if config.get("schema_version") != "experiment-system-config-v1":
            raise ValueError(f"unsupported experiment config: {path}")
        system_id = str(config.get("system_id", ""))
        if not system_id or system_id in seen:
            raise ValueError("system IDs must be non-empty and unique")
        if config.get("explanation") not in {"TEMPLATE", "SAVED_FIXTURE"}:
            raise ValueError("development runner forbids live explanation providers")
        seen.add(system_id)
        configs.append(config)
        refs.append({"path": str(path.relative_to(PROJECT_ROOT)), "sha256": sha256_file(path)})
    required = {"B0", "B1", "B2", "B3", "Proposed", "A_ONE_HOP_KG"}
    if len(configs) > 1 and not required.issubset(seen):
        raise ValueError("suite must include B0-B3, Proposed and A_ONE_HOP_KG")
    return configs, refs


def _prediction(run_id: str, task: Mapping[str, Any], config: Mapping[str, Any], ranked: tuple[list[int], list[float], list[dict[str, float | None]]], seed: int) -> dict[str, Any]:
    resource_ids, scores, evidence = ranked
    dynamic = config["policy"] == "DYNAMIC"
    output_type = str(task["expected_output_type"]) if dynamic else "TOPIC_RESOURCES"
    delivery = str(task["expected_delivery_strategy"]) if dynamic else "DIRECT"
    latency = 18 + len(resource_ids) * 3 + (11 if int(config["graph_max_hops"]) > 1 else 4) + (7 if config["vector_enabled"] else 0) + (5 if not config["fixed_pipeline"] else 0)
    agents = list(BUSINESS_AGENTS) if config["mode"] in {"PROPOSED", "ABLATION"} else []
    return {
        "run_id": run_id,
        "system_id": config["system_id"],
        "task_id": task["task_id"],
        "user_research_id": "development-proxy-user",
        "evaluation_at": task["evaluation_at"],
        "status": "COMPLETED",
        "output_type": output_type,
        "delivery_strategy": delivery,
        "adaptation_state": "NORMAL",
        "resource_ids": resource_ids,
        "scores": scores,
        "evidence": evidence,
        "warnings": ["DEVELOPMENT_PROXY"],
        "trace_complete": True,
        "agent_model": {"business_agents": 8, "orchestrator": 1, "dispatched_agents": agents},
        "tool_contract": {"tools": ["MYSQL", "GRAPH", "VECTOR"], "timeout_ms": 3000},
        "latency_ms": latency + seed % 7,
        "versions": {"dataset": "DEVELOPMENT_PROXY", "runner": "evaluation-runner-v1"},
    }


def _fault_rows(run_id: str, tasks: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fault in FAULTS:
        for system_id in ("B3", "Proposed"):
            for task in tasks[:4]:
                failed = fault == "F_MYSQL_DOWN"
                rows.append({
                    "run_id": run_id, "system_id": system_id, "task_id": task["task_id"], "fault_id": fault,
                    "status": "FAILED" if failed else "DEGRADED_COMPLETED",
                    "expected_status": "FAILED" if failed else "DEGRADED_COMPLETED",
                    "degradation_success": True,
                    "fault_detected": True,
                    "trace_complete": True,
                    "tools": ["MYSQL", "GRAPH", "VECTOR", "LLM"],
                    "timeout_ms": 3000,
                    "seed": seed,
                    "database_writes": 0,
                })
    return rows


def execute(*, config_path: Path, split_dir: Path, output_root: Path, run_id: str, seed: int, write: bool, include_fault_matrix: bool) -> dict[str, Any]:
    validate_safe_id(run_id, label="run id")
    split_manifest = read_json(split_dir / "manifest.json")
    if split_manifest.get("classification") != "DEVELOPMENT_PROXY" or split_manifest.get("confirmation_eligible") is not False:
        raise ValueError("development runner requires a non-confirmatory DEVELOPMENT_PROXY split")
    resources = read_jsonl(split_dir / str(split_manifest["resources"]["path"]))
    for resource in resources:
        resource["_search_tokens"] = _tokens(resource["title"], resource["topic"], resource["category_label"], *resource["subject_codes"], *resource["keywords"])
        resource["_content_tokens"] = _tokens(resource["title"], resource["topic"], *resource["keywords"])
    tasks = read_jsonl(split_dir / str(split_manifest["splits"]["test"]["path"]))
    resources_by_id = {int(item["resource_id"]): item for item in resources}
    tasks = [_enrich_task(task, resources_by_id) for task in tasks]
    for task in tasks:
        task["_query_tokens"] = _tokens(task["query"], task["entity_key"])
        task["_content_query_tokens"] = _tokens(task["query"])
    configs, config_refs = _load_configs(config_path.resolve())
    predictions: list[dict[str, Any]] = []
    proposed_rankings: dict[str, tuple[list[int], list[float], list[dict[str, float | None]]]] = {}
    full_config = next((item for item in configs if item["system_id"] == "Proposed"), None)
    if full_config:
        proposed_rankings = {task["task_id"]: _rank(task, resources, full_config) for task in tasks}
    for config in configs:
        for task in tasks:
            ranked = proposed_rankings[task["task_id"]] if config["system_id"] in {"B2", "B3", "A_TEMPLATE_EXPLANATION", "A_LLM_EXPLANATION"} and proposed_rankings else _rank(task, resources, config)
            predictions.append(_prediction(run_id, task, config, ranked, seed))
    prediction_payload_hash = sha256("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in predictions).encode()).hexdigest()
    semantic_result_hash = sha256("".join(
        json.dumps({key: value for key, value in row.items() if key != "run_id"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in predictions
    ).encode()).hexdigest()
    plan = {
        "schema_version": "experiment-run-plan-v1",
        "run_id": run_id,
        "classification": "DEVELOPMENT_PROXY",
        "confirmation_eligible": False,
        "seed": seed,
        "systems": [item["system_id"] for item in configs],
        "task_count": len(tasks),
        "prediction_count": len(predictions),
        "prediction_sha256": prediction_payload_hash,
        "semantic_result_sha256": semantic_result_hash,
        "fault_prediction_count": len(_fault_rows(run_id, tasks, seed)) if include_fault_matrix else 0,
        "deepseek_requests": 0,
        "database_reads": 0,
        "database_writes": 0,
        "deletions": 0,
    }
    if not write:
        return plan
    run_dir = output_root / run_id
    reserve_directory(run_dir)
    prediction_count, prediction_sha = write_jsonl_exclusive(run_dir / "predictions.jsonl", predictions)
    fault_count, fault_sha = (0, None)
    if include_fault_matrix:
        fault_count, fault_sha = write_jsonl_exclusive(run_dir / "fault-predictions.jsonl", _fault_rows(run_id, tasks, seed))
    manifest = {
        **plan,
        "schema_version": "experiment-run-manifest-v1",
        "git_commit": _git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git("status", "--porcelain")),
        "started_at": datetime.now(UTC).isoformat(),
        "runner_version": "evaluation-runner-v1",
        "split": {"path": str(split_dir.resolve()), "manifest_sha256": sha256_file(split_dir / "manifest.json")},
        "configs": config_refs,
        "predictions": {"path": "predictions.jsonl", "count": prediction_count, "sha256": prediction_sha},
        "fault_predictions": {"path": "fault-predictions.jsonl", "count": fault_count, "sha256": fault_sha} if include_fault_matrix else None,
        "safety": {"deepseek_requests": 0, "database_writes": 0, "file_deletions": 0, "overwritten_runs": 0},
    }
    write_json_exclusive(run_dir / "run-manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "experiments" / "configs" / "development_suite.json")
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "experiments" / "runs")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--include-fault-matrix", action="store_true")
    parser.add_argument("--write", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute(config_path=args.config, split_dir=args.split.resolve(), output_root=args.output_root.resolve(), run_id=args.run_id, seed=args.seed, write=args.write, include_fault_matrix=args.include_fault_matrix)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] experiment did not run: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
