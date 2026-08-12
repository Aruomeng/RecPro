from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.app.config import AppSettings, ConfigurationState
from backend.app.worker import run_worker


class _OnePollWorker:
    def __init__(self, stop_event: asyncio.Event) -> None:
        self.stop_event = stop_event

    async def run_once(self, *, limit: int):
        self.stop_event.set()
        return ()


class WorkerEntrypointTests(unittest.TestCase):
    def _state(self, **overrides: object) -> ConfigurationState:
        settings = AppSettings(
            mysql_password="isolated-test-password",
            app_env="test",
            **overrides,
        )
        return ConfigurationState(settings=settings, is_valid=True)

    def test_default_worker_waits_without_building_a_database_connection(self) -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        connection_factory = AsyncMock()
        with patch(
            "backend.app.worker.load_configuration",
            return_value=self._state(),
        ), patch("backend.app.worker.configure_logging"), patch(
            "backend.app.worker._mysql_connection_factory",
            return_value=connection_factory,
        ), patch("backend.app.worker.build_profile_outbox_worker") as builder:
            asyncio.run(run_worker(stop_event=stop_event))

        builder.assert_not_called()
        connection_factory.assert_not_awaited()

    def test_explicit_profile_mode_runs_a_bounded_poll_loop(self) -> None:
        stop_event = asyncio.Event()
        connection_factory = AsyncMock()
        fake_worker = _OnePollWorker(stop_event)
        with patch(
            "backend.app.worker.load_configuration",
            return_value=self._state(
                worker_enabled=True,
                worker_mode="profile_outbox",
                worker_id="test-profile-worker",
                worker_batch_limit=4,
            ),
        ), patch("backend.app.worker.configure_logging"), patch(
            "backend.app.worker.build_profile_outbox_worker",
            return_value=fake_worker,
        ) as builder:
            asyncio.run(
                run_worker(
                    stop_event=stop_event,
                    connection_factory=connection_factory,
                )
            )

        builder.assert_called_once()
        self.assertEqual(4, builder.call_args.args[0].worker_batch_limit)
        connection_factory.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
