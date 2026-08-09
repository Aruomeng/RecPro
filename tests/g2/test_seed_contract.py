from __future__ import annotations

import json
import unittest

from scripts.seed_g2 import DEFAULT_SEED, validate_seed


class G2SeedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.seed = validate_seed(json.loads(DEFAULT_SEED.read_text(encoding="utf-8")))

    def test_seed_is_synthetic_and_versioned(self) -> None:
        self.assertTrue(str(self.seed["seed_version"]).startswith("g2-"))
        self.assertEqual("synthetic", self.seed["source"]["kind"])
        self.assertIn("license", self.seed["source"])

    def test_seed_has_resources_tags_profiles_and_behaviors(self) -> None:
        self.assertGreaterEqual(len(self.seed["resources"]), 6)
        self.assertGreaterEqual(len(self.seed["tags"]), 6)
        self.assertGreaterEqual(len(self.seed["declared_profiles"]), 2)
        self.assertGreaterEqual(len(self.seed["behaviors"]), 8)
        external_ids = {item["external_id"] for item in self.seed["resources"]}
        for event in self.seed["behaviors"]:
            self.assertIn(event["resource_external_id"], external_ids)

    def test_seed_topic_negative_is_explicit(self) -> None:
        topic_negatives = [
            event
            for event in self.seed["behaviors"]
            if event.get("reason_code") == "TOPIC_NOT_INTERESTED"
        ]
        self.assertEqual(1, len(topic_negatives))


if __name__ == "__main__":
    unittest.main()
