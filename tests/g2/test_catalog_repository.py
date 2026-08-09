from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime

from backend.app.catalog.adapters.mysql import MySQLCatalogRepository


class FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.query = ""
        self.parameters: tuple[object, ...] = ()

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, query: str, parameters: tuple[object, ...] = ()) -> None:
        self.query = query
        self.parameters = parameters

    async def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.cursor_instance = FakeCursor(rows)

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


class CatalogRepositoryTests(unittest.TestCase):
    def test_resource_rows_are_mapped_without_sql_in_domain(self) -> None:
        row = (
            1,
            "BOOK",
            "book-1",
            "示例书",
            json.dumps(["作者"]),
            "摘要",
            json.dumps(["智慧图书馆"]),
            "G25",
            2025,
            "AVAILABLE_BORROW",
            datetime(2025, 1, 1),
            None,
            0.9,
            0,
            1,
            "zh-CN",
            2,
        )
        connection = FakeConnection([row])
        repository = MySQLCatalogRepository(connection)
        resources = asyncio.run(repository.list_resources(available_at=datetime(2025, 2, 1), resource_type="BOOK"))
        self.assertEqual(("示例书",), tuple(item.title for item in resources))
        self.assertIn("availability_status <> 'REMOVED'", connection.cursor_instance.query)
        self.assertEqual((datetime(2025, 2, 1), "BOOK"), connection.cursor_instance.parameters)
        self.assertNotIn("DELETE", connection.cursor_instance.query.upper())


if __name__ == "__main__":
    unittest.main()
