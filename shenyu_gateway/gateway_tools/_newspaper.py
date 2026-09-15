from __future__ import annotations

from typing import Any, Optional

from shenyu_gateway.newspaper_basket import read_newspaper_basket


class NewspaperToolsMixin:
    async def newspaper_basket(
        self,
        *,
        date: Optional[str] = None,
        query: Optional[str] = None,
        limit: Any = 30,
    ) -> dict:
        """Read the old-newspaper basket from daily chat.

        Same read the Room's `room_newspaper_basket` performs, deliberately
        without the `room_trace` write: that table answers "was he in the
        room", and `last_room_visit_at()` takes its newest row regardless of
        action, so recording a daily read here would damp the room charge and
        hide doors on his next actual visit.
        """
        # Argument coercion stays inside read_newspaper_basket so the daily and
        # Room entries cannot drift on the same params.
        return read_newspaper_basket(
            self.store,
            {"date": date, "query": query, "limit": limit},
        )
