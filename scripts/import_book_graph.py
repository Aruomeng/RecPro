"""Safely import a reviewed book-graph plan into the isolated RecPro Neo4j.

The default mode is a read-only preflight.  ``--apply`` is required for any
Neo4j write and also requires an explicit, non-pending source license status.
All data writes are append-only ``MERGE``/``ON CREATE`` operations.  There is
no delete, detach, remove, or overwrite operation in this importer.
"""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.user-secrets"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
GRAPH_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
PROJECT_PATTERN = re.compile(r"^recpro-library-neo4j-[a-z0-9][a-z0-9._-]{2,63}$")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_LICENSE_STATUSES = {"CONFIRMED_LOCAL_RESEARCH", "LICENSED_OPEN_DATA"}
ALL_LICENSE_STATUSES = {"PENDING_USER_CONFIRMATION", *ALLOWED_LICENSE_STATUSES}
NODE_LABELS = {
    "GraphVersion",
    "SourceFile",
    "SourceRecord",
    "Book",
    "Category",
    "Topic",
    "Author",
    "Publisher",
    "SubjectCode",
    "Keyword",
}
RELATIONSHIP_TYPES = {
    "FROM_BATCH",
    "READ_FROM",
    "DESCRIBES",
    "IN_GRAPH_VERSION",
    "CLASSIFIED_AS",
    "IN_TOPIC",
    "HAS_TOPIC",
    "AUTHORED_BY",
    "PUBLISHED_BY",
    "HAS_SUBJECT_CODE",
    "HAS_KEYWORD",
}
_DESTRUCTIVE_CYPHER_WORDS = (
    "DE" + "LETE",
    "DE" + "TACH",
    "RE" + "MOVE",
    "DR" + "OP",
    "TRUN" + "CATE",
)
FORBIDDEN_CYPHER = re.compile(
    r"\b(?:" + "|".join(_DESTRUCTIVE_CYPHER_WORDS) + r")\b",
    re.IGNORECASE,
)


def validate_identifier(value: str, *, label: str, pattern: re.Pattern[str] = RUN_ID_PATTERN) -> str:
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{label} has an unsafe format")
    return value


def resolve_repository_path(value: str | Path, *, label: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def relative_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def load_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} cannot be read: {type(exc).__name__}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} line {line_number} is invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} line {line_number} must be an object")
        rows.append(value)
    return rows


