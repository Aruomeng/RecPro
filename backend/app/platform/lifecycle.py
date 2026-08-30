"""Explicit asynchronous resource lifecycle for composed application roots.

The domain and transport layers do not own process resources.  A reviewed
composition root may pass pools, clients, workers, or application services
that expose ``close``/``aclose`` into :class:`RuntimeResourceRegistry`.
The registry closes them in reverse construction order, de-duplicates shared
objects, and keeps a small non-sensitive snapshot seam for operators/tests.

No resource is discovered implicitly.  This is deliberate: injected fakes and
resources owned by another process must not be closed merely because they are
reachable from a FastAPI dependency graph.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any


async def _invoke_close(resource: object) -> bool:
    """Invoke one explicitly supplied close hook, if it has one."""

    callback = getattr(resource, "aclose", None)
    if not callable(callback):
        callback = getattr(resource, "close", None)
    if not callable(callback):
        return False
    result = callback()
    if inspect.isawaitable(result):
        await result
    return True


def _public_snapshot(resource: object) -> dict[str, object] | None:
    """Return a safe, JSON-shaped snapshot without inspecting credentials."""

    for method_name in ("snapshot", "runtime_metrics"):
        method = getattr(resource, method_name, None)
        if not callable(method):
            continue
        try:
            value = method()
        except Exception:
            # Metrics are diagnostic only; a broken optional probe must not
            # make the application lifecycle or health endpoint fail.
            continue
        if is_dataclass(value):
            value = asdict(value)
        if isinstance(value, dict):
            return {
                "resource_type": type(resource).__name__,
                "metrics": dict(value),
            }
    return None


class RuntimeResourceCloseError(RuntimeError):
    """Raised after all resources were attempted but one or more failed."""

    def __init__(self, failures: tuple[tuple[str, str], ...]) -> None:
        self.failures = failures
        labels = ", ".join(f"{name}: {error}" for name, error in failures)
        super().__init__(f"runtime resource shutdown failed ({labels})")


class RuntimeResourceRegistry:
    """Own only resources explicitly handed to a composition root.

    A registry is intentionally small and framework-neutral.  It can be
    attached to ``application.state`` and used by a FastAPI lifespan, a CLI
    runner, or a worker entrypoint.  Closing is idempotent and attempts every
    resource so one faulty optional dependency does not strand later pools.
    """

    def __init__(self, resources: Iterable[object] = ()) -> None:
        unique: list[object] = []
        seen: set[int] = set()
        for resource in resources:
            if resource is None or id(resource) in seen:
                continue
            seen.add(id(resource))
            unique.append(resource)
        self._resources = tuple(unique)
        self._closed = False

    @property
    def resources(self) -> tuple[object, ...]:
        return self._resources

    @property
    def closed(self) -> bool:
        return self._closed

    def snapshots(self) -> tuple[dict[str, object], ...]:
        """Read non-sensitive metrics from explicitly registered resources."""

        values: list[dict[str, object]] = []
        for resource in self._resources:
            snapshot = _public_snapshot(resource)
            if snapshot is not None:
                values.append(snapshot)
        return tuple(values)

    def diagnostics_snapshot(self) -> dict[str, object]:
        """Return the lifecycle state plus bounded resource snapshots.

        The composition root may hand this method to a read-only diagnostics
        adapter.  It contains no connection options or credentials; the HTTP
        adapter applies its own public metric allowlist before serialization.
        """

        return {
            "registry_closed": self._closed,
            "resources": self.snapshots(),
        }

    async def close(self) -> None:
        """Close all resources in reverse order; safe to call repeatedly."""

        if self._closed:
            return
        failures: list[tuple[str, str]] = []
        for resource in reversed(self._resources):
            try:
                await _invoke_close(resource)
            except Exception as exc:  # keep attempting the remaining resources
                failures.append((type(resource).__name__, type(exc).__name__))
        self._closed = True
        if failures:
            raise RuntimeResourceCloseError(tuple(failures))

    async def __aenter__(self) -> "RuntimeResourceRegistry":
        if self._closed:
            raise RuntimeError("runtime resource registry is closed")
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()


__all__ = ["RuntimeResourceCloseError", "RuntimeResourceRegistry"]
