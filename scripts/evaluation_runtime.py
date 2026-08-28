"""Shared deterministic helpers for development and formal evaluation tooling.

The helpers are deliberately file-only.  They never connect to MySQL, Neo4j,
Chroma or an LLM provider, and every output is created with exclusive-create
semantics so a frozen run can never be overwritten.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_safe_id(value: str, *, label: str) -> str:
    if SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must use 3-64 safe characters")
    return value


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no} must contain a JSON object")
        rows.append(value)
    return rows


def reserve_directory(path: Path) -> None:
    """Create one new directory and fail if it already exists."""

    path.mkdir(parents=True, exist_ok=False)


def write_json_exclusive(path: Path, value: object) -> None:
    with path.open("xb") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
        handle.write(b"\n")


def write_jsonl_exclusive(path: Path, rows: Iterable[Mapping[str, Any]]) -> tuple[int, str]:
    digest = sha256()
    count = 0
    with path.open("xb") as handle:
        for row in rows:
            payload = canonical_bytes(dict(row))
            handle.write(payload)
            digest.update(payload)
            count += 1
    return count, digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(float(ordered[position]), 6)


__all__ = [
    "PROJECT_ROOT",
    "canonical_bytes",
    "percentile",
    "read_json",
    "read_jsonl",
    "reserve_directory",
    "sha256_bytes",
    "sha256_file",
    "validate_safe_id",
    "write_json_exclusive",
    "write_jsonl_exclusive",
]