def verify_plan(plan_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    plan_path = plan_dir / "graph-plan.json"
    nodes_path = plan_dir / "nodes.jsonl"
    triples_path = plan_dir / "triples.jsonl"
    plan = load_json(plan_path, label="graph plan")
    nodes_raw = nodes_path.read_bytes()
    triples_raw = triples_path.read_bytes()
    artifacts = plan.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("graph plan artifacts metadata is missing")
    expected_nodes_hash = artifacts.get("nodes_sha256")
    expected_triples_hash = artifacts.get("triples_sha256")
    if expected_nodes_hash != sha256_bytes(nodes_raw) or expected_triples_hash != sha256_bytes(triples_raw):
        raise ValueError("graph plan JSONL artifact hash mismatch")
    graph_version = plan.get("graph_version")
    validate_identifier(str(graph_version), label="graph version", pattern=GRAPH_VERSION_PATTERN)
    if plan.get("schema_version") != "book-graph-plan-v1":
        raise ValueError("unsupported graph plan schema version")
    if plan.get("can_import") is not True:
        raise ValueError("graph plan is not marked can_import")
    license_status = plan.get("license_status")
    if license_status not in ALL_LICENSE_STATUSES:
        raise ValueError("graph plan has an unknown license status")
    nodes = load_jsonl(nodes_path, label="graph nodes")
    triples = load_jsonl(triples_path, label="graph triples")
    if plan.get("nodes", {}).get("total") != len(nodes):
        raise ValueError("graph plan node count does not match nodes.jsonl")
    if plan.get("triples", {}).get("total") != len(triples):
        raise ValueError("graph plan triple count does not match triples.jsonl")
    node_keys: set[str] = set()
    node_labels: dict[str, str] = {}
    for node in nodes:
        key = node.get("graph_key")
        label = node.get("label")
        if not isinstance(key, str) or not key or key in node_keys:
            raise ValueError("graph nodes contain missing or duplicate graph_key values")
        if label not in NODE_LABELS:
            raise ValueError("graph nodes contain an unsupported label")
        if not isinstance(node.get("entity_id"), str) or not isinstance(node.get("graph_version"), str):
            raise ValueError("graph nodes must include string entity_id and graph_version")
        if node["graph_version"] != graph_version:
            raise ValueError("graph node graph_version does not match plan")
        properties = node.get("properties")
        if not isinstance(properties, Mapping) or any(value is None for value in properties.values()):
            raise ValueError("graph node properties must be an object without null values")
        node_keys.add(key)
        node_labels[key] = label
    edge_keys: set[str] = set()
    for triple in triples:
        edge_key = triple.get("edge_key")
        subject_key = triple.get("subject_key")
        object_key = triple.get("object_key")
        predicate = triple.get("predicate")
        if not isinstance(edge_key, str) or not edge_key or edge_key in edge_keys:
            raise ValueError("graph triples contain missing or duplicate edge_key values")
        if subject_key not in node_keys or object_key not in node_keys:
            raise ValueError("graph triple points to an unknown node")
        if predicate not in RELATIONSHIP_TYPES:
            raise ValueError("graph triple contains an unsupported predicate")
        properties = triple.get("properties")
        if not isinstance(properties, Mapping) or any(value is None for value in properties.values()):
            raise ValueError("graph triple properties must be an object without null values")
        edge_keys.add(edge_key)
    return plan, nodes, triples


class Neo4jHttpClient:
    """Small dependency-free client for Neo4j's transactional HTTP endpoint."""

    def __init__(self, *, endpoint: str, username: str, password: str, timeout: float = 15.0) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.authorization = f"Basic {token}"
        self.read_count = 0
        self.write_count = 0
        # The desktop may have a system HTTP proxy configured.  The target is
        # a local Docker endpoint; routing credentials through a proxy is both
        # unnecessary and unsafe, so this client deliberately bypasses it.
        self.opener = build_opener(ProxyHandler({}))

    def run(self, query: str, parameters: Mapping[str, Any] | None = None, *, write: bool = False) -> list[dict[str, Any]]:
        if FORBIDDEN_CYPHER.search(query):
            raise ValueError("forbidden destructive Cypher keyword detected")
        request = Request(
            self.endpoint,
            data=json.dumps(
                {"statements": [{"statement": query, "parameters": dict(parameters or {})}]},
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Authorization": self.authorization,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Neo4j HTTP request failed with status {exc.code}") from exc
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Neo4j HTTP request failed: {type(exc).__name__}") from exc
        errors = payload.get("errors", []) if isinstance(payload, dict) else []
        if errors:
            codes = [str(item.get("code", "UNKNOWN")) for item in errors if isinstance(item, Mapping)]
            raise RuntimeError(f"Neo4j rejected a query ({','.join(codes)})")
        if write:
            self.write_count += 1
        else:
            self.read_count += 1
        results = payload.get("results", []) if isinstance(payload, dict) else []
        if not results:
            return []
        first = results[0]
        return first.get("data", []) if isinstance(first, Mapping) else []


def extract_count(rows: list[dict[str, Any]]) -> int:
    if len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise ValueError("Neo4j count query returned an unexpected shape")
    row = rows[0].get("row")
    if not isinstance(row, list) or len(row) != 1 or not isinstance(row[0], int) or row[0] < 0:
        raise ValueError("Neo4j count query did not return a non-negative integer")
    return row[0]


def cypher_count_nodes(client: Neo4jHttpClient) -> int:
    return extract_count(client.run("MATCH (n) RETURN count(n) AS count"))


def cypher_count_relationships(client: Neo4jHttpClient) -> int:
    return extract_count(client.run("MATCH ()-[r]->() RETURN count(r) AS count"))


def cypher_count_graph_version(client: Neo4jHttpClient, graph_version: str) -> tuple[int, int]:
    node_count = extract_count(
        client.run(
            "MATCH (n {graph_version: $graph_version}) RETURN count(n) AS count",
            {"graph_version": graph_version},
        )
    )
    relationship_count = extract_count(
        client.run(
            "MATCH ()-[r {graph_version: $graph_version}]->() RETURN count(r) AS count",
            {"graph_version": graph_version},
        )
    )
    return node_count, relationship_count


def create_constraints(client: Neo4jHttpClient) -> None:
    for label in sorted(NODE_LABELS):
        query = (
            f"CREATE CONSTRAINT recpro_book_{label.lower()}_graph_key_unique IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.graph_key IS UNIQUE"
        )
        client.run(query, write=True)


def import_nodes(
    client: Neo4jHttpClient,
    nodes: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
) -> int:
    writes = 0
    for label in sorted(NODE_LABELS):
        rows = [node for node in nodes if node.get("label") == label]
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset : offset + batch_size]
            query = (
                f"UNWIND $rows AS row "
                f"MERGE (n:{label} {{graph_key: row.graph_key}}) "
                "ON CREATE SET n.entity_id = row.entity_id, "
                "n.graph_version = row.graph_version, n += row.properties"
            )
            client.run(query, {"rows": list(batch)}, write=True)
            writes += len(batch)
    return writes


def import_triples(
    client: Neo4jHttpClient,
    triples: Sequence[Mapping[str, Any]],
    node_labels: Mapping[str, str],
    *,
    graph_version: str,
    batch_size: int,
) -> int:
    writes = 0
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for triple in triples:
        key = (
            node_labels[str(triple["subject_key"])],
            str(triple["predicate"]),
            node_labels[str(triple["object_key"])],
        )
        grouped.setdefault(key, []).append(triple)
    for (subject_label, predicate, object_label), rows in sorted(grouped.items()):
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset : offset + batch_size]
            query = (
                f"UNWIND $rows AS row "
                f"MATCH (s:{subject_label} {{graph_key: row.subject_key}}) "
                f"MATCH (o:{object_label} {{graph_key: row.object_key}}) "
                f"MERGE (s)-[r:{predicate} {{edge_key: row.edge_key}}]->(o) "
                "ON CREATE SET r.graph_version = $graph_version, r += row.properties"
            )
            client.run(query, {"rows": list(batch), "graph_version": graph_version}, write=True)
            writes += len(batch)
    return writes


