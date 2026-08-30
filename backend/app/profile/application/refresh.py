"""Crash-safe profile outbox worker orchestration."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from backend.app.feedback.domain.public import ProfileRefreshReceipt
from backend.app.profile.ports.public import ProfileRefreshPort


ConnectionFactory = Callable[[], Awaitable[Any]]


async def _close(connection: Any) -> None:
    result = connection.close()
    if inspect.isawaitable(result):
        await result


class ProfileOutboxWorker:
    """Claim work, apply a deterministic snapshot, and mark it in one commit."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        refresh_port: ProfileRefreshPort,
        worker_id: str,
        formula_version: str = "profile-g2-v1",
        lease_seconds: int = 60,
        max_attempts: int = 3,
        allowed_outbox_ids: tuple[int, ...] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if allowed_outbox_ids is not None:
            normalized_ids = tuple(dict.fromkeys(int(item) for item in allowed_outbox_ids))
            if not normalized_ids or len(normalized_ids) > 100 or any(item <= 0 for item in normalized_ids):
                raise ValueError("allowed_outbox_ids must contain 1-100 unique positive ids")
            if len(normalized_ids) != len(allowed_outbox_ids):
                raise ValueError("allowed_outbox_ids must not contain duplicates")
        else:
            normalized_ids = None
        self._connection_factory = connection_factory
        self._refresh_port = refresh_port
        self._worker_id = worker_id
        self._formula_version = formula_version
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._allowed_outbox_ids = normalized_ids

    async def close(self) -> None:
        """Close the explicitly supplied pool; pending facts remain queued."""

        close = getattr(self._connection_factory, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def run_once(self, *, limit: int = 10) -> tuple[ProfileRefreshReceipt, ...]:
        claim_connection = await self._connection_factory()
        try:
            work = await self._refresh_port.claim_pending(
                claim_connection,
                worker_id=self._worker_id,
                limit=limit,
                lease_seconds=self._lease_seconds,
                max_attempts=self._max_attempts,
                allowed_outbox_ids=self._allowed_outbox_ids,
            )
            await claim_connection.commit()
        except BaseException:
            await claim_connection.rollback()
            raise
        finally:
            await _close(claim_connection)

        receipts: list[ProfileRefreshReceipt] = []
        for item in work:
            connection = await self._connection_factory()
            try:
                receipt = await self._refresh_port.apply_claim(
                    connection,
                    item,
                    formula_version=self._formula_version,
                )
                await self._refresh_port.mark_done(connection, outbox_id=int(item["outbox_id"]))
                await connection.commit()
                receipts.append(receipt)
            except BaseException as exc:
                await connection.rollback()
                failure_connection = await self._connection_factory()
                try:
                    attempts = int(item.get("attempts", self._max_attempts))
                    await self._refresh_port.mark_failed(
                        failure_connection,
                        outbox_id=int(item["outbox_id"]),
                        error_code=type(exc).__name__,
                        dead=attempts >= self._max_attempts,
                    )
                    await failure_connection.commit()
                except BaseException:
                    await failure_connection.rollback()
                    raise
                finally:
                    await _close(failure_connection)
            finally:
                await _close(connection)
        return tuple(receipts)


__all__ = ["ProfileOutboxWorker"]
