"""Fail-closed worker entrypoint with an explicit Profile Outbox opt-in."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import asyncmy

from backend.app.config import (
    CONFIG_BUNDLE_SCHEMA_PATH,
    CONFIG_BUNDLE_SCHEMA_SHA256,
    load_configuration,
)
from backend.app.composition import build_profile_outbox_worker
from backend.app.logging import configure_logging, get_logger
from backend.app.observability.adapters import JsonConfigBundleReadinessProbe
from backend.app.observability.domain import ComponentStatus


ConnectionFactory = Callable[[], Awaitable[Any]]


def _mysql_connection_factory(settings: Any) -> ConnectionFactory:
    """Create controlled-write MySQL connections for the explicit worker mode."""

    options = {
        "host": settings.mysql_host,
        "port": settings.mysql_port,
        "db": settings.mysql_database,
        "user": settings.mysql_user,
        "password": settings.mysql_password.get_secret_value(),
        "connect_timeout": settings.mysql_connect_timeout_seconds,
        "read_timeout": max(settings.mysql_connect_timeout_seconds, 3.0),
        "charset": "utf8mb4",
        "autocommit": False,
    }

    async def connect() -> Any:
        return await asyncmy.connect(**options)

    return connect


async def _wait_for_stop(stop_event: asyncio.Event | None) -> None:
    if stop_event is None:
        await asyncio.Event().wait()
    else:
        await stop_event.wait()


async def run_worker(
    *,
    stop_event: asyncio.Event | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> None:
    """Validate runtime inputs, then run only the explicitly selected worker.

    The default Compose worker remains a healthy, inert process.  Setting both
    ``RECPRO_WORKER_ENABLED=true`` and
    ``RECPRO_WORKER_MODE=profile_outbox`` is required before any MySQL claim or
    controlled projection write can occur.  ``stop_event`` and the injectable
    factory keep the loop deterministic for process-level tests without
    connecting to a database.
    """

    configuration = load_configuration()
    configure_logging(configuration.settings.log_level)
    logger = get_logger(__name__)
    if not configuration.is_valid:
        logger.error(
            "worker_configuration_invalid",
            error_code=configuration.error_code,
        )
        raise RuntimeError("worker configuration is invalid")
    bundle_probe = JsonConfigBundleReadinessProbe(
        path=configuration.settings.config_bundle_path,
        schema_path=CONFIG_BUNDLE_SCHEMA_PATH,
        expected_sha256=configuration.settings.config_bundle_sha256,
        expected_schema_sha256=CONFIG_BUNDLE_SCHEMA_SHA256,
        expected_version=configuration.settings.config_bundle_version,
    )
    bundle_readiness = await bundle_probe.check()
    if bundle_readiness.status is not ComponentStatus.UP:
        logger.error(
            "worker_config_bundle_invalid",
            error_code=bundle_readiness.error_code,
        )
        raise RuntimeError("worker config Bundle is invalid")

    settings = configuration.settings
    if not settings.worker_enabled:
        logger.info(
            "worker_disabled",
            capability="NONE",
            worker_mode=settings.worker_mode,
            config_bundle_version=settings.config_bundle_version,
        )
        await _wait_for_stop(stop_event)
        return

    if settings.worker_mode != "profile_outbox":
        # This is also enforced by AppSettings, but retaining the boundary at
        # the process entrypoint prevents a future config construction shortcut
        # from silently acquiring a different write capability.
        raise RuntimeError("unsupported worker mode")

    active_connection_factory = connection_factory or _mysql_connection_factory(settings)
    worker = build_profile_outbox_worker(
        settings,
        connection_factory=active_connection_factory,
        worker_id=settings.worker_id,
        formula_version=settings.worker_formula_version,
        lease_seconds=settings.worker_lease_seconds,
        max_attempts=settings.worker_max_attempts,
    )
    logger.info(
        "worker_started",
        capability="PROFILE_OUTBOX",
        worker_id=settings.worker_id,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
        batch_limit=settings.worker_batch_limit,
        lease_seconds=settings.worker_lease_seconds,
        max_attempts=settings.worker_max_attempts,
        formula_version=settings.worker_formula_version,
        config_bundle_version=settings.config_bundle_version,
    )
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            receipts = await worker.run_once(limit=settings.worker_batch_limit)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker_poll_failed", worker_id=settings.worker_id)
            raise
        logger.info(
            "worker_poll_completed",
            worker_id=settings.worker_id,
            receipt_count=len(receipts),
        )
        if receipts:
            # Drain a bounded batch before sleeping so a backlog does not wait
            # an entire interval between each batch.
            await asyncio.sleep(0)
            continue
        if stop_event is None:
            await asyncio.sleep(settings.worker_poll_interval_seconds)
            continue
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.worker_poll_interval_seconds
            )
        except asyncio.TimeoutError:
            pass


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
