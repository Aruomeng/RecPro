"""Build an immutable DEVELOPMENT_PROXY split from the local Lib catalogue.

The proxy labels are derived deterministically from Topic, Category and
SubjectCode metadata.  They are suitable for runner/mechanism verification,
not for confirmatory claims about recommendation accuracy.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

try:
    from scripts.evaluation_runtime import PROJECT_ROOT, canonical_bytes, reserve_directory, sha256_file, validate_safe_id, write_json_exclusive, write_jsonl_exclusive
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from evaluation_runtime import PROJECT_ROOT, canonical_bytes, reserve_directory, sha256_file, validate_safe_id, write_json_exclusive, write_jsonl_exclusive


SUBJECT_CODE = re.compile(r"[A-Z][A-Z0-9]*(?:\.[0-9]+)?")
YEAR = re.compile(r"(?:19|20)[0-9]{2}")


def _parts(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[-;,，；/]+", value or "") if item.strip()]


def _external_id(row: dict[str, str]) -> str:
    isbn = re.sub(r"[^0-9Xx]", "", row.get("ISBN号", "")).upper()
    if isbn:
        return f"isbn:{isbn}"
    raw = "|".join((row.get("题名", "").strip(), row.get("作者", "").strip(), row.get("出版社", "").strip()))
    return "book:" + sha256(raw.encode("utf-8")).hexdigest()[:24]


def read_catalog(catalog_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files = sorted(catalog_root.glob("*/*.csv"), key=lambda item: item.as_posix())
    if not files:
        raise ValueError("catalog root must contain classified CSV files")
    resources_by_external: dict[str, dict[str, Any]] = {}
    source_files: list[dict[str, Any]] = []
    for path in files:
        category_dir = path.parent.name
        category_code, _, category_label = category_dir.partition("-")
        topic = path.stem.strip()
        source_files.append({"path": path, "sha256": sha256_file(path), "bytes": path.stat().st_size})
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"题名", "作者", "主题词", "中图法分类号"}
            if not required.issubset(set(reader.fieldnames or ())):
                raise ValueError(f"catalog file lacks required columns: {path}")
            for row in reader:
                title = (row.get("题名") or "").strip()
                if not title:
                    continue
                external_id = _external_id(row)
                subject_codes = sorted(set(SUBJECT_CODE.findall(row.get("中图法分类号", ""))))[:8]
                year_match = YEAR.search(row.get("发行时间", ""))
                candidate = {
                    "external_id": external_id,
                    "title": title[:240],
                    "authors": _parts(row.get("作者", ""))[:8],
                    "topic": topic[:120],
                    "category_code": category_code[:16],
                    "category_label": category_label[:120],
                    "subject_codes": subject_codes,
                    "keywords": _parts(row.get("主题词", ""))[:16],
                    "publication_year": int(year_match.group()) if year_match else None,
                    "popularity_proxy": round(int(sha256(external_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF, 6),
                }
                previous = resources_by_external.get(external_id)
                if previous is None or canonical_bytes(candidate) < canonical_bytes(previous):
                    resources_by_external[external_id] = candidate
    resources = sorted(resources_by_external.values(), key=lambda item: item["external_id"])
    for index, resource in enumerate(resources, 1):
        resource["resource_id"] = index
    return resources, source_files


def _task_id(kind: str, key: str) -> str:
    return f"proxy-{kind.lower()}-{sha256(f'{kind}:{key}'.encode()).hexdigest()[:16]}"


def build_tasks(resources: list[dict[str, Any]], *, max_subject_tasks: int = 24) -> list[dict[str, Any]]:
    by_topic: dict[str, list[dict[str, Any]]] = {}
    by_category: dict[str, list[dict[str, Any]]] = {}
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for resource in resources:
        by_topic.setdefault(str(resource["topic"]), []).append(resource)
        by_category.setdefault(str(resource["category_code"]), []).append(resource)
        for code in resource["subject_codes"]:
            by_subject.setdefault(str(code), []).append(resource)
    subject_keys = [key for key, rows in sorted(by_subject.items(), key=lambda item: (-len(item[1]), item[0])) if len(rows) >= 5][:max_subject_tasks]
    tasks: list[dict[str, Any]] = []

    def add(kind: str, key: str, label: str, direct: list[dict[str, Any]], related: Iterable[dict[str, Any]], direct_rel: int, related_hops: int) -> None:
        judgments: dict[int, dict[str, int]] = {int(row["resource_id"]): {"relevance": direct_rel, "graph_hops": 1} for row in direct}
        for row in related:
            resource_id = int(row["resource_id"])
            judgments.setdefault(resource_id, {"relevance": 1, "graph_hops": related_hops})
            if len(judgments) >= max(220, len(direct)):
                break
        digest = int(sha256(f"{kind}:{key}".encode()).hexdigest()[:8], 16)
        tasks.append({
            "task_id": _task_id(kind, key),
            "entity_type": kind,
            "entity_key": key,
            "query": label,
            "expected_output_type": "READING_PATH" if digest % 5 == 0 else "TOPIC_RESOURCES",
            "expected_delivery_strategy": "CLARIFY" if digest % 7 == 0 else "DIRECT",
            "evaluation_at": "2026-08-28T00:00:00Z",
            "judgments": [{"resource_id": resource_id, **value} for resource_id, value in sorted(judgments.items())],
        })

    for topic, direct in sorted(by_topic.items()):
        category = str(direct[0]["category_code"])
        related = (row for row in by_category[category] if row["topic"] != topic)
        add("TOPIC", topic, topic, direct, related, 3, 3)
    for category, direct in sorted(by_category.items()):
        label = str(direct[0]["category_label"] or category)
        add("CATEGORY", category, label, direct, (), 2, 1)
    for subject in sorted(subject_keys):
        direct = by_subject[subject]
        categories = {str(row["category_code"]) for row in direct}
        related = (row for row in resources if str(row["category_code"]) in categories and subject not in row["subject_codes"])
        add("SUBJECT_CODE", subject, subject, direct, related, 3, 2)
    return sorted(tasks, key=lambda item: item["task_id"])


def split_tasks(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result = {"train": [], "validation": [], "test": []}
    for task in tasks:
        bucket = int(sha256(task["task_id"].encode()).hexdigest()[:8], 16) % 10
        result["train" if bucket < 6 else "validation" if bucket < 8 else "test"].append(task)
    if any(not rows for rows in result.values()):
        raise ValueError("deterministic split unexpectedly produced an empty partition")
    return result


def build_plan(catalog_root: Path, output: Path, dataset_version: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    resources, source_files = read_catalog(catalog_root)
    tasks = build_tasks(resources)
    partitions = split_tasks(tasks)
    plan = {
        "schema_version": "development-proxy-plan-v1",
        "classification": "DEVELOPMENT_PROXY",
        "confirmation_eligible": False,
        "dataset_version": validate_safe_id(dataset_version, label="dataset version"),
        "catalog_root": str(catalog_root),
        "output": str(output),
        "counts": {"resources": len(resources), "tasks": len(tasks), **{name: len(rows) for name, rows in partitions.items()}},
        "source_files": [{"path": str(item["path"]), "sha256": item["sha256"], "bytes": item["bytes"]} for item in source_files],
        "label_basis": ["Topic", "Category", "SubjectCode"],
        "deepseek_requests": 0,
        "database_reads": 0,
        "database_writes": 0,
        "deletions": 0,
    }
    return plan, resources, partitions


def execute(catalog_root: Path, output: Path, dataset_version: str, *, write: bool) -> dict[str, Any]:
    plan, resources, partitions = build_plan(catalog_root.resolve(), output.resolve(), dataset_version)
    if not write:
        return plan
    reserve_directory(output)
    resources_count, resources_sha = write_jsonl_exclusive(output / "resources.jsonl", resources)
    split_files: dict[str, Any] = {}
    for name, rows in partitions.items():
        count, digest = write_jsonl_exclusive(output / f"{name}.jsonl", rows)
        split_files[name] = {"path": f"{name}.jsonl", "count": count, "sha256": digest}
    manifest = {
        **plan,
        "catalog_root": str(catalog_root.resolve()),
        "output": ".",
        "resources": {"path": "resources.jsonl", "count": resources_count, "sha256": resources_sha},
        "splits": split_files,
        "frozen": True,
    }
    write_json_exclusive(output / "manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-root", type=Path, default=PROJECT_ROOT / "Lib")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-version", default="lib-development-proxy-20260828-v1")
    parser.add_argument("--write", action="store_true", help="create the new immutable output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute(args.catalog_root, args.output, args.dataset_version, write=args.write)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        print(f"[FAIL] evaluation split was not prepared: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
