#!/usr/bin/env python3
"""Build a zero-write DRY_RUN plan for the six browser research scenarios."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "verification" / "g8-browser-scenario-plan.schema.json"
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
SCENARIO_IDS = (
    "cold_user_guided", "clear_user_recommendation", "topic_user_explanation",
    "reading_path_clarification", "negative_feedback_adjustment", "degraded_dependency_path",
)
FIXTURE_USERS = ("demo_cold", "demo_clear", "demo_topic", "demo_path", "demo_negative", "demo_degraded")
GRAPH_VERSION = "lib-books-v1-20260810"
EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def resolve_inside_project(path: Path, *, label: str, strict: bool = True) -> Path:
    resolved = (path if path.is_absolute() else PROJECT_ROOT / path).resolve(strict=strict)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def current_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
    value = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("current Git HEAD is not a full commit")
    return value


def require_clean_worktree() -> None:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
    if result.stdout.strip():
        raise ValueError("working tree must be clean before freezing a browser plan")


def load_baseline(path: Path) -> tuple[dict[str, Any], bytes, Path]:
    resolved = resolve_inside_project(path, label="browser baseline")
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "PASS":
        raise ValueError("browser baseline must be a PASS JSON object")
    mysql = payload.get("mysql")
    counts = mysql.get("counts_after") if isinstance(mysql, dict) else None
    if not isinstance(counts, dict) or not counts:
        raise ValueError("browser baseline must contain mysql.counts_after")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values()):
        raise ValueError("browser baseline counts must be non-negative integers")
    return payload, raw, resolved


def _request(run_id: str, name: str, input_text: str, resource_types: list[str], output_type: str, limit: int) -> dict[str, Any]:
    return {
        "request_id": str(uuid5(NAMESPACE_URL, f"g8-browser:{run_id}:{name}:request")),
        "session_id": str(uuid5(NAMESPACE_URL, f"g8-browser:{run_id}:{name}:session")),
        "scene": "SEARCH_AFTER",
        "input_text": input_text,
        "requested_resource_types": resource_types,
        "requested_output_type": output_type,
        "limit": limit,
    }


def _scenario(run_id: str, scenario_id: str, fixture_user: str, request: dict[str, Any], status: str, output_type: str, delivery: str, minimum_items: int, required_texts: list[str], actions: list[str], max_db: int, max_llm: int, max_network: int) -> dict[str, Any]:
    acceptable_statuses = (
        ["COMPLETED", "DEGRADED_COMPLETED"]
        if status == "COMPLETED"
        else [status]
    )
    return {
        "scenario_id": scenario_id,
        "fixture_user": fixture_user,
        "request": request,
        "expected": {
            "status": status,
            "acceptable_statuses": acceptable_statuses,
            "output_type": output_type,
            "delivery_strategy": delivery,
            "minimum_items": minimum_items,
            "required_texts": required_texts,
        },
        "browser": {
            "viewport": {"width": 1280, "height": 720},
            "required_selectors": [
                "[aria-label='当前阶段说明']",
                "[aria-labelledby='recommendation-title']",
                "button[name='请求真实推荐']",
                "[aria-labelledby='interaction-title']",
            ],
            "assertions": [
                "live and readiness status are visible",
                "request controls are keyboard reachable",
                "the result status and evidence references are visible",
                "no horizontal overflow is present at the selected viewport",
            ],
        },
        "actions": actions,
        "budget": {
            "max_database_writes": max_db,
            "max_external_llm_requests": max_llm,
            "max_network_requests": max_network,
            "max_outbox_claims": 0,
            "replay_zero_delta": True,
        },
    }


def build_plan(*, run_id: str, baseline_path: Path, compose_project: str, mysql_database: str = "recpro", frontend_origin: str = "http://127.0.0.1:5173/", backend_origin: str = "http://127.0.0.1:8000/") -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use lowercase letters, digits, and hyphens")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", compose_project):
        raise ValueError("compose project must be lowercase and safe")
    baseline, baseline_raw, resolved_baseline = load_baseline(baseline_path)
    require_clean_worktree()
    commit = current_commit()
    counts = {str(key): int(value) for key, value in baseline["mysql"]["counts_after"].items()}
    scenarios = [
        _scenario(run_id, "cold_user_guided", "demo_cold", _request(run_id, "cold", "我还不确定要研究什么，先帮我梳理方向", ["BOOK", "PAPER"], "PERSONALIZED_FEED", 6), "WAITING_CLARIFICATION", "PERSONALIZED_FEED", "GUIDED", 0, ["请补充", "澄清"], ["readiness_get", "recommendation_post"], 20, 0, 4),
        _scenario(run_id, "clear_user_recommendation", "demo_clear", _request(run_id, "clear", "请推荐多智能体系统与智慧图书馆相关图书", ["BOOK"], "PERSONALIZED_FEED", 8), "COMPLETED", "PERSONALIZED_FEED", "DIRECT", 6, ["协作链返回的资源", "证据"], ["readiness_get", "recommendation_post", "recommendation_replay"], 56, 16, 6),
        _scenario(run_id, "topic_user_explanation", "demo_topic", _request(run_id, "topic", "围绕多智能体、知识图谱和智慧图书馆解释推荐理由", ["BOOK", "PAPER"], "TOPIC_RESOURCES", 8), "COMPLETED", "TOPIC_RESOURCES", "DIRECT", 6, ["结果与证据", "召回"], ["readiness_get", "recommendation_post", "recommendation_replay"], 56, 16, 6),
        # The browser request does not declare an insufficient difficulty-level
        # coverage constraint.  The live policy therefore treats this as a
        # normal reading-path output; degradation is exercised independently by
        # the explicit dependency-fault scenario below.
        _scenario(run_id, "reading_path_clarification", "demo_path", _request(run_id, "path", "请给我一条从推荐系统基础到多智能体智慧图书馆的学习路径", ["BOOK", "PAPER"], "READING_PATH", 8), "COMPLETED", "READING_PATH", "DIRECT", 6, ["结果与证据", "学习路径"], ["readiness_get", "recommendation_post", "recommendation_replay"], 56, 16, 6),
        _scenario(run_id, "negative_feedback_adjustment", "demo_negative", _request(run_id, "negative", "我不想看传统编目主题，请重新推荐多智能体和知识图谱资料", ["BOOK"], "TOPIC_RESOURCES", 8), "COMPLETED", "TOPIC_RESOURCES", "DIRECT", 6, ["反馈", "调整"], ["readiness_get", "recommendation_post", "record_impression", "record_feedback", "record_behavior", "recommendation_replay"], 62, 16, 10),
        _scenario(run_id, "degraded_dependency_path", "demo_degraded", _request(run_id, "degraded", "请推荐一个非常小众且馆藏不足的主题", ["BOOK"], "TOPIC_RESOURCES", 8), "DEGRADED_COMPLETED", "TOPIC_RESOURCES", "DEGRADED", 0, ["DEGRADED", "缺口"], ["readiness_get", "dependency_fault", "recommendation_post", "recommendation_replay"], 56, 16, 8),
    ]
    max_db = sum(int(item["budget"]["max_database_writes"]) for item in scenarios)
    max_llm = sum(int(item["budget"]["max_external_llm_requests"]) for item in scenarios)
    max_network = sum(int(item["budget"]["max_network_requests"]) for item in scenarios)
    plan: dict[str, Any] = {
        "schema_version": "g8-browser-scenario-plan-v1",
        "plan_id": str(uuid5(NAMESPACE_URL, f"g8-browser-plan:{run_id}")),
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S3_BROWSER_SCENARIO",
        "mode": "DRY_RUN",
        "environment": {
            "compose_project": compose_project,
            "mysql_database": mysql_database,
            "frontend_origin": frontend_origin,
            "backend_origin": backend_origin,
            "graph_version": GRAPH_VERSION,
            "embedding_version": EMBEDDING_VERSION,
            "index_version": INDEX_VERSION,
            "llm_provider": "deepseek",
            "llm_model": "deepseek-v4-flash",
        },
        "baseline": {
            "path": resolved_baseline.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": hashlib.sha256(baseline_raw).hexdigest(),
            "counts_sha256": sha256_bytes(canonical(dict(sorted(counts.items())))),
            "compose_project": compose_project,
            "counts": counts,
        },
        "scenario_ids": list(SCENARIO_IDS),
        "scenarios": scenarios,
        "aggregate_budget": {
            "max_database_writes": max_db,
            "max_external_llm_requests": max_llm,
            "max_network_requests": max_network,
            "max_outbox_claims": 0,
            "max_files_deleted": 0,
            "max_database_physical_deletions": 0,
            "max_artifact_overwrites": 0,
        },
        "safety_assertions": {
            "business_writes_authorized": False,
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "artifact_overwrites": 0,
            "outbox_claims": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "external_llm_requests": 0,
        },
        "executor_status": "READY_FOR_EXPLICIT_APPROVAL",
    }
    plan["plan_hash"] = sha256_bytes(canonical(plan))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan), key=lambda error: tuple(error.absolute_path))
    if errors:
        raise ValueError("browser scenario plan violates schema: " + "; ".join(error.message for error in errors))
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--mysql-database", default="recpro")
    parser.add_argument("--frontend-origin", default="http://127.0.0.1:5173/")
    parser.add_argument("--backend-origin", default="http://127.0.0.1:8000/")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_plan(run_id=args.run_id, baseline_path=args.baseline, compose_project=args.compose_project, mysql_database=args.mysql_database, frontend_origin=args.frontend_origin, backend_origin=args.backend_origin)
        output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / args.run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        output = output_dir / "browser-scenario-plan.json"
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "PASS", "run_id": args.run_id, "plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "path": output.relative_to(PROJECT_ROOT).as_posix(), "scenario_count": len(plan["scenarios"]), "max_database_writes": plan["aggregate_budget"]["max_database_writes"], "max_external_llm_requests": plan["aggregate_budget"]["max_external_llm_requests"], "database_writes": 0, "external_llm_requests": 0, "files_deleted": 0, "database_physical_deletions": 0}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
