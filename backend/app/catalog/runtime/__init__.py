"""Catalog-side research runtime composition helpers."""

from backend.app.catalog.runtime.g4_ports import (
    G4ReadOnlyRuntime,
    build_g4_readonly_runtime,
)

__all__ = ["G4ReadOnlyRuntime", "build_g4_readonly_runtime"]
