from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import mkdtemp

from scripts.bootstrap import (
    CONFIG_TEMPLATES,
    ToolCheck,
    check_tools,
    create_runtime_configs,
    node_version_supported,
)


class BootstrapContractTests(unittest.TestCase):
    def test_runtime_configuration_targets_are_distinct_and_untracked(self) -> None:
        sources = {source for source, _target in CONFIG_TEMPLATES}
        targets = {target for _source, target in CONFIG_TEMPLATES}

        self.assertEqual(
            sources,
            {Path(".env.host.example"), Path(".env.compose.example")},
        )
        self.assertEqual(targets, {Path(".env.host"), Path(".env.compose")})
        self.assertTrue(sources.isdisjoint(targets))

    def test_tool_checks_cover_python_node_npm_and_compose(self) -> None:
        observed: list[tuple[str, ...]] = []

        def fake_runner(command: tuple[str, ...]) -> ToolCheck:
            observed.append(command)
            if command == ("node", "--version"):
                return ToolCheck("node", True, "v20.19.3")
            if command[-2:] == ("up", "--help"):
                return ToolCheck("docker", True, "--wait --wait-timeout")
            if command[-2:] == ("exec", "--help"):
                return ToolCheck("docker", True, "-T, --no-tty")
            return ToolCheck(command[0], True, "test")

        results = check_tools(fake_runner, python_version=(3, 11, 14))

        self.assertEqual(len(results), 5)
        self.assertEqual(results[0], ToolCheck("python", True, "3.11.14"))
        self.assertIn(("node", "--version"), observed)
        self.assertIn(("npm", "--version"), observed)
        self.assertIn(("docker", "--version"), observed)
        self.assertIn(("docker", "compose", "version"), observed)
        self.assertIn(("docker", "compose", "up", "--help"), observed)
        self.assertIn(("docker", "compose", "exec", "--help"), observed)

    def test_unsupported_python_fails_closed(self) -> None:
        def supported_runner(command: tuple[str, ...]) -> ToolCheck:
            if command == ("node", "--version"):
                return ToolCheck("node", True, "v20.19.3")
            if command[-2:] == ("up", "--help"):
                return ToolCheck("docker", True, "--wait --wait-timeout")
            if command[-2:] == ("exec", "--help"):
                return ToolCheck("docker", True, "--no-tty")
            return ToolCheck(command[0], True, "test")

        results = check_tools(supported_runner, python_version=(3, 10, 10))

        self.assertFalse(results[0].available)

    def test_old_node_or_missing_compose_flags_fail_closed(self) -> None:
        def incompatible_runner(command: tuple[str, ...]) -> ToolCheck:
            if command == ("node", "--version"):
                return ToolCheck("node", True, "v20.18.0")
            if command[-2:] == ("up", "--help"):
                return ToolCheck("docker", True, "--wait")
            if command[-2:] == ("exec", "--help"):
                return ToolCheck("docker", True, "--index --env")
            return ToolCheck(command[0], True, "test")

        results = check_tools(incompatible_runner, python_version=(3, 11, 14))

        self.assertFalse(results[1].available)
        self.assertFalse(results[4].available)
        self.assertIn("up --wait-timeout", results[4].detail)
        self.assertIn("exec --no-tty", results[4].detail)

    def test_node_version_range_matches_all_locked_frontend_tools(self) -> None:
        expectations = {
            (20, 18, 9): False,
            (20, 19, 0): True,
            (21, 9, 0): False,
            (22, 12, 0): False,
            (22, 13, 0): True,
            (23, 9, 0): False,
            (24, 0, 0): True,
            (25, 6, 0): True,
        }
        for version, expected in expectations.items():
            with self.subTest(version=version):
                self.assertEqual(expected, node_version_supported(version))

    def test_partial_identical_bootstrap_can_append_the_missing_config(self) -> None:
        root = Path(mkdtemp(prefix="recpro-bootstrap-partial-"))
        for source, _target in CONFIG_TEMPLATES:
            (root / source).write_text(f"template={source.name}\n", encoding="utf-8")
        first_source, first_target = CONFIG_TEMPLATES[0]
        (root / first_target).write_bytes((root / first_source).read_bytes())

        created = create_runtime_configs(root)

        self.assertEqual((root / CONFIG_TEMPLATES[1][1],), created)
        self.assertEqual(
            (root / CONFIG_TEMPLATES[1][0]).read_bytes(),
            (root / CONFIG_TEMPLATES[1][1]).read_bytes(),
        )

    def test_partial_modified_bootstrap_is_never_overwritten(self) -> None:
        root = Path(mkdtemp(prefix="recpro-bootstrap-modified-"))
        for source, _target in CONFIG_TEMPLATES:
            (root / source).write_text(f"template={source.name}\n", encoding="utf-8")
        (root / CONFIG_TEMPLATES[0][1]).write_text("user-change=true\n", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            create_runtime_configs(root)

        self.assertEqual(
            "user-change=true\n",
            (root / CONFIG_TEMPLATES[0][1]).read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
