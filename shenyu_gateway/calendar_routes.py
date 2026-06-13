from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request

from .calendar_service import CalendarService
from .schemas import CalendarGenerateRequest, CalendarPromptUpdate


@dataclass(frozen=True)
class CalendarRouteDeps:
    require_session_store: Callable[[], Any]
    calendar_service: Callable[[Optional[Request]], CalendarService]


def build_calendar_router(deps: CalendarRouteDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/calendar/prompts")
    async def calendar_prompts():
        service = deps.calendar_service(None)
        return await service.list_prompt_configs()

    @router.post("/api/calendar/prompts")
    async def calendar_save_prompt(body: CalendarPromptUpdate):
        service = deps.calendar_service(None)
        return await service.save_prompt_config(body)

    @router.post("/api/calendar/prompts/{prompt_id}/activate")
    async def calendar_activate_prompt(prompt_id: str):
        service = deps.calendar_service(None)
        return await service.activate_prompt_config(prompt_id)

    @router.get("/api/calendar/month")
    async def calendar_month(month: Optional[str] = None):
        # External contract: home-frontend renders the month grid from grid[].date/day/
        # in_month/has_day/has_week/day_page{id,title,summary,status}.
        service = deps.calendar_service(None)
        return await service.month_status(month)

    @router.get("/api/calendar/page/{page_id}")
    async def calendar_page(page_id: str):
        # External contract: home-frontend expands calendar memories using id/title/summary/content.
        service = deps.calendar_service(None)
        return await service.page_detail(page_id)

    @router.get("/api/calendar/preview-sources")
    async def calendar_preview_sources(
        period_type: str,
        period_key: Optional[str] = None,
        session_tag: Optional[str] = None,
    ):
        service = deps.calendar_service(None)
        return await service.preview_sources(period_type, period_key, session_tag=session_tag)

    @router.get("/api/calendar/send-preview")
    async def calendar_send_preview(
        period_type: str,
        period_key: Optional[str] = None,
        model: Optional[str] = None,
        session_tag: Optional[str] = None,
    ):
        service = deps.calendar_service(None)
        return await service.send_preview(period_type, period_key, model, session_tag=session_tag)

    @router.get("/api/calendar/context-snapshots")
    async def calendar_context_snapshots(limit: int = 8, session_tag: Optional[str] = None):
        deps.require_session_store()
        service = deps.calendar_service(None)
        snapshots = service._context_snapshots(limit=limit, session_tag=session_tag)
        return {
            "items": [
                {
                    "id": item.get("id"),
                    "session_tag": item.get("session_tag"),
                    "client_name": item.get("client_name"),
                    "created_at": item.get("created_at"),
                    "last_active_at": item.get("last_active_at"),
                    "message_count": item.get("message_count"),
                    "stored_message_count": item.get("stored_message_count"),
                    "latest_user_text": item.get("latest_user_text"),
                    "messages": item.get("messages") or [],
                }
                for item in snapshots
            ]
        }

    @router.post("/api/calendar/generate")
    async def calendar_generate(request: Request, body: CalendarGenerateRequest):
        service = deps.calendar_service(request)
        return await service.generate_page(body)

    return router
