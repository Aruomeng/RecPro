"""Read-only MySQL adapter for public library exploration."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable


ConnectionFactory = Callable[[], Awaitable[Any]]


class MySQLCatalogReader:
    """Execute bounded SELECT statements and always close via rollback."""

    def __init__(self, *, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    async def overview(self) -> dict[str, object]:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT COUNT(*), SUM(resource_type='BOOK'), SUM(resource_type='PAPER') FROM resource_catalog")
                totals = await cursor.fetchone()
                await cursor.execute("SELECT COUNT(*) FROM tag_dictionary WHERE status='ACTIVE'")
                tag_count = int((await cursor.fetchone())[0])
                await cursor.execute("SELECT availability_status, COUNT(*) FROM resource_catalog GROUP BY availability_status ORDER BY availability_status")
                availability = [{"name": str(name), "count": int(count)} for name, count in await cursor.fetchall()]
                await cursor.execute("SELECT COALESCE(category_code, '未分类'), COUNT(*) AS c FROM resource_catalog GROUP BY category_code ORDER BY c DESC LIMIT 10")
                categories = [{"name": str(name), "count": int(count)} for name, count in await cursor.fetchall()]
                await cursor.execute("SELECT FLOOR(publication_year/10)*10 AS decade, COUNT(*) FROM resource_catalog WHERE publication_year IS NOT NULL GROUP BY decade ORDER BY decade")
                decades = [{"year": int(year), "count": int(count)} for year, count in await cursor.fetchall()]
                await cursor.execute(
                    "SELECT t.name, COUNT(DISTINCT rt.resource_id) AS c FROM tag_dictionary t "
                    "JOIN resource_tag rt ON rt.tag_id=t.id WHERE t.status='ACTIVE' "
                    "GROUP BY t.id, t.name ORDER BY c DESC, t.name LIMIT 16"
                )
                topics = [{"name": str(name), "count": int(count)} for name, count in await cursor.fetchall()]
            return {
                "totals": {"resources": int(totals[0]), "books": int(totals[1] or 0), "papers": int(totals[2] or 0), "tags": tag_count},
                "availability": availability, "categories": categories, "publication_decades": decades, "popular_topics": topics,
            }
        finally:
            await connection.rollback()
            connection.close()

    async def resource(self, resource_id: int) -> dict[str, object]:
        if isinstance(resource_id, bool) or resource_id < 1:
            raise ValueError("resource id must be positive")
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT r.id, r.resource_type, r.external_id, r.title, r.authors_json, r.abstract_text, "
                    "r.keywords_json, r.category_code, r.publication_year, r.publisher_or_source, r.language, "
                    "r.difficulty_level, r.availability_status, b.isbn, b.call_number, b.location, b.borrowable_copies "
                    "FROM resource_catalog r LEFT JOIN resource_book_detail b ON b.resource_id = r.id WHERE r.id = %s",
                    (resource_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise LookupError("resource not found")
                await cursor.execute(
                    "SELECT t.name FROM resource_tag rt JOIN tag_dictionary t ON t.id = rt.tag_id "
                    "WHERE rt.resource_id = %s AND t.status = 'ACTIVE' ORDER BY rt.weight DESC, t.name LIMIT 20",
                    (resource_id,),
                )
                tags = [str(value[0]) for value in await cursor.fetchall()]
            return {
                "resource_id": int(row[0]), "resource_type": str(row[1]), "external_id": str(row[2]),
                "title": str(row[3]), "authors": self._json_list(row[4]), "abstract": str(row[5]) if row[5] else None,
                "keywords": self._json_list(row[6]), "category_code": str(row[7]) if row[7] else None,
                "publication_year": int(row[8]) if row[8] is not None else None,
                "publisher": str(row[9]) if row[9] else None, "language": str(row[10]) if row[10] else None,
                "difficulty_level": int(row[11]) if row[11] is not None else None,
                "availability_status": str(row[12]), "isbn": str(row[13]) if row[13] else None,
                "call_number": str(row[14]) if row[14] else None, "location": str(row[15]) if row[15] else None,
                "borrowable_copies": int(row[16] or 0), "tags": tags,
            }
        finally:
            await connection.rollback()
            connection.close()

    async def map_resource_ids(self, view: dict[str, object]) -> dict[str, object]:
        nodes = view.get("nodes")
        if not isinstance(nodes, list):
            return view
        external_ids = [str(node["id"]) for node in nodes if isinstance(node, dict) and node.get("type") == "Book"]
        if not external_ids:
            return view
        connection = await self._connection_factory()
        try:
            placeholders = ",".join(["%s"] * len(external_ids))
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT external_id, id FROM resource_catalog WHERE resource_type='BOOK' AND external_id IN ({placeholders})",  # noqa: S608 - placeholders only
                    tuple(external_ids),
                )
                mapping = {str(external_id): int(resource_id) for external_id, resource_id in await cursor.fetchall()}
            mapped = []
            for node in nodes:
                item = dict(node)
                item["resource_id"] = mapping.get(str(item.get("id")))
                mapped.append(item)
            return {**view, "nodes": mapped}
        finally:
            await connection.rollback()
            connection.close()

    @staticmethod
    def _json_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (bytes, bytearray)):
            value = value.decode()
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []
        return [str(item) for item in value] if isinstance(value, list) else []


__all__ = ["MySQLCatalogReader"]
