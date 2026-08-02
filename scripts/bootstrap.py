"""Safe, create-only bootstrap checks for the G1 local environment.

The command never overwrites an environment file.  Configuration creation is
explicit so CI and verification can execute the read-only checks independently.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_TEMPLATES = (
    (Path(".env.host.example"), Path(".env.host")),
    (Path(".env.compose.example"), Path(".env.compose")),
)


@dataclass(frozen=True)
class ToolCheck:
    name: str
    available: bool
    detail: str


def _run_version(command: Sequence[str]) -> ToolCheck:
    executable = command[0]
    resolved = shutil.which(executable)
    if resolved is None:
        return ToolCheck(executable, False, "not found on PATH")

    completed = subprocess.run(
        [resolved, *command[1:]],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = (completed.stdout or completed.stderr).strip()
    detail = output if output else f"exit={completed.returncode}"
    return ToolCheck(executable, completed.returncode == 0, detail)


def _semantic_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def node_version_supported(version: tuple[int, int, int]) -> bool:
    major = version[0]
    return (
        (major == 20 and version >= (20, 19, 0))
        or (major == 22 and version >= (22, 13, 0))
        or major >= 24
    )


def _help_has_option(help_text: str, option: str) -> bool:
    return re.search(
        rf"(?<![A-Za-z0-9_-]){re.escape(option)}(?![A-Za-z0-9_-])",
        help_text,
    ) is not None


def _compose_exec_no_tty_available(help_text: str) -> bool:
    return any(
        _help_has_option(help_text, option)
        for option in ("--no-tty", "--no-TTY", "-T")
    )


def check_tools(
    runner: Callable[[Sequence[str]], ToolCheck] = _run_version,
    python_version: tuple[int, int, int] | None = None,
) -> tuple[ToolCheck, ...]:
    """Return deterministic checks without changing the host environment."""

    resolved_python = python_version or (
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro,
    )
    python_supported = (3, 11, 0) <= resolved_python < (3, 13, 0)
    python_check = ToolCheck(
        "python",
        python_supported,
        ".".join(str(part) for part in resolved_python),
    )
    node_raw = runner(("node", "--version"))
    node_version = _semantic_version(node_raw.detail) if node_raw.available else None
    node_check = ToolCheck(
        "node",
        node_raw.available
        and node_version is not None
        and node_version_supported(node_version),
        node_raw.detail,
    )
    npm_check = runner(("npm", "--version"))
    docker_check = runner(("docker", "--version"))
    compose_version = runner(("docker", "compose", "version"))
    compose_up_help = runner(("docker", "compose", "up", "--help"))
    compose_exec_help = runner(("docker", "compose", "exec", "--help"))
    missing_capabilities = [
        capability
        for capability, available in (
            ("up --wait", _help_has_option(compose_up_help.detail, "--wait")),
            (
                "up --wait-timeout",
                _help_has_option(compose_up_help.detail, "--wait-timeout"),
            ),
            (
                "exec --no-tty",
                _compose_exec_no_tty_available(compose_exec_help.detail),
            ),
        )
        if not available
    ]
    compose_available = (
        compose_version.available
        and compose_up_help.available
        and compose_exec_help.available
        and not missing_capabilities
    )
    compose_detail = compose_version.detail
    if missing_capabilities:
        compose_detail = "missing required capabilities: " + ", ".join(
            missing_capabilities
        )
    compose_check = ToolCheck("docker compose", compose_available, compose_detail)
    return (python_check, node_check, npm_check, docker_check, compose_check)


def validate_templates(root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    issues: list[str] = []
    for source, _target in CONFIG_TEMPLATES:
        source_path = root / source
        if not source_path.is_file():
            issues.append(f"missing configuration template: {source}")
    return tuple(issues)


def create_runtime_configs(root: Path = PROJECT_ROOT) -> tuple[Path, ...]:
    """Create both runtime configs exclusively; never replace existing files."""

    missing_templates = validate_templates(root)
    if missing_templates:
        raise RuntimeError("; ".join(missing_templates))

    existing_pairs = [
        (source, target)
        for source, target in CONFIG_TEMPLATES
        if (root / target).exists()
    ]
    if len(existing_pairs) == len(CONFIG_TEMPLATES):
        rendered = ", ".join(str(target) for _source, target in existing_pairs)
        raise FileExistsError(
            f"bootstrap refused to overwrite existing runtime configuration: {rendered}"
        )

    for source, target in existing_pairs:
        source_path = root / source
        target_path = root / target
        if target_path.is_symlink() or not target_path.is_file():
            raise FileExistsError(
                f"bootstrap found an unsafe existing runtime configuration: {target}"
            )
        if source_path.read_bytes() != target_path.read_bytes():
            raise FileExistsError(
                f"bootstrap refused to replace a modified runtime configuration: {target}"
            )

    created: list[Path] = []
    for source, target in CONFIG_TEMPLATES:
        source_path = root / source
        target_path = root / target
        if target_path.exists():
            continue
        with source_path.open("r", encoding="utf-8") as source_file:
            contents = source_file.read()
        with target_path.open("x", encoding="utf-8", newline="\n") as target_file:
            target_file.write(contents)
        created.append(target_path)
    return tuple(created)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create-config",
        action="store_true",
        help=(
            "create each missing runtime config exclusively; an existing target is "
            "accepted only when it still exactly matches its template"
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="repository root (defaults to the root derived from this script)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()

    issues = list(validate_templates(root))
    checks = check_tools()
    for check in checks:
        state = "OK" if check.available else "MISSING"
        summary = check.detail.splitlines()[0] if check.detail else "no output"
        print(f"[{state}] {check.name}: {summary}")
        if not check.available:
            issues.append(f"required tool unavailable: {check.name}")

    if issues:
        for issue in issues:
            print(f"[ERROR] {issue}", file=sys.stderr)
        return 2

    if args.create_config:
        try:
            created = create_runtime_configs(root)
        except (FileExistsError, RuntimeError, OSError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 3
        for path in created:
            print(f"[CREATED] {path.relative_to(root)}")
    else:
        print("[PASS] bootstrap prerequisites and templates are available (read-only check)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
