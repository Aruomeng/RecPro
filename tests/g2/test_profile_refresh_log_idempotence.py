from __future__ import annotations

from pathlib import Path
import unittest


class ProfileRefreshLogIdempotenceTests(unittest.TestCase):
    def test_replay_log_uses_guarded_insert_not_warning_prone_insert_ignore(self) -> None:
        source = (Path(__file__).resolve().parents[2] / "backend/app/profile/adapters/refresh_mysql.py").read_text(encoding="utf-8")
        self.assertIn("WHERE NOT EXISTS (SELECT 1 FROM profile_change_log", source)
        self.assertNotIn('"INSERT IGNORE INTO profile_change_log', source)


if __name__ == "__main__":
    unittest.main()