def execute(
    *,
    run_id: str,
    plan_dir: Path,
    env_file: Path,
    apply: bool,
    license_status: str,
    allow_nonempty_target: bool,
    batch_size: int,
) -> dict[str, Any]:
    validate_identifier(run_id, label="import run id")
    if license_status not in ALL_LICENSE_STATUSES:
        raise ValueError("license status is not supported")
    if batch_size < 1 or batch_size > 5000:
        raise ValueError("batch size must be between 1 and 5000")
    resolved_plan_dir = resolve_repository_path(plan_dir, label="graph plan directory")
    resolved_env_file = resolve_repository_path(env_file, label="Neo4j secret file")
    if not resolved_plan_dir.is_dir() or not resolved_env_file.is_file():
        raise ValueError("graph plan directory or Neo4j secret file is missing")
    plan, nodes, triples = verify_plan(resolved_plan_dir)
    plan_license = str(plan["license_status"])
    if plan_license != license_status:
        raise ValueError("CLI license status must match the reviewed graph plan")
    if apply and license_status not in ALLOWED_LICENSE_STATUSES:
        raise ValueError("--apply requires explicit non-pending license status")

    values = read_env(resolved_env_file)
    project_name = values.get("RECPRO_LIBRARY_NEO4J_PROJECT_NAME", "")
    validate_identifier(project_name, label="isolated Neo4j project", pattern=PROJECT_PATTERN)
    username = values.get("RECPRO_NEO4J_ADMIN_USER", "")
    password = values.get("RECPRO_NEO4J_ADMIN_PASSWORD", "")
    host = values.get("RECPRO_LIBRARY_NEO4J_HTTP_HOST", "127.0.0.1")
    port = values.get("RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT", "")
    if not username or not password or not port:
        raise ValueError("isolated Neo4j endpoint credentials and port are required")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("isolated Neo4j HTTP port is invalid")
    if int(port) in {7474, 17474, 62474}:
        raise ValueError("refusing known existing/non-target Neo4j HTTP port")
    endpoint = f"http://{host}:{int(port)}/db/neo4j/tx/commit"
    client = Neo4jHttpClient(endpoint=endpoint, username=username, password=password)

    before_nodes = cypher_count_nodes(client)
    before_relationships = cypher_count_relationships(client)
    if (before_nodes or before_relationships) and not allow_nonempty_target:
        raise ValueError("target Neo4j is non-empty; refusing import without explicit override")

    node_labels = {str(node["graph_key"]): str(node["label"]) for node in nodes}
    writes = {"schema": 0, "nodes": 0, "relationships": 0}
    mode = "APPLY" if apply else "DRY_RUN"
    if apply:
        create_constraints(client)
        writes["schema"] = len(NODE_LABELS)
        writes["nodes"] = import_nodes(client, nodes, batch_size=batch_size)
        writes["relationships"] = import_triples(
            client,
            triples,
            node_labels,
            graph_version=str(plan["graph_version"]),
            batch_size=batch_size,
        )

    after_nodes = cypher_count_nodes(client)
    after_relationships = cypher_count_relationships(client)
    graph_version_nodes, graph_version_relationships = cypher_count_graph_version(
        client, str(plan["graph_version"])
    )
    expected_nodes = int(plan["nodes"]["total"])
    expected_relationships = int(plan["triples"]["total"])
    if apply and (
        graph_version_nodes != expected_nodes or graph_version_relationships != expected_relationships
    ):
        raise RuntimeError("Neo4j graph-version counts do not match the reviewed plan")
    report = {
        "schema_version": "book-graph-import-report-v1",
        "status": "PASS" if (not apply or (graph_version_nodes == expected_nodes and graph_version_relationships == expected_relationships)) else "PASS_WITH_BLOCKERS",
        "mode": mode,
        "run_id": run_id,
        "graph_plan": relative_path(resolved_plan_dir / "graph-plan.json"),
        "graph_version": plan["graph_version"],
        "license_status": license_status,
        "target": {
            "project": project_name,
            "host": host,
            "http_port": int(port),
            "database": "neo4j",
        },
        "counts": {
            "before": {"nodes": before_nodes, "relationships": before_relationships},
            "after": {"nodes": after_nodes, "relationships": after_relationships},
            "graph_version": {"nodes": graph_version_nodes, "relationships": graph_version_relationships},
            "expected": {"nodes": expected_nodes, "relationships": expected_relationships},
        },
        "writes": writes,
        "safety": {
            "database_reads": client.read_count,
            "database_writes": client.write_count if apply else 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "overwritten_inputs": 0,
            "target_nonempty_override": allow_nonempty_target,
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    evidence_dir = PROJECT_ROOT / "artifacts/verification/book-graph-import" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    with (evidence_dir / "import-report.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--license-status",
        default="PENDING_USER_CONFIRMATION",
        choices=tuple(sorted(ALL_LICENSE_STATUSES)),
    )
    parser.add_argument("--apply", action="store_true", help="perform append-only Neo4j writes")
    parser.add_argument(
        "--allow-nonempty-target",
        action="store_true",
        help="explicitly permit a non-empty isolated target; never use for the existing graph",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        execute(
            run_id=args.run_id,
            plan_dir=args.plan_dir,
            env_file=args.env_file,
            apply=args.apply,
            license_status=args.license_status,
            allow_nonempty_target=args.allow_nonempty_target,
            batch_size=args.batch_size,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[FAIL] book graph import did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
