from __future__ import annotations

from types import SimpleNamespace
import unittest

from fastapi.testclient import TestClient

import backend.app.platform.mysql as mysql_module
from backend.app.main import create_app
from backend.app.platform.lifecycle import RuntimeResourceRegistry
from backend.app.platform.mysql import MySQLConnectionPool
from backend.app.config import AppSettings


class _FakePool:
    def __init__(self) -> None:
        self.size = 0
        self.freesize = 0
        self.released: list[object] = []
        self.closed = False

    async def acquire(self) -> object:
        self.size += 1
        return SimpleNamespace()

    def release(self, connection: object) -> None:
        self.released.append(connection)
        self.freesize = len(self.released)

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class RuntimeLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_pool_snapshot_tracks_leases_without_connection_options(self) -> None:
        fake_pool = _FakePool()

        async def create_pool(**_: object) -> _FakePool:
            return fake_pool

        original = mysql_module.asyncmy.create_pool
        mysql_module.asyncmy.create_pool = create_pool
        try:
            pool = MySQLConnectionPool(
                connection_options={"host": "no-network", "password": "secret"},
                min_size=0,
                max_size=2,
                pool_recycle_seconds=60,
                acquire_timeout_seconds=1,
            )
            lease = await pool()
            active = pool.snapshot()
            self.assertEqual(1, active.acquire_count)
            self.assertEqual(1, active.active_leases)
            self.assertNotIn("password", active.as_dict())
            lease.close()
            self.assertEqual(1, pool.snapshot().release_count)
            await pool.close()
            self.assertTrue(pool.snapshot().closed)
            self.assertTrue(fake_pool.closed)
        finally:
            mysql_module.asyncmy.create_pool = original

    async def test_registry_deduplicates_and_closes_in_reverse_order(self) -> None:
        closed: list[str] = []

        class Resource:
            def __init__(self, name: str) -> None:
                self.name = name

            async def close(self) -> None:
                closed.append(self.name)

            def snapshot(self) -> dict[str, object]:
                return {"name": self.name}

        first = Resource("first")
        second = Resource("second")
        registry = RuntimeResourceRegistry((first, second, first))
        self.assertEqual(2, len(registry.resources))
        self.assertEqual(2, len(registry.snapshots()))
        await registry.close()
        await registry.close()
        self.assertEqual(["second", "first"], closed)

    def test_fastapi_lifespan_closes_only_explicit_resources(self) -> None:
        closed: list[str] = []

        class Resource:
            async def close(self) -> None:
                closed.append("resource")

        app = create_app(
            settings=AppSettings(
                app_env="demo",
                mysql_password="isolated-test-password",
            ),
            managed_resources=(Resource(),),
        )
        with TestClient(app) as client:
            self.assertEqual(200, client.get("/api/v1/health/live").status_code)
            self.assertFalse(app.state.runtime_resources.closed)
        self.assertEqual(["resource"], closed)
        self.assertTrue(app.state.runtime_resources.closed)


if __name__ == "__main__":
    unittest.main()
