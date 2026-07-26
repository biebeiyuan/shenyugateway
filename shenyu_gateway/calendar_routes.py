from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import APIRouter

from .calendar_service import CalendarService


@dataclass(frozen=True)
class CalendarRouteDeps:
    calendar_service: Callable[[], CalendarService]


def build_calendar_router(deps: CalendarRouteDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/calendar/month")
    async def calendar_month(month: Optional[str] = None):
        # External contract: home-frontend renders the month grid from grid[].date/day/
        # in_month/has_day/has_week/day_page{id,title,summary,status}.
        service = deps.calendar_service()
        return await service.month_status(month)

    @router.get("/api/calendar/page/{page_id}")
    async def calendar_page(page_id: str):
        # External contract: home-frontend expands calendar memories using id/title/summary/content.
        service = deps.calendar_service()
        return await service.page_detail(page_id)

    return router
