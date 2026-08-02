from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class G1MakefileContractTests(unittest.TestCase):
    def test_unified_python_discovery_does_not_shadow_backend_package(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn(
            "unittest discover -s tests/g1 -t tests -p 'test_*.py'",
            makefile,
        )


if __name__ == "__main__":
    unittest.main()
