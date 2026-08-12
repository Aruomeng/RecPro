from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch
import unittest

from scripts import verify_g4_real_llm_readonly as probe


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class G4RealLLMReadOnlyProbeTest(unittest.TestCase):
    def test_exact_confirmation_is_required_before_provider_construction(self) -> None:
        with patch.object(probe, "build_llm_provider") as build_provider:
            with self.assertRaises(ValueError):
                asyncio.run(
                    probe.execute(
                        run_id="g4-real-llm-test-001",
                        confirmation="NO",
                        compose_env_file=PROJECT_ROOT / ".env.compose",
                        secrets_file=PROJECT_ROOT / ".env.user-secrets",
                        llm_env_file=PROJECT_ROOT / ".env.host",
                        chroma_path=PROJECT_ROOT / "data" / "chroma",
                        chroma_site_packages=PROJECT_ROOT / "missing-site-packages",
                    )
                )
        build_provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
