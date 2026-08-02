from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"


def requirement_pins(lines: list[str]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def locked_requirement_blocks(lock_text: str) -> tuple[str, ...]:
    lines = lock_text.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^[A-Za-z0-9_.-]+==", line)
    ]
    blocks: list[str] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        blocks.append("\n".join(lines[start:end]))
    return tuple(blocks)


class DependencyLockTest(unittest.TestCase):
    def test_g0_direct_requirements_match_pyproject_extra(self) -> None:
        pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text())
        declared = requirement_pins(
            pyproject["project"]["optional-dependencies"]["g0"]
        )
        input_requirements = requirement_pins(
            (BACKEND / "requirements-g0.in").read_text().splitlines()
        )
        self.assertEqual(declared, input_requirements)

    def test_direct_requirements_match_pyproject_declarations(self) -> None:
        pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text())
        runtime_declared = requirement_pins(pyproject["project"]["dependencies"])
        runtime_input = requirement_pins(
            (BACKEND / "requirements-g1.in").read_text().splitlines()
        )
        test_declared = requirement_pins(
            pyproject["project"]["optional-dependencies"]["g1-test"]
        )
        test_input = requirement_pins(
            (BACKEND / "requirements-g1-test.in").read_text().splitlines()
        )
        self.assertEqual(runtime_declared, runtime_input)
        self.assertEqual(test_declared, test_input)

    def test_every_locked_distribution_has_hash_and_exact_version(self) -> None:
        for lock_name in (
            "requirements-g0.lock",
            "requirements-g1.lock",
            "requirements-g1-test.lock",
        ):
            lock_text = (BACKEND / lock_name).read_text()
            package_blocks = locked_requirement_blocks(lock_text)
            self.assertGreater(len(package_blocks), 1)
            for block in package_blocks:
                with self.subTest(
                    lock_name=lock_name,
                    package=block.split("==", maxsplit=1)[0],
                ):
                    self.assertRegex(block, r"^[A-Za-z0-9_.-]+==[^\s\\]+")
                    self.assertIn("--hash=sha256:", block)

    def test_input_pins_are_preserved_in_generated_locks(self) -> None:
        for generation in ("g0", "g1", "g1-test"):
            declared = requirement_pins(
                (BACKEND / f"requirements-{generation}.in").read_text().splitlines()
            )
            locked = requirement_pins(
                (BACKEND / f"requirements-{generation}.lock").read_text().splitlines()
            )
            with self.subTest(generation=generation):
                self.assertEqual(declared, {name: locked[name] for name in declared})

    def test_docker_install_enforces_hashes(self) -> None:
        dockerfile = (BACKEND / "Dockerfile").read_text()
        self.assertRegex(
            dockerfile,
            r"FROM python:3\.11\.15-slim-trixie@sha256:[0-9a-f]{64}",
        )
        self.assertIn("--require-hashes", dockerfile)
        self.assertNotIn(":latest", dockerfile)
        self.assertIn("requirements-g1.lock", dockerfile)
        self.assertNotIn("requirements-g1-test.lock", dockerfile)

    def test_runtime_lock_excludes_http_client_test_dependency(self) -> None:
        runtime_lock = (BACKEND / "requirements-g1.lock").read_text()
        test_lock = (BACKEND / "requirements-g1-test.lock").read_text()
        self.assertNotRegex(runtime_lock, r"(?m)^httpx2==")
        self.assertRegex(test_lock, r"(?m)^httpx2==2\.9\.1")

    def test_combined_locks_have_no_overlapping_version_conflicts(self) -> None:
        observed: dict[str, tuple[str, str]] = {}
        for lock_name in (
            "requirements-g0.lock",
            "requirements-g1.lock",
            "requirements-g1-test.lock",
        ):
            pins = requirement_pins((BACKEND / lock_name).read_text().splitlines())
            for raw_name, version in pins.items():
                name = canonical_distribution_name(raw_name)
                if name in observed:
                    prior_lock, prior_version = observed[name]
                    self.assertEqual(
                        prior_version,
                        version,
                        msg=(
                            f"{name} conflicts between {prior_lock} ({prior_version}) "
                            f"and {lock_name} ({version})"
                        ),
                    )
                else:
                    observed[name] = (lock_name, version)
