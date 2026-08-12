from __future__ import annotations

import unittest

from backend.app.feedback.domain.public import is_valid_exposure


class ExposureBoundaryTests(unittest.TestCase):
    def test_exposure_threshold_boundaries_are_closed(self) -> None:
        self.assertFalse(is_valid_exposure(visible_ms=999, max_visible_ratio=0.8))
        self.assertFalse(is_valid_exposure(visible_ms=1000, max_visible_ratio=0.49))
        self.assertTrue(is_valid_exposure(visible_ms=1000, max_visible_ratio=0.5))
        self.assertTrue(is_valid_exposure(visible_ms=1500, max_visible_ratio=0.8))


if __name__ == "__main__":
    unittest.main()
