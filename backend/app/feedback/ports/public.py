"""Public storage boundary for exposure and feedback facts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.app.feedback.domain.public import (
    FeedbackCommand,
    FeedbackReceipt,
    ImpressionCommand,
    ImpressionReceipt,
)


class FeedbackStorePort(Protocol):
    """Validate recommendation ownership and append feedback-owned facts."""

    async def find_item(
        self,
        connection: object,
        *,
        recommendation_item_id: int,
        user_id: int,
    ) -> dict[str, object] | None: ...

    async def find_impression(
        self,
        connection: object,
        *,
        impression_uuid: UUID,
        user_id: int,
        recommendation_item_id: int,
    ) -> dict[str, object] | None: ...

    async def find_behavior_event(
        self,
        connection: object,
        *,
        event_uuid: UUID,
        user_id: int,
        recommendation_item_id: int,
    ) -> dict[str, object] | None: ...

    async def append_impression(
        self,
        connection: object,
        command: ImpressionCommand,
    ) -> ImpressionReceipt: ...

    async def append_feedback(
        self,
        connection: object,
        *,
        command: FeedbackCommand,
        resource_id: int,
        state: dict[str, object] | None,
        behavior_event_id: int,
    ) -> FeedbackReceipt: ...


__all__ = ["FeedbackStorePort"]
