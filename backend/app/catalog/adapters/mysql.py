"""Minimal async MySQL Catalog adapter with no ORM dependency."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncmy

from backend.app.catalog.domain.models import ResourceSummary, ResourceTagEvidence
from backend.app.catalog.ports.public import CatalogRepository, CatalogUnitOfWork


def _json_array(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


class MySQLCatalogRepository(CatalogRepository):
    """Read-only resource and tag queries bound to one active connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def list_resources(
        self,
        *,
        available_at: datetime | None = None,
        resource_type: str | None = None,
    ) -> tuple[ResourceSummary, ...]:
        predicates = ["availability_status <> 'REMOVED'"]
        parameters: list[object] = []
        if available_at is not None:
            predicates.append("available_from <= %s")
            parameters.append(available_at)
        if resource_type is not None:
            predicates.append("resource_type = %s")
            parameters.append(resource_type)
        query = (
            "SELECT id, resource_type, external_id, title, authors_json, abstract_text, "
            "keywords_json, category_code, publication_year, availability_status, "
            "available_from, access_url, metadata_quality, is_classic, metadata_version, "
            "language, difficulty_level FROM resource_catalog WHERE "
            + " AND ".join(predicates)
            + " ORDER BY id"
        )
        async with self._connection.cursor() as cursor:
            await cursor.execute(query, tuple(parameters))
            rows = await cursor.fetchall()
        return tuple(
            ResourceSummary(
                id=int(row[0]),
                resource_type=str(row[1]),
                external_id=str(row[2]),
                title=str(row[3]),
                authors=_json_array(row[4]),
                abstract_text=str(row[5]) if row[5] is not None else None,
                keywords=_json_array(row[6]),
                category_code=str(row[7]) if row[7] is not None else None,
                publication_year=int(row[8]) if row[8] is not None else None,
                availability_status=str(row[9]),
                available_from=row[10],
                access_url=str(row[11]) if row[11] is not None else None,
                metadata_quality=float(row[12]),
                is_classic=bool(row[13]),
                metadata_version=int(row[14]),
                language=str(row[15]) if row[15] is not None else None,
                difficulty_level=int(row[16]) if row[16] is not None else None,
            )
            for row in rows
        )

    async def list_resource_tags(
        self,
        *,
        resource_ids: tuple[int, ...],
    ) -> tuple[ResourceTagEvidence, ...]:
        if not resource_ids:
            return ()
        placeholders = ",".join("%s" for _ in resource_ids)
        query = (
            "SELECT rt.resource_id, rt.tag_id, td.normalized_name, rt.weight, "
            "rt.confidence, rt.source FROM resource_tag rt "
            "JOIN tag_dictionary td ON td.id = rt.tag_id "
            f"WHERE rt.resource_id IN ({placeholders}) "
            "ORDER BY rt.resource_id, rt.tag_id, rt.source"
        )
        async with self._connection.cursor() as cursor:
            await cursor.execute(query, resource_ids)
            rows = await cursor.fetchall()
        return tuple(
            ResourceTagEvidence(
                resource_id=int(row[0]),
                tag_id=int(row[1]),
                normalized_name=str(row[2]),
                weight=float(row[3]),
                confidence=float(row[4]),
                source=str(row[5]),
            )
            for row in rows
        )


class MySQLCatalogUnitOfWork(CatalogUnitOfWork):
    """Async context manager that owns one runtime MySQL connection."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        connect_timeout: float = 3.0,
    ) -> None:
        self._connection_options = {
            "host": host,
            "port": port,
            "db": database,
            "user": user,
            "password": password,
            "connect_timeout": connect_timeout,
            "read_timeout": connect_timeout,
            "charset": "utf8mb4",
            "autocommit": False,
        }
        self._connection: Any | None = None
        self.catalog: MySQLCatalogRepository | None = None

    async def __aenter__(self) -> "MySQLCatalogUnitOfWork":
        self._connection = await asyncmy.connect(**self._connection_options)
        self.catalog = MySQLCatalogRepository(self._connection)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._connection is None:
            return
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()
        self._connection.close()
        self._connection = None
        self.catalog = None

    async def commit(self) -> None:
        if self._connection is not None:
            await self._connection.commit()

    async def rollback(self) -> None:
        if self._connection is not None:
            await self._connection.rollback()
