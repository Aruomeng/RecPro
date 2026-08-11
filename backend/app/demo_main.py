"""Explicit local MySQL-backed HTTP entrypoint for the recommendation demo.

The repository's module-level ``backend.app.main:app`` remains health-only.
This module is intentionally a separate opt-in entrypoint: it refuses to
construct a business API unless the caller sets both the demo environment and
the explicit ``RECPRO_DEMO_HTTP_ENABLED=true`` switch.
"""

from __future__ import annotations

import os

from backend.app.composition import build_demo_mysql_http_app
from backend.app.config import load_configuration


def create_demo_app():
    if os.environ.get("RECPRO_DEMO_HTTP_ENABLED", "").lower() != "true":
        raise RuntimeError(
            "demo HTTP entrypoint requires RECPRO_DEMO_HTTP_ENABLED=true"
        )
    state = load_configuration()
    if not state.is_valid:
        raise RuntimeError(
            f"demo HTTP entrypoint rejected invalid configuration: {state.error_code}"
        )
    if state.settings.app_env != "demo":
        raise RuntimeError("demo HTTP entrypoint requires RECPRO_APP_ENV=demo")
    return build_demo_mysql_http_app(state.settings)


app = create_demo_app()
