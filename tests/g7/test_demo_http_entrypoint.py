from __future__ import annotations

import importlib
import os
import sys
import unittest
from unittest.mock import patch


class DemoHttpEntrypointTests(unittest.TestCase):
    def tearDown(self) -> None:
        sys.modules.pop("backend.app.demo_main", None)

    def test_entrypoint_is_fail_closed_without_explicit_switch(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RECPRO_DEMO_HTTP_ENABLED": "false",
                "RECPRO_APP_ENV": "demo",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "RECPRO_DEMO_HTTP_ENABLED"):
                importlib.import_module("backend.app.demo_main")

    def test_entrypoint_is_explicitly_composed_when_enabled(self) -> None:
        environment = {
            "RECPRO_DEMO_HTTP_ENABLED": "true",
            "RECPRO_APP_ENV": "demo",
            "RECPRO_MYSQL_PASSWORD": "demo-entrypoint-test-password",
            "RECPRO_MYSQL_HOST": "127.0.0.1",
            "RECPRO_MYSQL_PORT": "62306",
            "RECPRO_MYSQL_DATABASE": "recpro",
            "RECPRO_MYSQL_USER": "recpro_runtime",
            "RECPRO_PERSISTENCE_PROBE_ID": "recpro-g2-tianyuhang-20260809a",
            "RECPRO_CONFIG_BUNDLE_SHA256": "220b0fb30f38fef7ca148c43b1f2751715c7df7ecf7d47e7ddfce7ff2847a5c6",
        }
        with patch.dict(os.environ, environment, clear=False):
            module = importlib.import_module("backend.app.demo_main")
        paths = set(module.app.openapi()["paths"])
        self.assertIn("/api/v1/health/ready", paths)
        self.assertIn("/api/v1/recommendation-tasks", paths)


if __name__ == "__main__":
    unittest.main()
