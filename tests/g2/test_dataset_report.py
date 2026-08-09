from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.build_g2_dataset_report import build_reports
from scripts.seed_g2 import DEFAULT_SEED, validate_seed


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "contracts/data/g2/dataset_manifest.json"
QUALITY = ROOT / "contracts/data/g2/data-quality-report-v1.json"


class G2DatasetReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.seed_bytes = DEFAULT_SEED.read_bytes()
        cls.seed = validate_seed(json.loads(cls.seed_bytes.decode("utf-8")))

    def test_checked_in_manifest_and_quality_report_match_fixture(self) -> None:
        manifest, quality = build_reports(self.seed, seed_path=DEFAULT_SEED, seed_bytes=self.seed_bytes)
        self.assertEqual(manifest, json.loads(MANIFEST.read_text(encoding="utf-8")))
        self.assertEqual(quality, json.loads(QUALITY.read_text(encoding="utf-8")))
        self.assertEqual("PASS", quality["status"])
        self.assertEqual(0, quality["issue_count"])

    def test_report_rejects_duplicate_behavior_identity(self) -> None:
        mutated = json.loads(json.dumps(self.seed))
        mutated["behaviors"][1]["event_uuid"] = mutated["behaviors"][0]["event_uuid"]
        _, quality = build_reports(mutated, seed_path=DEFAULT_SEED, seed_bytes=self.seed_bytes)
        self.assertEqual("FAIL", quality["status"])
        self.assertFalse(quality["checks"]["behavior_event_uuids_unique"])


if __name__ == "__main__":
    unittest.main()
