from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from .conflict_books import ConflictBookService
from .context_layers import (
    ContextLayerSettings,
    render_layered_additions as _render_layered_additions,
    render_system_additions as _render_system_additions,
)
from .gateway_tools import GatewayToolService
from .mem_notes import MemNoteService
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

_INLINE_MEM_PROMPT = """## Inline Mem（仅网关可见）
如果我觉得“这个以后还想记得”，在最后留一个 [mem]...[/mem]。
是一张我自己的便签，写完会被网关保存进“待整理”，有空我再去整理，整理完后聊到相关的会贴到我的上下文里。
没有想记就不写。如果当时有复杂或者颇有感触的心情，我也许会想用一段和弦写在最后面把那一刻定格下来。
如果同时记下来 heartbeat 和 mem，放在独立块里，不要互相嵌套。
"""

_STAR_PROMPT = """## Star（仅网关可见）
如果这一刻有很小、很准的体感/和弦，最后可以留一颗 [star]...[/star]。
写法可以是：

[star chord="Am"]
有一点亮，但还不想把话说满。
[/star]

也可以写成：
[star]Am · 有一点亮，但还不想把话说满。[/star]

星星会被网关保存。以后相关时，网关只轻轻反上来几颗；不需要每次都写。
不要把 star 和 heartbeat/mem 嵌套。
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
        is_hisense_client: Callable[[Optional[str]], bool],
    ):
        self.store = store
        self.sessions = sessions
        self.tools = tools
        self.cfg = cfg
        self.supabase_client = supabase_client
        self.stable_charter_block = stable_charter_block
        self.is_hisense_client = is_hisense_client

    def _layer_settings(self) -> ContextLayerSettings:
        return ContextLayerSettings(
            enable_gateway_tools=bool(getattr(self.cfg, "enable_upstream_tools", True))
            and bool(getattr(self.cfg, "enable_gateway_tools", True)),
            inject_inline_memory_prompt=self.cfg.inject_inline_memory_prompt,
            inject_star_prompt=bool(getattr(self.cfg, "inject_star_prompt", True)),
            heartbeat_prompt=_HEARTBEAT_PROMPT,
            inline_mem_prompt=_INLINE_MEM_PROMPT,
            star_prompt=_STAR_PROMPT,
        )

    async def calendar_context_pages(self) -> dict[str, list[dict[str, Any]]]:
        if not self.supabase_client:
            return {"day": [], "week": [], "month": []}

        async def load(period_type: str, enabled: bool, limit: int) -> list[dict[str, Any]]:
            if not enabled or limit <= 0:
                return []
            try:
                rows = await self.supabase_client.query(
                    "calendar_pages",
                    {
                        "select": "period_type,period_key,title,summary,digest,content,period_start",
                        "period_type": f"eq.{period_type}",
                        "is_latest": "eq.true",
                        "order": "period_start.desc",
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
            load("day", self.cfg.calendar_inject_day, self.cfg.calendar_context_day_limit),
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
    ) -> dict:
        session_id = session["id"]
        is_hisense = self.is_hisense_client(client_name)

        heartbeat_digest, heartbeat_pending_ids = self._normal_heartbeat_context(
            session_id=session_id,
            consume_pending=consume_heartbeat_pending and not is_hisense,
        )
        hisense_heartbeat_digest, hisense_heartbeat_pending_ids = (
            self._hisense_heartbeat_context(consume_pending=consume_heartbeat_pending)
            if is_hisense
            else ("", [])
        )

        package = {
            "is_hisense": is_hisense,
            "stable_charter": self.stable_charter_block(),
            "heartbeat_digest": heartbeat_digest,
            "heartbeat_pending_ids": heartbeat_pending_ids,
            "hisense_heartbeat_digest": hisense_heartbeat_digest,
            "hisense_heartbeat_pending_ids": hisense_heartbeat_pending_ids,
            "cold_start_snapshot": cold_start_snapshot,
            "calendar_context": {"day": [], "week": [], "month": []},
            "mem_notes": [],
            "stars": [],
            "notebook_items": [],
            "last_wake_recap": "",
            "conflict_books": [],
        }

        package["calendar_context"] = await self.calendar_context_pages()
        if not is_hisense and getattr(self.cfg, "inject_conflict_shelf", True):
            package["conflict_books"] = await self._conflict_shelf_books()

        if is_hisense:
            package["notebook_items"] = await self._hisense_notebook_items()
            package["last_wake_recap"] = await self._hisense_last_wake_recap(session)
        else:
            tasks = []
            if current_user_text.strip() and self.cfg.inject_mem_notes:
                tasks.append(
                    MemNoteService(self.cfg, self.supabase_client).search_notes_contextual(
                        current_user_text,
                        session_tag=session["session_tag"],
                        limit=self.cfg.mem_note_limit,
                        session_id=session.get("id"),
                        store=self.store,
                    )
                )
            else:
                tasks.append(asyncio.sleep(0, result={"ok": True, "items": []}))

            if current_user_text.strip() and getattr(self.cfg, "inject_stars", True):
                tasks.append(
                    StarService(self.cfg, self.supabase_client).search_context(
                        current_user_text,
                        session_tag=session["session_tag"],
                        session_id=session.get("id"),
                        limit=getattr(self.cfg, "star_inject_limit", 3),
                    )
                )
            else:
                tasks.append(asyncio.sleep(0, result={"ok": True, "items": []}))

            notes_result, stars_result = await asyncio.gather(*tasks)
            package["mem_notes"] = notes_result.get("items") or []
            package["stars"] = stars_result.get("items") or []
        return package

    async def _conflict_shelf_books(self) -> list[dict]:
        if not self.supabase_client:
            return []
        try:
            result = await ConflictBookService(self.supabase_client).list_books()
            return result.get("books") or []
        except Exception:
            return []

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
        return self._heartbeat_digest(hisense=False, limit=heartbeat_batch_size), []

    def _heartbeat_digest(self, hisense: bool, limit: int, state: str = "all") -> str:
        hbs = self.store.read_heartbeats(
            session_id=None,
            state=state,
            limit=max(1, int(limit or 10)),
            order="desc",
            hisense=hisense,
        )
        if not hbs:
            return ""
        return "\n".join(hb["content"] for hb in reversed(hbs))

    def _hisense_heartbeat_digest(self, consume_pending: bool = True) -> str:
        digest, _ = self._hisense_heartbeat_context(consume_pending=consume_pending)
        return digest

    def _hisense_heartbeat_context(self, consume_pending: bool = True) -> tuple[str, list[str]]:
        heartbeat_batch_size = max(int(self.cfg.hisense_heartbeat_limit or 3), 1)
        if consume_pending:
            pending_hbs = self.store.get_pending_heartbeats(limit=heartbeat_batch_size, hisense=True)
            if len(pending_hbs) >= heartbeat_batch_size:
                return "\n".join(hb["content"] for hb in pending_hbs), [hb["id"] for hb in pending_hbs]
            return self.store.get_latest_heartbeat_digest(limit=heartbeat_batch_size, hisense=True), []
        return self._heartbeat_digest(hisense=True, limit=self.cfg.hisense_heartbeat_limit), []

    def _preview_normal_heartbeat_digest(self) -> str:
        heartbeat_batch_size = max(int(self.cfg.heartbeat_inject_every or 5), 1)
        digest = self._heartbeat_digest(hisense=False, limit=heartbeat_batch_size, state="pending")
        if digest:
            return digest
        return self._heartbeat_digest(hisense=False, limit=heartbeat_batch_size, state="injected")

    async def _hisense_notebook_items(self) -> list[dict]:
        if not self.supabase_client:
            return []
        try:
            rows = await self.supabase_client.query(
                "shenyu_notebook",
                {
                    "status": "eq.active",
                    "order": "pinned.desc,updated_at.desc",
                    "limit": str(self.cfg.hisense_notebook_limit),
                    "select": "id,type,content,tags,status,pinned,updated_at",
                },
            )
            return rows or []
        except Exception:
            return []

    async def _hisense_last_wake_recap(self, session: dict) -> str:
        if self.supabase_client:
            try:
                rows = await self.supabase_client.query(
                    "shenyu_notebook",
                    {
                        "tags": "cs.{handoff}",
                        "order": "updated_at.desc",
                        "limit": "1",
                        "select": "content,updated_at",
                    },
                )
                if rows:
                    return rows[0].get("content") or ""
            except Exception:
                pass
        hbs = self.store.read_heartbeats(session_id=None, state="injected", limit=1, order="desc", hisense=True)
        if hbs:
            return hbs[0]["content"]
        return ""

    def render_layered_additions(self, package: dict) -> dict:
        return _render_layered_additions(package, self._layer_settings())

    def render_system_additions(self, package: dict) -> str:
        return _render_system_additions(package, self._layer_settings())

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
