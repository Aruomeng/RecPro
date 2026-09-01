from __future__ import annotations

import unittest

from scripts.execute_current_synthetic_profile_demo_change_plan import _port


class CurrentSyntheticProfileDemoRecoveryTests(unittest.TestCase):
    def test_worker_port_normalizes_host_or_compose_environment_key(self) -> None:
        self.assertEqual(3306, _port({"RECPRO_MYSQL_PORT": "3306"}))
        self.assertEqual(13306, _port({"RECPRO_MYSQL_HOST_PORT": "13306", "RECPRO_MYSQL_PORT": "3306"}))


if __name__ == "__main__":
    unittest.main()
