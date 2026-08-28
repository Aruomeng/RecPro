#!/usr/bin/env python3
"""Build or dry-run the additive Work/Instance library graph v2 artifacts.

The default mode reads only the immutable v1 JSONL artifacts and prints an
exact report.  ``--write`` creates a new output directory and refuses to use
an existing target.  It never connects to Neo4j or modifies v1 artifacts.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
from typing import Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_VERSION = "lib-books-v1-20260810"
V2_PATTERN = re.compile(r"^lib-books-v2-[0-9]{8}$")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name} line {line_number} is not an object")
        rows.append(value)
    return rows


@dataclass(frozen=True, slots=True)
class WorkGroup:
    work_id: str
    title: str
    normalized_title: str
    book_keys: tuple[str, ...]
    author_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class V2Analysis:
    source_nodes: int
    source_triples: int
    source_books: int
    works: tuple[WorkGroup, ...]
    proposals: tuple[dict[str, object], ...]

    @property
    def target_nodes(self) -> int:
        return self.source_nodes + len(self.works)

    @property
    def target_triples(self) -> int:
        return self.source_triples + self.source_books


def analyze(nodes: Iterable[Mapping[str, object]], triples: Iterable[Mapping[str, object]]) -> V2Analysis:
    node_rows = list(nodes)
    triple_rows = list(triples)
    books: dict[str, Mapping[str, object]] = {
        str(row["graph_key"]): row for row in node_rows if row.get("label") == "Book"
    }
    authors: dict[str, set[str]] = defaultdict(set)
    for triple in triple_rows:
        if triple.get("predicate") == "AUTHORED_BY" and str(triple.get("subject_key")) in books:
            authors[str(triple["subject_key"])].add(str(triple["object_key"]))

    by_title: dict[str, list[str]] = defaultdict(list)
    proposals: list[dict[str, object]] = []
    for book_key, row in books.items():
        properties = row.get("properties")
        title = str(properties.get("title", "")) if isinstance(properties, Mapping) else ""
        normalized = normalize_title(title)
        if not normalized:
            normalized = sha256(book_key.encode()).hexdigest()
            proposals.append(_proposal("MISSING_NORMALIZED_TITLE", (book_key,), 0.0))
        by_title[normalized].append(book_key)

    groups: list[WorkGroup] = []
    for normalized_title, title_books in sorted(by_title.items()):
        # Union only books sharing at least one author. Missing-author records
        # become singleton Works and are sent to governance review.
        parent = {book_key: book_key for book_key in title_books}

        def find(value: str) -> str:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        by_author: dict[str, list[str]] = defaultdict(list)
        for book_key in title_books:
            if not authors[book_key]:
                proposals.append(_proposal("MISSING_AUTHOR_FOR_WORK_MERGE", (book_key,), 0.50))
            for author_key in authors[book_key]:
                by_author[author_key].append(book_key)
        for author_books in by_author.values():
            for book_key in author_books[1:]:
                union(author_books[0], book_key)
        components: dict[str, list[str]] = defaultdict(list)
        for book_key in title_books:
            components[find(book_key)].append(book_key)
        for component in sorted(components.values(), key=lambda item: tuple(sorted(item))):
            ordered_books = tuple(sorted(component))
            work_authors = tuple(sorted(set().union(*(authors[key] for key in ordered_books))))
            first_properties = books[ordered_books[0]].get("properties")
            title = str(first_properties.get("title", "")) if isinstance(first_properties, Mapping) else ""
            digest = sha256(
                canonical([normalized_title, ordered_books, work_authors]).encode()
            ).hexdigest()[:32]
            groups.append(WorkGroup(f"work:{digest}", title, normalized_title, ordered_books, work_authors))
            if len(ordered_books) > 1:
                _append_conflict_proposals(proposals, ordered_books, books)

    return V2Analysis(
        source_nodes=len(node_rows),
        source_triples=len(triple_rows),
        source_books=len(books),
        works=tuple(groups),
        proposals=tuple(proposals),
    )


def _append_conflict_proposals(
    proposals: list[dict[str, object]],
    book_keys: tuple[str, ...],
    books: Mapping[str, Mapping[str, object]],
) -> None:
    for field in ("isbn", "publisher"):
        values = set()
        for key in book_keys:
            properties = books[key].get("properties")
            if isinstance(properties, Mapping) and properties.get(field):
                values.add(str(properties[field]).strip())
        if len(values) > 1:
            proposals.append(_proposal(f"WORK_{field.upper()}_CONFLICT", book_keys, 0.60))


def _proposal(reason_code: str, book_keys: tuple[str, ...], confidence: float) -> dict[str, object]:
    digest = sha256(canonical([reason_code, sorted(book_keys)]).encode()).hexdigest()
    return {
        "proposal_key": f"review:{digest[:32]}",
        "proposal_type": "WORK_IDENTITY_REVIEW",
        "reason_code": reason_code,
        "book_keys": list(sorted(book_keys))[:20],
        "confidence": confidence,
        "idempotency_sha256": digest,
    }


def dry_run_report(analysis: V2Analysis, *, target_version: str) -> dict[str, object]:
    reason_counts = Counter(str(item["reason_code"]) for item in analysis.proposals)
    return {
        "schema_version": "book-graph-v2-dry-run-v1",
        "source_graph_version": V1_VERSION,
        "target_graph_version": target_version,
        "source": {
            "nodes": analysis.source_nodes,
            "triples": analysis.source_triples,
            "books": analysis.source_books,
        },
        "target": {
            "nodes": analysis.target_nodes,
            "triples": analysis.target_triples,
            "works": len(analysis.works),
            "instance_of": analysis.source_books,
            "items": 0,
        },
        "review_proposals": {
            "total": len(analysis.proposals),
            "by_reason": dict(sorted(reason_counts.items())),
            "persisted_rows": 0,
        },
        "safety": {
            "database_connections": 0,
            "neo4j_reads": 0,
            "neo4j_writes": 0,
            "deepseek_requests": 0,
            "source_artifacts_modified": 0,
            "files_deleted": 0,
        },
    }


def rewrite_key(value: str, target_version: str) -> str:
    prefix = V1_VERSION + ":"
    return target_version + ":" + value[len(prefix):] if value.startswith(prefix) else value


def build_rows(
    nodes: list[dict[str, object]],
    triples: list[dict[str, object]],
    analysis: V2Analysis,
    *,
    target_version: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    target_nodes: list[dict[str, object]] = []
    for row in nodes:
        copied = dict(row)
        copied["graph_version"] = target_version
        copied["graph_key"] = rewrite_key(str(row["graph_key"]), target_version)
        properties = dict(row.get("properties", {}))
        properties = {
            key: target_version if value == V1_VERSION else value
            for key, value in properties.items()
        }
        copied["properties"] = properties
        target_nodes.append(copied)
    work_key_by_book: dict[str, str] = {}
    for work in analysis.works:
        work_key = f"{target_version}:work:{work.work_id.split(':', 1)[1]}"
        target_nodes.append({
            "entity_id": work.work_id,
            "graph_key": work_key,
            "graph_version": target_version,
            "label": "Work",
            "properties": {
                "title": work.title,
                "normalized_title": work.normalized_title,
                "instance_count": len(work.book_keys),
                "identity_rule": "normalized-title-shared-author-v1",
            },
        })
        for book_key in work.book_keys:
            work_key_by_book[book_key] = work_key
    target_triples: list[dict[str, object]] = []
    for row in triples:
        copied = dict(row)
        copied["subject_key"] = rewrite_key(str(row["subject_key"]), target_version)
        copied["object_key"] = rewrite_key(str(row["object_key"]), target_version)
        copied["edge_key"] = "edge:" + sha256(
            f"{target_version}:{row['edge_key']}".encode()
        ).hexdigest()[:32]
        target_triples.append(copied)
    for book_key, work_key in sorted(work_key_by_book.items()):
        subject_key = rewrite_key(book_key, target_version)
        target_triples.append({
            "edge_key": "edge:" + sha256(
                f"{target_version}:{subject_key}:INSTANCE_OF:{work_key}".encode()
            ).hexdigest()[:32],
            "subject_key": subject_key,
            "predicate": "INSTANCE_OF",
            "object_key": work_key,
            "properties": {"identity_rule": "normalized-title-shared-author-v1"},
        })
    return target_nodes, target_triples


def write_artifacts(
    output_dir: Path,
    *,
    nodes: list[dict[str, object]],
    triples: list[dict[str, object]],
    analysis: V2Analysis,
    target_version: str,
) -> None:
    if output_dir.exists():
        raise FileExistsError("v2 output directory already exists; refusing to overwrite")
    output_dir.mkdir(parents=True)
    target_nodes, target_triples = build_rows(
        nodes, triples, analysis, target_version=target_version,
    )
    nodes_bytes = ("\n".join(canonical(row) for row in target_nodes) + "\n").encode()
    triples_bytes = ("\n".join(canonical(row) for row in target_triples) + "\n").encode()
    (output_dir / "nodes.jsonl").write_bytes(nodes_bytes)
    (output_dir / "triples.jsonl").write_bytes(triples_bytes)
    node_counts = Counter(str(row["label"]) for row in target_nodes)
    relationship_counts = Counter(str(row["predicate"]) for row in target_triples)
    plan = dry_run_report(analysis, target_version=target_version) | {
        "schema_version": "book-graph-plan-v2",
        "graph_version": target_version,
        "source_graph_version": V1_VERSION,
        "can_import": True,
        "license_status": "CONFIRMED_LOCAL_RESEARCH",
        "nodes": {
            "total": len(target_nodes),
            "by_label": dict(sorted(node_counts.items())),
        },
        "triples": {
            "total": len(target_triples),
            "by_predicate": dict(sorted(relationship_counts.items())),
        },
        "artifacts": {
            "nodes_sha256": sha256(nodes_bytes).hexdigest(),
            "triples_sha256": sha256(triples_bytes).hexdigest(),
        },
    }
    (output_dir / "graph-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    reviews = "\n".join(canonical(row) for row in analysis.proposals)
    (output_dir / "review-proposals.jsonl").write_text(
        reviews + ("\n" if reviews else ""), encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts/verification/book-graph/lib-graph-plan-20260810-003",
    )
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if V2_PATTERN.fullmatch(args.target_version) is None:
        raise ValueError("target version must match lib-books-v2-YYYYMMDD")
    nodes = load_jsonl(args.source_dir / "nodes.jsonl")
    triples = load_jsonl(args.source_dir / "triples.jsonl")
    analysis = analyze(nodes, triples)
    report = dry_run_report(analysis, target_version=args.target_version)
    if args.write:
        if args.output_dir is None:
            raise ValueError("--write requires --output-dir")
        write_artifacts(
            args.output_dir,
            nodes=nodes,
            triples=triples,
            analysis=analysis,
            target_version=args.target_version,
        )
        report["output_dir"] = str(args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
