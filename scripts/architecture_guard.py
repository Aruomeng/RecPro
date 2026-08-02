#!/usr/bin/env python3
"""Check the modular-monolith dependency direction using Python ASTs."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DOMAIN_FORBIDDEN_ROOTS = {
    "fastapi",
    "sqlalchemy",
    "chromadb",
    "neo4j",
    "pymysql",
    "asyncmy",
    "openai",
    "anthropic",
    "requests",
    "httpx",
}
AGENT_FORBIDDEN_ROOTS = {
    "os",
    "pathlib",
    "shutil",
    "subprocess",
    "sqlite3",
    "sqlalchemy",
    "chromadb",
    "neo4j",
    "pymysql",
    "asyncmy",
    "openai",
    "anthropic",
    "requests",
    "httpx",
}
API_FORBIDDEN_ROOTS = {"sqlalchemy", "chromadb", "neo4j", "pymysql", "asyncmy"}
AGENT_FORBIDDEN_PARTS = {".adapters", ".infrastructure", ".platform", ".db"}
DOMAIN_FORBIDDEN_PARTS = {
    ".adapters",
    ".api",
    ".application",
    ".infrastructure",
    ".platform",
    ".ports",
    ".db",
}
APPLICATION_FORBIDDEN_PARTS = {".adapters", ".infrastructure", ".platform", ".db"}
API_FORBIDDEN_PARTS = {".adapters", ".infrastructure", ".platform", ".db", ".repository", ".repositories"}
DETERMINISTIC_FORBIDDEN_PARTS = {".adapters", ".infrastructure", ".platform", ".db", ".repository", ".repositories"}
AGENT_SHARED_MODULES = {"__init__", "base", "contracts", "public", "registry", "types"}
BUSINESS_MODULES = {
    "catalog",
    "profile",
    "recommendation",
    "feedback",
    "observability",
    "evaluation",
}


def _is_project_import(imported: str) -> bool:
    return imported == "backend.app" or imported.startswith("backend.app.")


def _matches_module(imported: str, prefix: str) -> bool:
    return imported == prefix or imported.startswith(f"{prefix}.")


def _is_allowed_domain_import(source_module: str | None, imported: str) -> bool:
    """Apply a fail-closed allowlist to project-local Domain dependencies."""

    if not _is_project_import(imported):
        return True
    shared_prefixes = (
        "backend.app.shared_kernel.contracts",
        "backend.app.shared_kernel.domain",
    )
    if any(_matches_module(imported, prefix) for prefix in shared_prefixes):
        return True
    if source_module in BUSINESS_MODULES:
        own_domain = f"backend.app.{source_module}.domain"
        return _matches_module(imported, own_domain)
    return False


def _is_allowed_api_import(imported: str) -> bool:
    """Keep HTTP adapters on API DTOs, shared contracts, and public use cases."""

    if not _is_project_import(imported):
        return True
    if any(
        _matches_module(imported, prefix)
        for prefix in (
            "backend.app.api",
            "backend.app.shared_kernel",
            # HTTP adapters may emit through the process-wide structured logger;
            # this exact module exposes no persistence or business implementation.
            "backend.app.logging",
        )
    ):
        return True
    parts = imported.split(".")
    return (
        len(parts) >= 5
        and parts[:2] == ["backend", "app"]
        and parts[2] in BUSINESS_MODULES
        and parts[3:5] == ["application", "public"]
    )


@dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    code: str
    path: str
    line: int
    imported: str


def _source_package(path: str) -> list[str]:
    parts = path.replace("\\", "/").removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        return parts[:-1]
    return parts[:-1]


def _resolve_import(path: str, node: ast.ImportFrom) -> list[str]:
    if node.level == 0:
        return [node.module] if node.module else []
    package = _source_package(path)
    keep = len(package) - (node.level - 1)
    if keep < 0:
        return ["." * node.level + (node.module or "")]
    base = package[:keep]
    if node.module:
        return [".".join(base + node.module.split("."))]
    return [".".join(base + alias.name.split(".")) for alias in node.names]


def imported_modules(path: str, text: str) -> list[tuple[int, str]]:
    tree = ast.parse(text)
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend((node.lineno, module) for module in _resolve_import(path, node))
    return imports


def check_source(path: str, text: str) -> list[ArchitectureViolation]:
    normalized = path.replace("\\", "/")
    try:
        imports = imported_modules(normalized, text)
    except SyntaxError as exc:
        return [
            ArchitectureViolation(
                "PYTHON_SYNTAX_ERROR",
                path,
                exc.lineno or 0,
                exc.msg,
            )
        ]
    violations: list[ArchitectureViolation] = []
    is_domain = "/domain/" in normalized or "/shared_kernel/contracts/" in normalized
    is_agent = "/agents/" in normalized
    is_api = "/api/" in normalized
    is_application = "/application/" in normalized
    is_shared_kernel = "/shared_kernel/" in normalized
    is_ranking = "/recommendation/ranking/" in normalized
    is_explanation = "/recommendation/explanation/" in normalized
    source_stem = Path(normalized).stem
    path_parts = normalized.split("/")
    source_module = path_parts[2] if len(path_parts) > 2 and path_parts[:2] == ["backend", "app"] else None
    for line, imported in imports:
        root = imported.split(".", maxsplit=1)[0]
        qualified_import = "." + imported.lstrip(".")
        imported_parts = imported.split(".")
        imported_module = (
            imported_parts[2]
            if len(imported_parts) > 2 and imported_parts[:2] == ["backend", "app"]
            else None
        )
        if is_shared_kernel and imported_module in BUSINESS_MODULES:
            violations.append(
                ArchitectureViolation("SHARED_KERNEL_DOMAIN_DEPENDENCY", path, line, imported)
            )
        if is_domain and (
            root in DOMAIN_FORBIDDEN_ROOTS
            or any(part in qualified_import for part in DOMAIN_FORBIDDEN_PARTS)
            or not _is_allowed_domain_import(source_module, imported)
        ):
            violations.append(
                ArchitectureViolation("DOMAIN_INFRA_DEPENDENCY", path, line, imported)
            )
        if is_agent and (
            root in AGENT_FORBIDDEN_ROOTS
            or any(part in qualified_import for part in AGENT_FORBIDDEN_PARTS)
        ):
            violations.append(
                ArchitectureViolation("AGENT_INFRA_DEPENDENCY", path, line, imported)
            )
        imported_tail = imported.rsplit(".", maxsplit=1)[-1]
        if (
            is_agent
            and source_stem not in AGENT_SHARED_MODULES
            and ".agents." in f"{qualified_import}."
            and imported_tail not in AGENT_SHARED_MODULES
        ):
            violations.append(
                ArchitectureViolation("AGENT_TO_AGENT_IMPORT", path, line, imported)
            )
        if is_api and (
            root in API_FORBIDDEN_ROOTS
            or any(part in qualified_import for part in API_FORBIDDEN_PARTS)
            or not _is_allowed_api_import(imported)
        ):
            violations.append(
                ArchitectureViolation("API_ORM_DEPENDENCY", path, line, imported)
            )
        if is_application and any(
            part in qualified_import for part in APPLICATION_FORBIDDEN_PARTS
        ):
            violations.append(
                ArchitectureViolation("APPLICATION_INFRA_DEPENDENCY", path, line, imported)
            )
        if (
            source_module in BUSINESS_MODULES
            and imported_module in BUSINESS_MODULES
            and source_module != imported_module
            and not imported.endswith(
                (".application.public", ".ports.public", ".domain.public")
            )
        ):
            violations.append(
                ArchitectureViolation("CROSS_MODULE_INTERNAL_DEPENDENCY", path, line, imported)
            )
        if is_ranking and ".recommendation.retrieval" in qualified_import:
            violations.append(
                ArchitectureViolation("RANKING_RETRIEVAL_DEPENDENCY", path, line, imported)
            )
        if is_explanation and ".recommendation.ranking" in qualified_import:
            violations.append(
                ArchitectureViolation("EXPLANATION_RANKING_DEPENDENCY", path, line, imported)
            )
        if (is_ranking or is_explanation) and (
            root in AGENT_FORBIDDEN_ROOTS
            or any(part in qualified_import for part in DETERMINISTIC_FORBIDDEN_PARTS)
        ):
            violations.append(
                ArchitectureViolation(
                    "DETERMINISTIC_SERVICE_INFRA_DEPENDENCY",
                    path,
                    line,
                    imported,
                )
            )
    return violations


def scan(root: Path) -> tuple[list[ArchitectureViolation], int]:
    source_root = root / "backend" / "app"
    if not source_root.exists():
        return [], 0
    violations: list[ArchitectureViolation] = []
    count = 0
    for path in sorted(source_root.rglob("*.py")):
        count += 1
        relative = path.relative_to(root).as_posix()
        violations.extend(check_source(relative, path.read_text(encoding="utf-8")))
    return violations, count


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    violations, scanned_files = scan(args.root.resolve())
    print(
        json.dumps(
            {
                "status": "PASS" if not violations else "FAIL",
                "scanned_files": scanned_files,
                "violation_count": len(violations),
                "violations": [asdict(item) for item in violations],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
