#!/usr/bin/env python3
"""Validate Markdown fences, structured examples, and local links."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import yaml


FENCE_PATTERN = re.compile(r"^\s*```\s*([A-Za-z0-9_-]*)\s*$")
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
STRUCTURED_LANGUAGES = {"json", "yaml", "yml"}


@dataclass(frozen=True, slots=True)
class DocumentationIssue:
    code: str
    path: str
    line: int
    detail: str


@dataclass(frozen=True, slots=True)
class StructuredBlock:
    language: str
    start_line: int
    content: str


def extract_blocks(path: str, text: str) -> tuple[list[StructuredBlock], list[DocumentationIssue]]:
    blocks: list[StructuredBlock] = []
    issues: list[DocumentationIssue] = []
    language: str | None = None
    start_line = 0
    content: list[str] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        match = FENCE_PATTERN.match(line)
        if match:
            if language is None:
                language = match.group(1).lower()
                start_line = line_number
                content = []
            else:
                if language in STRUCTURED_LANGUAGES:
                    blocks.append(StructuredBlock(language, start_line, "\n".join(content)))
                language = None
                start_line = 0
                content = []
            continue
        if language is not None:
            content.append(line)

    if language is not None:
        issues.append(
            DocumentationIssue(
                code="UNCLOSED_CODE_FENCE",
                path=path,
                line=start_line,
                detail=f"unclosed {language or 'plain'} fence",
            )
        )
    return blocks, issues


def validate_structured_blocks(
    path: str, blocks: Sequence[StructuredBlock]
) -> list[DocumentationIssue]:
    issues: list[DocumentationIssue] = []
    for block in blocks:
        try:
            if block.language == "json":
                json.loads(block.content)
            else:
                list(yaml.safe_load_all(block.content))
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            issues.append(
                DocumentationIssue(
                    code="INVALID_STRUCTURED_EXAMPLE",
                    path=path,
                    line=block.start_line,
                    detail=f"{block.language}: {exc}",
                )
            )
    return issues


def validate_local_links(path: Path, root: Path, text: str) -> list[DocumentationIssue]:
    issues: list[DocumentationIssue] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in LINK_PATTERN.finditer(line):
            target = match.group(1).strip()
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target_path = target.split("#", maxsplit=1)[0]
            if not target_path:
                continue
            resolved = (path.parent / target_path).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                issues.append(
                    DocumentationIssue(
                        code="LOCAL_LINK_OUTSIDE_REPOSITORY",
                        path=path.relative_to(root).as_posix(),
                        line=line_number,
                        detail=target,
                    )
                )
                continue
            if not resolved.exists():
                issues.append(
                    DocumentationIssue(
                        code="LOCAL_LINK_TARGET_MISSING",
                        path=path.relative_to(root).as_posix(),
                        line=line_number,
                        detail=target,
                    )
                )
    return issues


def validate_repository(root: Path) -> tuple[list[DocumentationIssue], int, int]:
    issues: list[DocumentationIssue] = []
    markdown_files = 0
    structured_blocks = 0
    for path in sorted(root.rglob("*.md")):
        if any(part in {".git", "node_modules"} for part in path.parts):
            continue
        markdown_files += 1
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        blocks, fence_issues = extract_blocks(relative, text)
        structured_blocks += len(blocks)
        issues.extend(fence_issues)
        issues.extend(validate_structured_blocks(relative, blocks))
        issues.extend(validate_local_links(path, root, text))
    return issues, markdown_files, structured_blocks


def render_report(
    issues: Sequence[DocumentationIssue],
    markdown_files: int,
    structured_blocks: int,
) -> str:
    return json.dumps(
        {
            "status": "PASS" if not issues else "FAIL",
            "markdown_files": markdown_files,
            "structured_blocks": structured_blocks,
            "issue_count": len(issues),
            "issues": [asdict(issue) for issue in issues],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    issues, markdown_files, structured_blocks = validate_repository(args.root.resolve())
    print(render_report(issues, markdown_files, structured_blocks))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
