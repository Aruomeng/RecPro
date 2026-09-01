from __future__ import annotations

import unittest

from scripts.verify_g7_mysql_http_readonly import build_settings


class MySqlHttpPortCompatibilityTests(unittest.TestCase):
    def test_host_runtime_port_falls_back_to_compose_port_key(self) -> None:
        values = {
            "RECPRO_CONFIG_BUNDLE_PATH": "config/bundles/recommendation-v1.json",
            "RECPRO_CONFIG_BUNDLE_SHA256": "0" * 64,
            "RECPRO_CONFIG_BUNDLE_VERSION": "test-v1",
            "RECPRO_MYSQL_PORT": "3307",
            "RECPRO_MYSQL_DATABASE": "recpro",
            "RECPRO_MYSQL_USER": "reader",
            "RECPRO_MYSQL_PASSWORD": "SyntheticPassword123",
            "RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS": "1",
            "RECPRO_PERSISTENCE_PROBE_ID": "probe",
        }
        self.assertEqual(3307, build_settings(values).mysql_port)


if __name__ == "__main__":
    unittest.main()
