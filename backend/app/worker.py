"""Safe G1 worker process skeleton; it performs no persistence operations."""

from __future__ import annotations

import asyncio

from backend.app.config import (
    CONFIG_BUNDLE_SCHEMA_PATH,
    CONFIG_BUNDLE_SCHEMA_SHA256,
    load_configuration,
)
from backend.app.logging import configure_logging, get_logger
from backend.app.observability.adapters import JsonConfigBundleReadinessProbe
from backend.app.observability.domain import ComponentStatus


async def run_worker() -> None:
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
    logger.info(
        "worker_skeleton_started",
        capability="NONE",
        config_bundle_version=configuration.settings.config_bundle_version,
    )
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
