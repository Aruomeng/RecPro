from __future__ import annotations

import unittest

from scripts.verify_data_plane_runtime import (
    parse_count_output,
    parse_service_state,
    validate_run_id,
)


class DataPlaneRuntimeTest(unittest.TestCase):
    def test_service_state_parser_accepts_empty_optional_columns(self) -> None:
        self.assertEqual(
            {
                "mysql": {"health": "healthy", "state": "running"},
                "neo4j": {"health": "", "state": "running"},
                "worker": {"health": "", "state": ""},
            },
            parse_service_state("mysql\thealthy\trunning\nneo4j\t\trunning\nworker"),
        )

    def test_count_parser_uses_last_numeric_line(self) -> None:
        self.assertEqual(40, parse_count_output("count(n)\n40\n"))
        self.assertEqual(0, parse_count_output("0\n"))
        with self.assertRaises(ValueError):
            parse_count_output("permission denied\n")

    def test_run_id_rejects_path_traversal(self) -> None:
        self.assertEqual("data-plane-001", validate_run_id("data-plane-001"))
        with self.assertRaises(ValueError):
            validate_run_id("../data-plane")


if __name__ == "__main__":
    unittest.main()
