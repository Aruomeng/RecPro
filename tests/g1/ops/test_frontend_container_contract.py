from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "frontend/Dockerfile"
NGINX_CONFIG = ROOT / "frontend/nginx/nginx.conf"
NGINX_SITE = ROOT / "frontend/nginx/default.conf"
PACKAGE_JSON = ROOT / "frontend/package.json"


class FrontendContainerContractTests(unittest.TestCase):
    def test_both_base_images_are_tagged_and_digest_pinned(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
        self.assertEqual(2, len(from_lines))
        for line in from_lines:
            with self.subTest(line=line):
                self.assertRegex(line, re.compile(r":.+@sha256:[0-9a-f]{64}(?: AS \w+)?$"))
                self.assertNotIn(":" + "latest", line.lower())

    def test_runtime_is_non_root_and_uses_only_the_selected_build_run(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("RECPRO_BUILD_RUN_ID=container-image", dockerfile)
        self.assertIn("/workspace/dist/container-image", dockerfile)
        self.assertIn("USER nginx", dockerfile)
        self.assertIn("ENTRYPOINT []", dockerfile)
        self.assertIn("/etc/nginx/conf.d/default.conf", dockerfile)
        nginx_config = NGINX_CONFIG.read_text(encoding="utf-8")
        self.assertIn("pid /tmp/nginx.pid;", nginx_config)
        self.assertIn("proxy_temp_path /tmp/proxy_temp;", nginx_config)

    def test_local_development_server_is_loopback_only(self) -> None:
        package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
        self.assertEqual("vite --host 127.0.0.1", package["scripts"]["dev"])
        self.assertEqual(
            "^20.19.0 || ^22.13.0 || >=24.0.0",
            package["engines"]["node"],
        )

    def test_missing_production_assets_never_fall_back_to_html(self) -> None:
        site = NGINX_SITE.read_text(encoding="utf-8")
        self.assertRegex(
            site,
            re.compile(r"location /assets/\s*\{\s*try_files \$uri =404;\s*\}"),
        )


if __name__ == "__main__":
    unittest.main()
