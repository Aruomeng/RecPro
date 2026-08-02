from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = ROOT / "frontend/src"
IMPORT_PATTERN = re.compile(r"from\s+[\"'](?P<target>[^\"']+)[\"']")


class FrontendArchitectureContractTests(unittest.TestCase):
    def test_domain_has_no_adapter_or_presentation_dependency(self) -> None:
        for path in (FRONTEND_SRC / "domain").glob("*.ts"):
            imports = IMPORT_PATTERN.findall(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertFalse(
                    any("/api/" in target or "/presentation/" in target for target in imports)
                )

    def test_presentation_and_components_do_not_depend_on_api_adapter(self) -> None:
        paths = [
            *(FRONTEND_SRC / "presentation").glob("*.ts"),
            *(FRONTEND_SRC / "components").glob("*.vue"),
        ]
        for path in paths:
            imports = IMPORT_PATTERN.findall(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertFalse(any("/api/" in target for target in imports))


if __name__ == "__main__":
    unittest.main()
