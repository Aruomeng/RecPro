#!/usr/bin/env python3
"""Fail closed when executable project files contain destructive operations.

The scanner is intentionally dependency-free so it can run before the runtime
environment is bootstrapped. Markdown prose is outside the executable suffix
allowlist; executable files remain in scope even when placed under docs or tests.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


SCANNED_SUFFIXES = {
    ".py",
    ".sh",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".mk",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".vue",
}
SCANNED_NAMES = {"Makefile", "Dockerfile", "package.json"}
EXCLUDED_PARTS = {".git", "node_modules", "__pycache__"}
EXCLUDED_FILES = {
    Path("scripts/safety_scan.py"),
}
# Vite output is reproducibly generated from scanned source and package scripts.
# Keep this exact path narrow: a generic ``dist`` exclusion would create an
# avoidable hiding place elsewhere in the repository.
GENERATED_PREFIXES = (Path("frontend/dist"),)


def _join(*parts: str) -> str:
    """Build scanner signatures without making this source match itself."""

    return "".join(parts)


FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "FILE_REMOVE",
        re.compile(
            _join(r"\br", r"m\s+(?:(?:-[A-Za-z]+|--[A-Za-z-]+)\s+)*[^\s]"),
            re.I,
        ),
    ),
    ("FILE_RIMRAF", re.compile(_join(r"\brim", r"raf\b"), re.I)),
    ("FILE_UNLINK", re.compile(_join(r"\.un", r"link\s*\("), re.I)),
    ("FILE_RMTREE", re.compile(_join(r"shutil\.rm", r"tree\s*\("), re.I)),
    ("FILE_OS_REMOVE", re.compile(_join(r"os\.re", r"move\s*\("), re.I)),
    ("FILE_RMDIR", re.compile(_join(r"(?:\brm", r"dir\b|\.rmdir\s*\()"), re.I)),
    ("FILE_FIND_DELETE", re.compile(_join(r"\bfind\b[^\n]*\s-de", r"lete\b"), re.I)),
    (
        "JS_FILE_REMOVE",
        re.compile(_join(r"\bfs(?:\.promises)?\.(?:rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)", r"\s*\(")),
    ),
    ("GIT_CLEAN", re.compile(_join(r"\bgit\s+cl", r"ean\b"), re.I)),
    ("GIT_HARD_RESET", re.compile(_join(r"\bgit\s+reset\s+--h", r"ard\b"), re.I)),
    (
        "GIT_DISCARD_CHECKOUT",
        re.compile(_join(r"\bgit\s+check", r"out\s+--(?:\s|$)"), re.I),
    ),
    ("GIT_DISCARD_RESTORE", re.compile(_join(r"\bgit\s+rest", r"ore\b"), re.I)),
    ("GIT_BRANCH_FORCE_DELETE", re.compile(_join(r"\bgit\s+branch\s+-D", r"\b"))),
    ("GIT_REMOTE_DELETE", re.compile(_join(r"\bgit\s+push\b[^\n]*--de", r"lete\b"), re.I)),
    ("SQL_DELETE", re.compile(_join(r"\bDE", r"LETE\s+FROM\b"), re.I)),
    ("SQL_TRUNCATE", re.compile(_join(r"\bTRUN", r"CATE(?:\s+TABLE)?\b"), re.I)),
    (
        "SQL_DROP",
        re.compile(
            _join(
                r"\bDR",
                r"OP\s+(?:TABLE|DATABASE|SCHEMA|INDEX|COLUMN|VIEW|TRIGGER|PROCEDURE|FUNCTION|EVENT|USER|ROLE)\b",
            ),
            re.I,
        ),
    ),
    ("SQL_ALTER_DROP", re.compile(_join(r"\bALTER\s+TABLE\b[^;]*?\bDR", r"OP\b"), re.I)),
    ("SQL_REPLACE_INTO", re.compile(_join(r"\bREPL", r"ACE\s+INTO\b"), re.I)),
    (
        "SQL_DELETE_CASCADE",
        re.compile(_join(r"ON\s+DE", r"LETE\s+(?:CASCADE|SET\s+NULL)"), re.I),
    ),
    ("ALEMBIC_DOWNGRADE", re.compile(_join(r"\balembic\s+down", r"grade\b"), re.I)),
    ("ALEMBIC_DROP_OP", re.compile(_join(r"\bop\.dr", r"op_\w+\s*\("), re.I)),
    ("NEO4J_DETACH_DELETE", re.compile(_join(r"\bDETACH\s+DE", r"LETE\b"), re.I)),
    ("NEO4J_DELETE", re.compile(_join(r"\bDE", r"LETE\s+(?:\w+|\([^)]*\))"), re.I)),
    ("NEO4J_DROP_DATABASE", re.compile(_join(r"\bDR", r"OP\s+DATABASE\b"), re.I)),
    (
        "CHROMA_DELETE_COLLECTION",
        re.compile(_join(r"\.delete_col", r"lection\s*\("), re.I),
    ),
    (
        "CHROMA_DELETE",
        re.compile(
            _join(
                r"\b(?:chroma\w*|collection|vector_(?:store|client)|embedding_store)\.de",
                r"lete\s*\(",
            ),
            re.I,
        ),
    ),
    (
        "CHROMA_RESET",
        re.compile(
            _join(
                r"\b(?:chroma\w*|collection|vector_(?:store|client)|embedding_store)\.re",
                r"set\s*\(",
            ),
            re.I,
        ),
    ),
    (
        "HTTP_DELETE_METHOD",
        re.compile(_join(r"\bmethod\s*:\s*['\"]DE", r"LETE['\"]"), re.I),
    ),
    (
        "GENERIC_DESTRUCTIVE_CALL",
        re.compile(
            _join(
                r"\b(?:de",
                r"lete|drop|truncate|purge|destroy|erase)(?:_[A-Za-z0-9_]+|[A-Z][A-Za-z0-9_]*)?\s*\(",
            )
        ),
    ),
    (
        "DOCKER_DOWN_VOLUME",
        re.compile(
            _join(r"docker\s+compose\s+down\b[^\n]*(?:\s-v\b|--vol", r"umes\b)"),
            re.I,
        ),
    ),
    ("DOCKER_COMPOSE_REMOVE", re.compile(_join(r"docker\s+compose\s+r", r"m\b"), re.I)),
    (
        "DOCKER_VOLUME_REMOVE",
        re.compile(_join(r"docker\s+volume\s+(?:r", r"m|prune)\b"), re.I),
    ),
    ("DOCKER_PRUNE", re.compile(_join(r"docker\s+(?:system|image)\s+pr", r"une\b"), re.I)),
)

FORBIDDEN_REPOSITORY_METHODS = {
    "delete",
    "drop",
    "remove",
    "reset",
    "truncate",
    "purge",
    "destroy",
    "erase",
    "clear",
}
GLOBALLY_FORBIDDEN_METHODS = {
    "delete",
    "drop",
    "truncate",
    "purge",
    "destroy",
    "erase",
}
SENSITIVE_METHOD_PATHS = {
    "ports",
    "adapters",
    "migrations",
    "scripts",
    "platform",
    "db",
    "persistence",
    "repository",
    "repositories",
}
SENSITIVE_DESTRUCTIVE_CALLS = {
    "delete",
    "drop",
    "truncate",
    "purge",
    "destroy",
    "erase",
    "remove",
    "reset",
    "clear",
}


def _matches_destructive_name(name: str, forbidden: set[str]) -> bool:
    lowered = name.lower()
    return lowered in forbidden or any(
        lowered.startswith(f"{prefix}_") for prefix in forbidden
    )


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    path: str
    line: int
    excerpt: str


def should_scan(relative_path: Path) -> bool:
    if relative_path in EXCLUDED_FILES:
        return False
    # Root-only local interpreters are isolated, ignored dependency trees.  Do
    # not generalize this to nested directories, which remain fail-closed.
    if relative_path.parts and (
        relative_path.parts[0] == ".venv"
        or relative_path.parts[0].startswith(".venv-")
    ):
        return False
    if any(
        relative_path == prefix or prefix in relative_path.parents
        for prefix in GENERATED_PREFIXES
    ):
        return False
    if any(part in EXCLUDED_PARTS for part in relative_path.parts):
        return False
    return relative_path.suffix in SCANNED_SUFFIXES or relative_path.name in SCANNED_NAMES


def _is_sensitive_implementation_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    parts = set(Path(normalized).parts)
    return bool(parts & SENSITIVE_METHOD_PATHS) or any(
        segment in normalized for segment in ("repository", "repositories")
    )


def find_text_violations(path: str, text: str) -> list[Violation]:
    violations: list[Violation] = []
    for code, pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            line_number = text.count("\n", 0, match.start()) + 1
            excerpt = " ".join(match.group(0).split())[:240]
            violations.append(
                Violation(
                    code=code,
                    path=path,
                    line=line_number,
                    excerpt=excerpt,
                )
            )
    return violations


def find_repository_interface_violations(path: str, text: str) -> list[Violation]:
    sensitive_path = _is_sensitive_implementation_path(path)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lowered = node.name.lower()
            if _matches_destructive_name(
                lowered,
                GLOBALLY_FORBIDDEN_METHODS,
            ) or sensitive_path and (
                _matches_destructive_name(lowered, FORBIDDEN_REPOSITORY_METHODS)
            ):
                violations.append(
                    Violation(
                        code="DESTRUCTIVE_REPOSITORY_METHOD",
                        path=path,
                        line=node.lineno,
                        excerpt=node.name,
                    )
                )
    return violations


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local_name = item.asname or item.name.split(".", maxsplit=1)[0]
                aliases[local_name] = item.name if item.asname else local_name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name == "*":
                    continue
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _resolve_alias(name: str, aliases: dict[str, str]) -> str:
    if not name:
        return ""
    head, separator, tail = name.partition(".")
    resolved_head = aliases.get(head, head)
    return f"{resolved_head}.{tail}" if separator else resolved_head


def _literal_getattr_target(node: ast.AST, aliases: dict[str, str]) -> str:
    if not isinstance(node, ast.Call):
        return ""
    if _resolve_alias(_call_name(node.func), aliases) not in {"getattr", "builtins.getattr"}:
        return ""
    if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
        return ""
    attribute = node.args[1].value
    if not isinstance(attribute, str):
        return ""
    receiver = _resolve_alias(_call_name(node.args[0]), aliases)
    return f"{receiver}.{attribute}" if receiver else attribute


def find_python_ast_violations(path: str, text: str) -> list[Violation]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [
            Violation(
                code="PYTHON_SYNTAX_ERROR",
                path=path,
                line=exc.lineno or 0,
                excerpt=exc.msg,
            )
        ]

    violations: list[Violation] = []
    path_variables: set[str] = set()
    sensitive_path = _is_sensitive_implementation_path(path)
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if isinstance(value, ast.Call):
            continue
        resolved_value = _resolve_alias(_call_name(value), aliases)
        resolved_tail = resolved_value.rsplit(".", maxsplit=1)[-1].lower()
        if not _matches_destructive_name(
            resolved_tail,
            SENSITIVE_DESTRUCTIVE_CALLS,
        ) and resolved_value not in {
            "os.unlink",
            "os.rmdir",
            "shutil.rmtree",
        }:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id] = resolved_value
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if (
            not isinstance(value, ast.Call)
            or _resolve_alias(_call_name(value.func), aliases) != "pathlib.Path"
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        path_variables.update(
            target.id.lower() for target in targets if isinstance(target, ast.Name)
        )
    subprocess_calls = {
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
    }
    direct_file_move_calls = {"os.rename", "os.replace", "shutil.move"}
    direct_file_delete_calls = {
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "shutil.rmtree",
        "pathlib.Path.unlink",
        "pathlib.Path.rmdir",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        raw_call_name = _call_name(node.func)
        call_name = _resolve_alias(raw_call_name, aliases)
        dynamic_call_name = _literal_getattr_target(node.func, aliases)
        effective_call_name = dynamic_call_name or call_name
        call_tail = effective_call_name.rsplit(".", maxsplit=1)[-1].lower()
        globally_destructive = _matches_destructive_name(
            call_tail,
            GLOBALLY_FORBIDDEN_METHODS,
        )
        sensitive_destructive = sensitive_path and _matches_destructive_name(
            call_tail,
            SENSITIVE_DESTRUCTIVE_CALLS,
        )
        if globally_destructive or sensitive_destructive:
            violations.append(
                Violation(
                    code="SENSITIVE_DESTRUCTIVE_CALL",
                    path=path,
                    line=node.lineno,
                    excerpt=f"{effective_call_name}(...)"[:240],
                )
            )
        if effective_call_name in direct_file_delete_calls:
            violations.append(
                Violation(
                    code="FILE_DELETE_CALL",
                    path=path,
                    line=node.lineno,
                    excerpt=f"{effective_call_name}(...)"[:240],
                )
            )
        if call_name in direct_file_move_calls:
            violations.append(
                Violation(
                    code="FILE_MOVE_OR_OVERWRITE_RISK",
                    path=path,
                    line=node.lineno,
                    excerpt=f"{call_name}(...)"[:240],
                )
            )
        if call_name in subprocess_calls and node.args:
            try:
                command = ast.literal_eval(node.args[0])
            except (ValueError, TypeError, SyntaxError):
                command = None
            if isinstance(command, (list, tuple)) and all(
                isinstance(part, str) for part in command
            ):
                joined = " ".join(command)
                for item in find_text_violations(path, joined):
                    violations.append(
                        Violation(
                            code="DESTRUCTIVE_SUBPROCESS_COMMAND",
                            path=path,
                            line=node.lineno,
                            excerpt=item.excerpt,
                        )
                    )
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"rename", "replace"}:
            receiver = node.func.value
            receiver_name = _resolve_alias(_call_name(receiver), aliases).lower()
            is_path_constructor = (
                isinstance(receiver, ast.Call)
                and _resolve_alias(_call_name(receiver.func), aliases)
                == "pathlib.Path"
            )
            if is_path_constructor or receiver_name in path_variables:
                violations.append(
                    Violation(
                        code="FILE_REPLACE_OVERWRITE_RISK",
                        path=path,
                        line=node.lineno,
                        excerpt=(
                            f"{receiver_name or 'Path(...)'}.{node.func.attr}(...)"
                        )[:240],
                    )
                )
    return violations


def find_git_history_violations(output: str) -> list[Violation]:
    """Parse committed delete/rename records from git name-status output."""

    violations: list[Violation] = []
    for line in filter(None, output.splitlines()):
        fields = line.split("\t")
        status = fields[0]
        if status.startswith("D") and len(fields) >= 2:
            target = fields[1]
        elif status.startswith("R") and len(fields) >= 3:
            target = f"{fields[1]} -> {fields[2]}"
        else:
            continue
        violations.append(
            Violation(
                code="GIT_HISTORY_DELETE_OR_RENAME",
                path=target,
                line=0,
                excerpt=f"git diff status={status}",
            )
        )
    return violations


def _git_deletion_violations(root: Path, base_ref: str | None = None) -> list[Violation]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return [
            Violation(
                code="GIT_STATUS_UNAVAILABLE",
                path=".git",
                line=0,
                excerpt=result.stderr.strip()[:240],
            )
        ]
    violations: list[Violation] = []
    for entry in filter(None, result.stdout.split("\0")):
        status = entry[:2]
        path = entry[3:]
        if "D" in status or "R" in status:
            violations.append(
                Violation(
                    code="GIT_DELETE_OR_RENAME",
                    path=path,
                    line=0,
                    excerpt=f"git status={status}",
                )
            )
    if base_ref is None:
        return violations
    if (
        not base_ref
        or base_ref.startswith("-")
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", base_ref)
    ):
        return violations + [
            Violation(
                code="GIT_BASE_REF_INVALID",
                path=".git",
                line=0,
                excerpt=str(base_ref)[:240],
            )
        ]
    comparison = subprocess.run(
        [
            "git",
            "log",
            "--format=",
            "--name-status",
            "--diff-filter=DR",
            "--find-renames",
            "-m",
            f"{base_ref}..HEAD",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if comparison.returncode != 0:
        return violations + [
            Violation(
                code="GIT_HISTORY_DIFF_UNAVAILABLE",
                path=".git",
                line=0,
                excerpt=comparison.stderr.strip()[:240],
            )
        ]
    return violations + find_git_history_violations(comparison.stdout)


def scan_repository(
    root: Path,
    base_ref: str | None = None,
) -> tuple[list[Violation], int]:
    violations: list[Violation] = []
    scanned_files = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if not should_scan(relative):
            continue
        scanned_files += 1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            violations.append(
                Violation(
                    code="NON_UTF8_EXECUTABLE_FILE",
                    path=relative.as_posix(),
                    line=0,
                    excerpt="Executable project files must use UTF-8.",
                )
            )
            continue
        violations.extend(find_text_violations(relative.as_posix(), text))
        violations.extend(find_repository_interface_violations(relative.as_posix(), text))
        if relative.suffix == ".py":
            violations.extend(find_python_ast_violations(relative.as_posix(), text))
    violations.extend(_git_deletion_violations(root, base_ref=base_ref))
    return violations, scanned_files


def render_report(violations: Sequence[Violation], scanned_files: int) -> str:
    return json.dumps(
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--base-ref",
        help="also reject committed deletes or renames between this Git ref and HEAD",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    violations, scanned_files = scan_repository(root, base_ref=args.base_ref)
    print(render_report(violations, scanned_files))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
