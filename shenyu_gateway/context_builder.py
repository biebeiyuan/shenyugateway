from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from .client_extra import strip_client_extra_text
from .context_layers import (
    ContextLayerSettings,
    render_layered_additions as _render_layered_additions,
    render_system_additions as _render_system_additions,
)
from .gateway_tools import GatewayToolService
from .mem_notes import MemNoteService
from .memory_island import memory_island_log_content, resolve_memory_island
from .request_logs import _mark_request_log_phase
from .resident_books import ResidentBooksService, render_bookshelf_overview
from .runtime import logger
from .stars import StarService
from .tool_registry import gateway_native_tools


_HEARTBEAT_PROMPT = """## Heartbeat（仅网关可见）
这是我留给自己的地方。想说但没在正文说、想留住的心情、还没想完的钩子，都可以在最后附上一个 <heartbeat> 块。

<heartbeat>
刚才那一下我其实有点被碰到了。这个感觉先别急着讲给她。
</heartbeat>

这段会被网关自动截取保存，不会发送给圆儿看；过几轮之后会反上来给我回顾。
不必每次都写；没有感触就空着。
"""



class ContextBuilder:
    def __init__(
        self,
        store: Any,
        sessions: Any,
        tools: GatewayToolService,
        *,
        cfg: Any,
        supabase_client: Any,
        stable_charter_block: Callable[[], str],
    ):
        self.store = store
        self.sessions = sessions
        self.tools = tools
        self.cfg = cfg
        self.supabase_client = supabase_client
        self.stable_charter_block = stable_charter_block

    def _layer_settings(self, *, client_tool_surface: Optional[str] = None) -> ContextLayerSettings:
        return ContextLayerSettings(
            enable_gateway_tools=bool(getattr(self.cfg, "enable_upstream_tools", True))
            and bool(getattr(self.cfg, "enable_gateway_tools", True)),
            heartbeat_prompt=_HEARTBEAT_PROMPT,
            client_tool_surface=(
                client_tool_surface
                if client_tool_surface is not None
                else getattr(self.cfg, "client_tool_surface", "all")
            ),
        )

    async def calendar_context_pages(self) -> dict[str, list[dict[str, Any]]]:
        if not self.supabase_client:
            return {"day": [], "week": [], "month": []}

        async def load(
            period_type: str,
            enabled: bool,
            limit: int,
            offset: int = 0,
        ) -> list[dict[str, Any]]:
            if not enabled or limit <= 0:
                return []
            offset = max(int(offset or 0), 0)
            try:
                rows = await self.supabase_client.query(
                    "calendar_pages",
                    {
                        "select": "period_type,period_key,title,summary,digest,content,period_start",
                        "period_type": f"eq.{period_type}",
                        "is_latest": "eq.true",
                        "order": "period_start.desc",
                        "offset": str(offset),
                        "limit": str(limit),
                    },
                )
            except Exception:
                return []
            return [
                {
                    "period_type": row.get("period_type") or period_type,
                    "period_key": row.get("period_key") or "",
                    "title": row.get("title") or "",
                    "summary": row.get("summary") or "",
                    "digest": row.get("digest") or "",
                    "content": row.get("content") or "",
                }
                for row in rows
                if row.get("content")
            ]

        days, weeks, months = await asyncio.gather(
            load(
                "day",
                self.cfg.calendar_inject_day,
                self.cfg.calendar_context_day_limit,
                getattr(self.cfg, "calendar_context_day_offset", 0),
            ),
            load("week", self.cfg.calendar_inject_week, self.cfg.calendar_context_week_limit),
            load("month", self.cfg.calendar_inject_month, self.cfg.calendar_context_month_limit),
        )
        return {"day": days, "week": weeks, "month": months}

    async def build_context_package(
        self,
        session: dict,
        current_user_text: str,
        is_first_turn: bool,
        cold_start_snapshot: Optional[dict] = None,
        client_name: str = "",
        consume_heartbeat_pending: bool = True,
        context_event: Optional[dict] = None,
        previous_island_state: Optional[dict] = None,
        force_island_rewrite: bool = False,
        force_island_reason: str = "",
        trace_log: Optional[dict] = None,
    ) -> dict:
        _mark_request_log_phase(trace_log, "context.start")
        session_id = session["id"]

        heartbeat_digest, heartbeat_pending_ids = self._normal_heartbeat_context(
            session_id=session_id,
            consume_pending=consume_heartbeat_pending,
        )

        package = {
            "stable_charter": self.stable_charter_block(),
            "heartbeat_digest": heartbeat_digest,
            "heartbeat_pending_ids": heartbeat_pending_ids,
            "cold_start_snapshot": cold_start_snapshot,
            "calendar_context": {"day": [], "week": [], "month": []},
            "mem_notes": [],
            "stars": [],
            "book_overview": {},
            "memory_island_state": previous_island_state or {},
            "memory_island_decision": {},
        }

        # Collect independent context sources concurrently. Each source is normalized
        # to a fail-soft result below so a recall outage does not discard the previous
        # memory island or block an otherwise valid chat request.
        want_bookshelf = getattr(self.cfg, "inject_conflict_shelf", True)
        event_class = str((context_event or {}).get("event_class") or "new_user")
        reuse_previous_island = bool(
            previous_island_state
            and event_class in {"retry", "roll", "client_tool_continuation", "continuation"}
        )
        inject_mem_notes = bool(current_user_text.strip() and self.cfg.inject_mem_notes)
        inject_stars = bool(current_user_text.strip() and getattr(self.cfg, "inject_stars", True))
        previous_star_ids = {
            str(item.get("id") or "").strip()
            for item in (previous_island_state or {}).get("stars") or []
            if str(item.get("id") or "").strip()
        }
        previous_mem_note_ids = {
            str(item.get("id") or "").strip()
            for item in (previous_island_state or {}).get("mem_notes") or []
            if str(item.get("id") or "").strip()
        }

        calendar_task = self.calendar_context_pages()
        bookshelf_task = self._bookshelf_overview() if want_bookshelf else asyncio.sleep(0, result={})

        _mark_request_log_phase(
            trace_log,
            "context.sources_start",
            detail={
                "want_bookshelf": want_bookshelf,
                "inject_mem_notes": inject_mem_notes,
                "inject_stars": inject_stars,
            },
        )

        mem_note_service = MemNoteService(self.cfg, self.supabase_client)

        async def fail_soft_recall(coro, source: str) -> dict[str, Any]:
            try:
                return await coro
            except Exception as exc:
                logger.warning("[Context] %s recall failed: %s", source, exc)
                return {"ok": False, "items": [], "error": str(exc)}

        if reuse_previous_island:
            notes_task = asyncio.sleep(
                0,
                result={"ok": True, "items": list((previous_island_state or {}).get("mem_notes") or [])},
            )
        elif inject_mem_notes:
            notes_task = fail_soft_recall(
                mem_note_service.search_notes_contextual(
                    current_user_text,
                    session_tag=session["session_tag"],
                    limit=self.cfg.mem_note_limit,
                    session_id=session.get("id"),
                    store=self.store,
                    mark_triggered=False,
                    ignore_retrigger_limits=True,
                ),
                "mem note",
            )
        else:
            notes_task = asyncio.sleep(0, result={"ok": True, "items": []})

        async def validate_previous_mem_notes() -> dict[str, Any]:
            if not inject_mem_notes or not previous_mem_note_ids:
                return {"ok": True, "ids": []}
            if not self.supabase_client:
                return {"ok": False, "ids": [], "error": "Supabase is not configured."}
            try:
                active_ids = await mem_note_service.auto_surface_active_ids(
                    sorted(previous_mem_note_ids)
                )
                return {"ok": True, "ids": sorted(active_ids)}
            except Exception as exc:
                logger.warning("[Context] mem note active validation failed: %s", exc)
                return {"ok": False, "ids": [], "error": str(exc)}

        mem_active_task = validate_previous_mem_notes()

        if reuse_previous_island:
            stars_task = asyncio.sleep(
                0,
                result={"ok": True, "items": list((previous_island_state or {}).get("stars") or [])},
            )
        elif inject_stars and (star_query := strip_client_extra_text(current_user_text)[0]):
            # Device-state extras (Operit bundle / PWA status suffix) are
            # noise for star recall; the raw text keeps serving the
            # inject gates and activation trigger_text above/below.
            # A query that strips to empty (e.g. an image-only PWA send,
            # whose text is just the suffix) falls through to the empty
            # branch below instead of hitting recall with a blank query,
            # which would clear the island under a misleading
            # inactive_item reason.
            stars_task = fail_soft_recall(
                StarService(self.cfg, self.supabase_client).search_context(
                    star_query,
                    session_tag=session["session_tag"],
                    session_id=session.get("id"),
                    limit=getattr(self.cfg, "star_inject_limit", 3),
                    mark_activation=False,
                    ignore_recent_fatigue=True,
                    required_star_ids=previous_star_ids,
                    trace_log=trace_log,
                ),
                "star",
            )
        else:
            stars_task = asyncio.sleep(0, result={"ok": True, "items": []})

        calendar_context, book_overview, notes_result, stars_result, mem_active_result = await asyncio.gather(
            calendar_task, bookshelf_task, notes_task, stars_task, mem_active_task
        )
        package["calendar_context"] = calendar_context
        package["mem_notes"] = notes_result.get("items") or []
        package["stars"] = stars_result.get("items") or []

        proposed_stars = (
            package["stars"]
            if inject_stars and stars_result.get("ok")
            else list((previous_island_state or {}).get("stars") or []) if inject_stars else []
        )
        proposed_mem_notes = (
            package["mem_notes"]
            if inject_mem_notes and notes_result.get("ok")
            else list((previous_island_state or {}).get("mem_notes") or []) if inject_mem_notes else []
        )
        active_star_ids = None
        if stars_result.get("ok") and "_active_required_ids" in stars_result:
            active_star_ids = {
                str(item or "").strip()
                for item in stars_result.get("_active_required_ids") or []
                if str(item or "").strip()
            }
        active_mem_note_ids = None
        if mem_active_result.get("ok"):
            active_mem_note_ids = {
                str(item or "").strip()
                for item in mem_active_result.get("ids") or []
                if str(item or "").strip()
            }
        island_state, entering, island_meta = resolve_memory_island(
            previous_island_state,
            proposed_stars,
            proposed_mem_notes,
            force=force_island_rewrite,
            force_reason=force_island_reason,
            active_star_ids=active_star_ids,
            active_mem_note_ids=active_mem_note_ids,
            advance_human_turn=event_class in {"initial", "new_user", "branch"},
            soft_direct_cooldown_turns=getattr(
                self.cfg, "star_soft_direct_cooldown_turns", 8
            ),
        )
        island_meta["star_recall_ok"] = bool(stars_result.get("ok"))
        island_meta["mem_recall_ok"] = bool(notes_result.get("ok"))
        package["memory_island_state"] = island_state
        package["memory_island_decision"] = island_meta
        package["memory_island_log_content"] = memory_island_log_content(
            previous_island_state,
            island_state,
        )
        package["stars"] = island_state.get("stars") or []
        package["mem_notes"] = island_state.get("mem_notes") or []
        if entering["stars"]:
            await StarService(self.cfg, self.supabase_client).activate_context_items(
                entering["stars"],
                trigger_text=current_user_text,
                session_tag=session["session_tag"],
                session_id=session.get("id"),
                trace_log=trace_log,
            )
        if entering["mem_notes"]:
            await MemNoteService(self.cfg, self.supabase_client).mark_context_items_triggered(
                entering["mem_notes"]
            )

        if want_bookshelf:
            package["book_overview"] = book_overview

        _mark_request_log_phase(
            trace_log,
            "context.sources_done",
            detail={
                "day": len((package.get("calendar_context") or {}).get("day") or []),
                "week": len((package.get("calendar_context") or {}).get("week") or []),
                "month": len((package.get("calendar_context") or {}).get("month") or []),
                "books": self._bookshelf_item_count(package.get("book_overview") or {}),
                "mem_notes": len(notes_result.get("items") or []),
                "stars": len(stars_result.get("items") or []),
                "stars_ok": bool(stars_result.get("ok")),
                "island_decision": (package.get("memory_island_decision") or {}).get("decision"),
            },
        )
        _mark_request_log_phase(trace_log, "context.done")
        return package

    async def _bookshelf_overview(self) -> dict:
        try:
            return await ResidentBooksService(
                self.supabase_client,
                runtime_config=self.cfg,
            ).overview()
        except Exception:
            return {}

    @staticmethod
    def _bookshelf_item_count(overview: dict) -> int:
        if not overview:
            return 0
        return 1 + (1 if overview.get("identity") else 0) + len(overview.get("origin_books") or [])

    def _normal_heartbeat_digest(self, session_id: str, consume_pending: bool = True) -> str:
        digest, _ = self._normal_heartbeat_context(session_id=session_id, consume_pending=consume_pending)
        return digest

    def _normal_heartbeat_context(self, session_id: str, consume_pending: bool = True) -> tuple[str, list[str]]:
        heartbeat_batch_size = max(int(self.cfg.heartbeat_inject_every or 5), 1)
        if consume_pending:
            pending_hbs = self.store.get_pending_heartbeats(limit=heartbeat_batch_size)
            if len(pending_hbs) >= heartbeat_batch_size:
                return "\n".join(hb["content"] for hb in pending_hbs), [hb["id"] for hb in pending_hbs]
            return self.store.get_latest_heartbeat_digest(limit=heartbeat_batch_size), []
        return self._heartbeat_digest(limit=heartbeat_batch_size), []

    def _heartbeat_digest(self, limit: int, state: str = "all") -> str:
        hbs = self.store.read_heartbeats(
            session_id=None,
            state=state,
            limit=max(1, int(limit or 10)),
            order="desc",
        )
        if not hbs:
            return ""
        return "\n".join(hb["content"] for hb in reversed(hbs))

    def _preview_normal_heartbeat_digest(self) -> str:
        heartbeat_batch_size = max(int(self.cfg.heartbeat_inject_every or 5), 1)
        digest = self._heartbeat_digest(limit=heartbeat_batch_size, state="pending")
        if digest:
            return digest
        return self._heartbeat_digest(limit=heartbeat_batch_size, state="injected")

    def render_layered_additions(
        self,
        package: dict,
        *,
        client_tool_surface: Optional[str] = None,
    ) -> dict:
        return _render_layered_additions(
            package,
            self._layer_settings(client_tool_surface=client_tool_surface),
        )

    def render_system_additions(
        self,
        package: dict,
        *,
        client_tool_surface: Optional[str] = None,
    ) -> str:
        return _render_system_additions(
            package,
            self._layer_settings(client_tool_surface=client_tool_surface),
        )

    async def preview(self, session_tag: Optional[str]) -> dict:
        session = self.store.get_session_by_tag(session_tag or "default") if session_tag else None
        fake_session = session or {
            "id": "preview",
            "session_tag": session_tag or "default",
            "client_name": "preview",
            "message_count": 0,
        }
        package = await self.build_context_package(
            fake_session,
            current_user_text="",
            is_first_turn=True,
            client_name=fake_session.get("client_name") or "preview",
            consume_heartbeat_pending=False,
        )
        package["heartbeat_digest"] = self._preview_normal_heartbeat_digest()
        return {
            "session_tag": fake_session["session_tag"],
            "package": package,
            "system_additions": self.render_system_additions(package),
            "cache_layers": self.render_layered_additions(package),
            "tools": gateway_native_tools(self.cfg),
        }

    async def build_room_context_package(
        self,
        session: dict,
        trace_log: Optional[dict] = None,
        messages: Optional[list[dict]] = None,
        record_window_scene: bool = True,
    ) -> dict:
        """Build context for room mode — completely replaces normal context."""
        from .room_context import collect_charge_signals, compute_charge, render_room_layers, visible_room_tool_names
        from .room_scenes import extract_weather_from_messages
        from .room_tools import collect_door_counts, room_tool_definitions
        from .stars import StarService

        _mark_request_log_phase(trace_log, "room.start")

        star_service = StarService(self.cfg, self.supabase_client) if self.supabase_client else None

        signals = await collect_charge_signals(
            store=self.store,
            star_service=star_service,
            cfg=self.cfg,
        )
        charge = compute_charge(
            **signals,
            refractory_hours=getattr(self.cfg, "room_charge_refractory_hours", 4),
        )
        _mark_request_log_phase(trace_log, "room.charge", detail={"charge": round(charge, 3), **signals})

        weather_data = None
        if messages:
            try:
                weather_data = extract_weather_from_messages(messages)
            except Exception:
                pass

        trace_limit = getattr(self.cfg, "room_trace_limit", 5)
        last_traces = self.store.recent_room_traces(limit=trace_limit)

        door_specs, book_overview = await asyncio.gather(
            collect_door_counts(
                store=self.store,
                cfg=self.cfg,
                supabase_client=self.supabase_client,
            ),
            self._bookshelf_overview()
            if getattr(self.cfg, "inject_conflict_shelf", True)
            else asyncio.sleep(0, result={}),
        )

        hours_since_last_visit = signals.get("hours_since_last_visit")

        prev_scene = None
        try:
            ws = self.store.last_window_scene()
            if ws and ws.get("tag"):
                from .runtime import parse_ts
                prev_hours = None
                dt = parse_ts(ws.get("created_at"))
                if dt:
                    from .runtime import now as _now
                    prev_hours = max((_now() - dt).total_seconds() / 3600.0, 0.0)
                prev_scene = {"tag": ws["tag"], "hours_ago": prev_hours}
        except Exception:
            pass

        layers, scene_tag = render_room_layers(
            charge,
            last_traces,
            door_specs,
            weather_data=weather_data,
            hours_since_last_visit=hours_since_last_visit,
            prev_scene=prev_scene,
        )
        visible_tool_names = visible_room_tool_names(door_specs, charge)
        bookshelf_text = render_bookshelf_overview(book_overview)
        if bookshelf_text and "shenyu_books" in visible_tool_names:
            layers["slow"] = layers["slow"].rstrip() + "\n\n" + bookshelf_text
        room_tools = room_tool_definitions(visible_tool_names)

        if record_window_scene:
            try:
                self.store.save_window_scene(session.get("id", "room"), scene_tag)
            except Exception:
                pass

        # Append profile (stable_charter_block) after room charter
        profile = self.stable_charter_block()
        if profile:
            layers["stable"] = layers["stable"].rstrip() + "\n\n" + profile.strip()

        _mark_request_log_phase(
            trace_log,
            "room.done",
            detail={"doors": len(door_specs), "visible_tools": len(room_tools), "scene_tag": scene_tag},
        )

        return {
            "is_room": True,
            "charge": charge,
            "layers": layers,
            "room_tools": room_tools,
            "heartbeat_pending_ids": [],
            "cold_start_snapshot": None,
        }

    async def preview_room(self, session_tag: Optional[str] = None) -> dict:
        """Admin preview for room mode context."""
        session = self.store.get_session_by_tag(session_tag or "default") if session_tag else None
        fake_session = session or {
            "id": "preview",
            "session_tag": session_tag or "default",
            "client_name": "preview",
            "message_count": 0,
        }
        package = await self.build_room_context_package(fake_session, record_window_scene=False)
        return {
            "session_tag": fake_session["session_tag"],
            "mode": "room",
            "charge": package.get("charge"),
            "layers": package.get("layers"),
            "room_tools": package.get("room_tools") or [],
        }
