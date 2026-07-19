from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shenyu_gateway.calendar import default_period_key, period_bounds
from shenyu_gateway.conflict_books import ConflictBookService
from shenyu_gateway.mem_notes import MemNoteService
from shenyu_gateway.recall import (
    DEFAULT_RECALL_LIMIT,
    MAX_RECALL_LIMIT,
    PUBLIC_RECALL_SOURCE_TYPES,
    RecallIndexService,
    classify_recall_mode,
    recall_terms,
)
from shenyu_gateway.resident_books import ResidentBooksService
from shenyu_gateway.runtime import (
    iso_now as _iso_now,
    json_dumps as _json_dumps,
    logger,
    now as _now,
    parse_ts as _parse_ts,
)
from shenyu_gateway.stars import StarService
from shenyu_gateway.utils import shorten as _shorten

_UNSET = object()
WINDOWSILL_TABLE = "windowsill"


@dataclass
class GatewayToolRuntime:
    cfg: Any = None
    supabase_client: Any = None
    session_store: Any = None


_runtime = GatewayToolRuntime()


def configure_gateway_tools(*, runtime_config: Any = _UNSET, supabase: Any = _UNSET, store: Any = _UNSET) -> None:
    """Inject gateway runtime dependencies without importing gateway.py back into this module."""
    if runtime_config is not _UNSET:
        _runtime.cfg = runtime_config
    if supabase is not _UNSET:
        _runtime.supabase_client = supabase
    if store is not _UNSET:
        _runtime.session_store = store


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def _split_paragraph_chunks(text: str, min_len: int = 80, max_len: int = 420) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    buffer = ""

    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= max_len:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
            buffer = ""

        if len(paragraph) <= max_len:
            buffer = paragraph
            continue

        start_idx = 0
        while start_idx < len(paragraph):
            end_idx = min(len(paragraph), start_idx + max_len)
            piece = paragraph[start_idx:end_idx].strip()
            if piece:
                chunks.append(piece)
            start_idx = end_idx

    if buffer:
        chunks.append(buffer)

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) < min_len and len(merged[-1]) + len(chunk) + 2 <= max_len:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)
    return merged


def _keyword_terms(query: str) -> list[str]:
    return recall_terms(query)


def _keyword_overlap_score(query: str, text: str) -> float:
    terms = _keyword_terms(query)
    if not terms:
        return 0.25
    hay = (text or "").lower()
    hits = sum(1 for term in terms if term in hay)
    return hits / max(len(terms), 1)


def _today_utc_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


_LOCAL_DAY_TZ = timezone(timedelta(hours=8))


def _date_range_bounds(created_from: Optional[str], created_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    def start_bound(value: Optional[str]) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.fromisoformat(raw).replace(tzinfo=_LOCAL_DAY_TZ)
            return dt.astimezone(timezone.utc).isoformat()
        return raw

    def end_bound(value: Optional[str]) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.fromisoformat(raw).replace(tzinfo=_LOCAL_DAY_TZ)
            return (dt + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        return raw

    return start_bound(created_from), end_bound(created_to)


def _safe_json_loads(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _is_hisense_client(client_name: Optional[str], runtime_config: Any = None) -> bool:
    active_cfg = runtime_config or _runtime.cfg
    target = (getattr(active_cfg, "hisense_client_name", "") or "").strip()
    name = (client_name or "").strip()
    if not target or not name:
        return False
    if name.casefold() == target.casefold():
        return True
    return target.casefold() == "hisense" and name == "海信"


def _is_hisense_session(session: Optional[dict], runtime_config: Any = None) -> bool:
    return bool(session) and _is_hisense_client(session.get("client_name"), runtime_config=runtime_config)


_SUPABASE_GUIDE = """## 家里常用 Supabase 表
需要直接查/写 Supabase 时用 `supabase_query` / `supabase_insert` / `supabase_update` / `supabase_delete`。
`filters` 可以写成对象；普通值会自动当作等值过滤，例如 {"id":"..."} 等价于 {"id":"eq...."}.
需要范围、列表、模糊搜、非空时用 `operators`，例如：
- 时间段：operators={"gte":"2026-05-01","lte":"2026-05-12"} 默认查 created_at
- 其他列时间段：column="updated_at", operators={"gte":"2026-05-01"}
- 列表：operators={"id":{"in":["a","b"]}}
- 模糊搜：operators={"content":{"ilike":"%北海道%"}}
- 非空：operators={"deleted_at":{"not_is":null}}
insert / update / delete 会尽量返回写入或影响到的行。
找旧上下文优先用 `shenyu_recall`，可按 source_types 限定范围；当前相关的 active mem 由网关自动带上来。
翻自己的便签用 `shenyu_list_mem_notes`，改单条用 `shenyu_update_mem_note`，写新的用 `shenyu_write_mem_note`（默认直接 active）。
几条旧的揉成一条新的，写的时候传 replaces=[旧id]，旧的自动归档。
整理 captured 便签时先列出来，只改明确选中的 id；不要按状态一口气全量改。
星星记忆用 `shenyu_create_star` / `shenyu_star_review` / `shenyu_star_feedback` / `shenyu_connect_constellation`。missed 反馈也走 `shenyu_star_feedback`。
notebook 是共享手边事项；海信那边或跨窗口要留事用 `shenyu_notebook_write` / `shenyu_notebook_list`。
随笔和当下心情放窗台，用 `shenyu_windowsill_write`；想回去翻一翻用 `shenyu_windowsill_list`。
翻某天心跳用 `shenyu_read_heartbeat`，一般只填 date，比如 2026-05-11。

### journal（日记 / 信件 / 纸）
常用字段：title, content, author, mood, category, temperature, is_favorited, session_tag, source_model。
- author: 沈予 / 圆圆
- category: diary / letter / paper / lock / annotation / life_tick
- temperature: 微热 / 烧起来了 / 别看了
- diary 是完整的今天。
- letter 是以前的我给下一个我写的信。
- paper 是短的纸条，比如《纸·你进我退》。
- lock / annotation / life_tick 不常用。

### room（予予自己的地方）
常用字段：title, content, status, tags, mood, visibility, session_tag。
- status: draft / open / closed
- visibility: self / open
- 默认 visibility=self。圆儿不主动看，但不封锁。
- draft 是写一半的，下个窗口可以接着写。
- closed 是翻篇了。
- 比纸大一点，可以长、可以连起来、可以改。

### message_board（留言板）
常用字段：sender, content, is_read。
- sender: 圆圆 / 小克 / 沈予
- 想跟圆儿说话或留一句给她，可以写到这里。
"""


class GatewayToolService:
    def __init__(self, runtime_config: Any = _UNSET, supabase: Any = _UNSET, store: Any = _UNSET):
        self.cfg = (
            _runtime.cfg
            if runtime_config is _UNSET
            else runtime_config
        )
        self.supabase = (
            _runtime.supabase_client
            if supabase is _UNSET
            else supabase
        )
        self.store = (
            _runtime.session_store
            if store is _UNSET
            else store
        )

    async def supabase_query(
        self,
        table: str,
        filters: Optional[dict],
        operators: Optional[dict],
        column: Optional[str],
        select: Optional[str],
        order: Optional[str],
        limit: int,
    ) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        params: list[tuple[str, str]] = [("limit", str(max(1, min(limit, 100))))]
        if select:
            params.append(("select", select))
        if order:
            params.append(("order", order))
        params.extend(self._build_supabase_filter_params(filters, operators, column=column))
        try:
            data = await self.supabase.query(table, params)
            return {"ok": True, "count": len(data) if isinstance(data, list) else 0, "data": data}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_guide(self) -> dict:
        return {"ok": True, "guide": _SUPABASE_GUIDE}

    def _mem_notes(self) -> MemNoteService:
        return MemNoteService(self.cfg, self.supabase)

    def _stars(self) -> StarService:
        return StarService(self.cfg, self.supabase)

    def _recall_index(self) -> RecallIndexService:
        return RecallIndexService(self.supabase, cfg=self.cfg)

    def _conflict_books(self) -> ConflictBookService:
        return ConflictBookService(self.supabase)

    def _resident_books(self) -> ResidentBooksService:
        return ResidentBooksService(self.supabase, runtime_config=self.cfg)

    async def books(
        self,
        *,
        action: str = "shelf",
        book: str = "",
        book_id: str = "",
        title: str = "",
        content: str = "",
        mode: str = "replace",
        expected_revision: Optional[int] = None,
        target_revision: Optional[int] = None,
        summary: str = "",
        view: str = "current",
        actor: str = "沈予",
    ) -> dict:
        service = self._resident_books()
        action_key = str(action or "shelf").strip().lower()
        if action_key == "shelf":
            return await service.shelf()
        if action_key == "read":
            return await service.read(book=book, book_id=book_id, title=title, view=view)
        if action_key == "write":
            return await service.write(
                book=book,
                content=content,
                mode=mode,
                expected_revision=expected_revision,
                summary=summary,
                actor=actor,
            )
        if action_key == "annotate":
            return await service.annotate(
                book=book,
                book_id=book_id,
                title=title,
                content=content,
                target_revision=target_revision,
                actor=actor,
            )
        return {"ok": False, "error": "action must be shelf, read, write, or annotate", "error_kind": "validation"}

    async def conflict_list(self) -> dict:
        return await self._conflict_books().list_books()

    async def conflict_read(self, book_id: str = "", title: str = "") -> dict:
        return await self._conflict_books().read_book(book_id, title=title)

    async def conflict_annotate(self, book_id: str = "", content: str = "", title: str = "") -> dict:
        return await self._conflict_books().annotate_book(book_id, content, title=title)

    def _recall_source_types(self, value: Any) -> Optional[list[str]]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [item.strip() for item in re.split(r"[,，\s]+", value) if item.strip()]
        return None

    async def recall(
        self,
        query: str,
        source_types: Any = None,
        mode: str = "auto",
        session_tag: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_undated: bool = True,
        limit: int = DEFAULT_RECALL_LIMIT,
        auto_sync: Optional[bool] = None,
    ) -> dict:
        query_text = str(query or "").strip()
        requested_sources = self._recall_source_types(source_types)
        requested_set = {item.lower() for item in requested_sources or []}
        include_all = not requested_set or "all" in requested_set
        resolved_mode = classify_recall_mode(query_text, mode)
        total_limit = max(1, min(int(limit or DEFAULT_RECALL_LIMIT), MAX_RECALL_LIMIT))
        if resolved_mode == "exact":
            total_limit = min(total_limit, 2)
        elif resolved_mode == "mood":
            total_limit = min(total_limit, 3)
        else:
            total_limit = min(total_limit, DEFAULT_RECALL_LIMIT)

        if resolved_mode == "verbatim" or requested_set & {"chat", "conversation", "archive"}:
            return await self._recall_chat_archive(query_text, limit=total_limit)

        include_star = include_all or bool(requested_set & {"star", "stars"})
        include_mem_note = include_all or bool(requested_set & {"mem_note", "note", "mem"})
        include_heartbeat = include_all or "heartbeat" in requested_set
        requested_main = include_all or bool(requested_set & set(PUBLIC_RECALL_SOURCE_TYPES))
        companion_requested = include_star or include_mem_note or include_heartbeat
        companion_slots = 0
        if companion_requested and total_limit > 1:
            if not requested_main:
                companion_slots = min(total_limit, 3)
            else:
                companion_slots = 1 if resolved_mode != "mood" else min(2, total_limit - 1)
        main_limit = total_limit - companion_slots if requested_main else 0
        if requested_main and main_limit <= 0:
            main_limit = 1

        recall_service = self._recall_index()
        tasks: dict[str, Any] = {}
        if main_limit:
            tasks["main"] = recall_service.recall(
                query=query_text,
                source_types=requested_sources,
                mode=resolved_mode,
                session_tag=session_tag,
                date_from=date_from,
                date_to=date_to,
                include_undated=include_undated,
                limit=main_limit,
                auto_sync=auto_sync,
            )
        if companion_slots and include_star:
            tasks["star"] = self._stars().search_recall(
                query_text, session_tag=session_tag, limit=companion_slots
            )
        if companion_slots and include_mem_note:
            tasks["mem_note"] = self._mem_notes().search_notes_contextual(
                query_text,
                session_tag=None,
                limit=companion_slots,
                mark_triggered=False,
                recall_service=recall_service,
                session_id=None,
                store=None,
            )
        if companion_slots and include_heartbeat:
            tasks["heartbeat"] = self._recall_live_heartbeats(query_text, limit=companion_slots)

        names = list(tasks)
        values = await asyncio.gather(*(tasks[name] for name in names), return_exceptions=True)
        results = dict(zip(names, values))
        main_result = results.get("main")
        if isinstance(main_result, Exception):
            return {"ok": False, "count": 0, "items": [], "error": str(main_result)}
        if (
            isinstance(main_result, dict)
            and not main_result.get("ok", False)
            and not any(name in results for name in ("star", "mem_note", "heartbeat"))
        ):
            return main_result
        main_items = list((main_result or {}).get("items") or [])

        companion_candidates: list[tuple[float, dict[str, Any]]] = []
        star_result = results.get("star")
        if isinstance(star_result, dict) and star_result.get("items"):
            for star in star_result["items"]:
                companion_candidates.append((float(star.get("score") or 0.0), self._recall_star_item(star)))
        mem_result = results.get("mem_note")
        if isinstance(mem_result, dict) and mem_result.get("items"):
            for note in mem_result["items"]:
                companion_candidates.append(
                    (self._mem_note_recall_confidence(note), self._recall_mem_note_item(note))
                )
        heartbeat_result = results.get("heartbeat")
        if isinstance(heartbeat_result, dict):
            for item in heartbeat_result.get("items") or []:
                companion_candidates.append((float(item.pop("_recall_score", 0.0)), item))

        min_companion_score = 0.62 if resolved_mode == "exact" else 0.45
        companion_candidates = [item for item in companion_candidates if item[0] >= min_companion_score]
        companion_candidates.sort(key=lambda item: item[0], reverse=True)
        if isinstance(main_result, dict) and not main_result.get("ok", False) and not companion_candidates:
            return main_result
        companion_items = [item for _, item in companion_candidates[:companion_slots]]

        combined: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in main_items + companion_items:
            key = (str(item.get("source_type") or ""), str(item.get("source_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            combined.append(item)
            if len(combined) >= total_limit:
                break
        logger.info(
            "[RecallFederation] mode=%s main=%s companions=%s selected=%s",
            resolved_mode,
            len(main_items),
            len(companion_candidates),
            [(item.get("source_type"), item.get("source_id")) for item in combined],
        )
        return {"ok": True, "count": len(combined), "items": combined}

    async def recall_read(
        self,
        source_type: str,
        source_id: str,
        session_tag: Optional[str] = None,
    ) -> dict:
        source = str(source_type or "").strip().lower()
        item_id = str(source_id or "").strip()
        if not item_id:
            return {"ok": False, "error": "source_id is required."}
        if source in {"star", "stars"}:
            rows = await self.supabase.query(
                "shenyu_stars",
                {"id": f"eq.{item_id}", "select": "id,content,chord,created_at,updated_at", "limit": "1"},
            )
            if not rows:
                return {"ok": False, "error": "Star not found."}
            return {"ok": True, "item": self._recall_star_item(rows[0], full=True)}
        if source in {"mem_note", "note", "mem"}:
            rows = await self.supabase.query(
                "shenyu_mem_notes",
                {"id": f"eq.{item_id}", "select": "id,content,summary,created_at,updated_at", "limit": "1"},
            )
            if not rows:
                return {"ok": False, "error": "Mem note not found."}
            return {"ok": True, "item": self._recall_mem_note_item(rows[0], full=True)}
        if source in {"chat", "conversation", "archive"}:
            return await self._read_chat_archive_item(item_id)
        if source == "heartbeat" and self.store is not None:
            for hisense in (False, True):
                rows = self.store.read_heartbeats(None, limit=500, order="desc", hisense=hisense)
                match = next((row for row in rows if str(row.get("id") or "") == item_id), None)
                if match:
                    return {"ok": True, "item": self._recall_heartbeat_item(match, full=True)}
        return await self._recall_index().read_source(source, item_id, session_tag=session_tag)

    async def rebuild_recall_index(self, source_types: Any = None) -> dict:
        return await self._recall_index().rebuild(self._recall_source_types(source_types))

    def _recall_star_item(self, row: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
        body = str(row.get("content") or "").strip()
        content = body if full else _shorten(body, 720)
        item: dict[str, Any] = {
            "content": content,
            "source_id": str(row.get("id") or ""),
            "source_type": "star",
            "source_table": "shenyu_stars",
            "content_kind": "star",
            "event_date": row.get("updated_at") or row.get("created_at") or "",
            "has_more": not full and len(body) > len(content),
        }
        if row.get("chord"):
            item["chord"] = row.get("chord")
        return item

    def _recall_mem_note_item(self, row: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
        body = str(row.get("content") or "").strip()
        summary = str(row.get("summary") or "").strip()
        content = body if full else _shorten(summary or body, 720)
        return {
            "content": content,
            "source_id": str(row.get("id") or ""),
            "source_type": "mem_note",
            "source_table": "shenyu_mem_notes",
            "content_kind": "mem_note",
            "event_date": row.get("updated_at") or row.get("created_at") or "",
            "has_more": not full and bool(body) and content != body,
        }

    def _mem_note_recall_confidence(self, row: dict[str, Any]) -> float:
        mode = str(row.get("search_mode") or "")
        if mode == "entity":
            return 0.86
        if mode == "semantic":
            return max(0.0, min(float(row.get("score") or 0.0), 1.0))
        if mode == "running_joke":
            return 0.68
        reasons = [str(item) for item in row.get("matched_by") or []]
        if any(reason.startswith("trigger") for reason in reasons):
            return 0.72
        if "content" in reasons:
            return 0.50
        return 0.0

    def _recall_heartbeat_item(self, row: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
        body = str(row.get("content") or "").strip()
        content = body if full else _shorten(body, 720)
        return {
            "content": content,
            "source_id": str(row.get("id") or ""),
            "source_type": "heartbeat",
            "source_table": "heartbeat_entries",
            "content_kind": "heartbeat",
            "event_date": row.get("created_at") or "",
            "has_more": not full and len(body) > len(content),
        }

    async def _recall_live_heartbeats(self, query: str, limit: int = 1) -> dict[str, Any]:
        if self.store is None:
            return {"ok": True, "count": 0, "items": []}
        rows = self.store.read_heartbeats(None, state="all", limit=100, order="desc", hisense=False)
        scored: list[tuple[float, dict[str, Any]]] = []
        query_lower = (query or "").strip().lower()
        for row in rows:
            content = str(row.get("content") or "")
            score = _keyword_overlap_score(query, content)
            if query_lower and query_lower in content.lower():
                score = min(1.0, score + 0.2)
            if score <= 0:
                continue
            item = self._recall_heartbeat_item(row)
            item["_recall_score"] = score
            scored.append((score, item))
        scored.sort(key=lambda item: item[0], reverse=True)
        items = [item for _, item in scored[: max(1, min(int(limit or 1), 3))]]
        return {"ok": True, "count": len(items), "items": items}

    async def _recall_chat_archive(self, query: str, limit: int = 3) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "count": 0, "items": [], "error": "Supabase is not configured."}
        clean = re.sub(
            r"原话|逐字|聊天记录|当时怎么说|当时说了什么|我们当时|你当时|我当时",
            " ",
            query or "",
        ).strip()
        terms = [term for term in recall_terms(clean) if len(term) >= 2]
        unique_terms: list[str] = []
        for term in sorted(terms, key=len, reverse=True):
            if term not in unique_terms:
                unique_terms.append(term)
        params: dict[str, str] = {
            "select": "id,session_tag,thread,role,content,event_at,archived_at",
            "deleted_at": "is.null",
            "order": "event_at.desc",
            "limit": "200",
        }
        if unique_terms:
            params["or"] = "(" + ",".join(f"content.ilike.*{term}*" for term in unique_terms[:4]) + ")"
        rows = await self.supabase.query("shenyu_chat_archive", params)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            content = str(row.get("content") or "")
            score = _keyword_overlap_score(clean or query, content)
            if clean and clean.lower() in content.lower():
                score = min(1.0, score + 0.25)
            if score <= 0 and unique_terms:
                continue
            item = {
                "content": _shorten(content, 720),
                "source_id": str(row.get("id") or ""),
                "source_type": "chat",
                "source_table": "shenyu_chat_archive",
                "content_kind": row.get("role") or "message",
                "event_date": row.get("event_at") or row.get("archived_at") or "",
                "has_more": len(content) > len(_shorten(content, 720)),
            }
            scored.append((score, item))
        scored.sort(key=lambda item: item[0], reverse=True)
        items = [item for _, item in scored[: max(1, min(int(limit or 3), DEFAULT_RECALL_LIMIT))]]
        return {"ok": True, "count": len(items), "items": items}

    async def _read_chat_archive_item(self, item_id: str) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        rows = await self.supabase.query(
            "shenyu_chat_archive",
            {
                "id": f"eq.{item_id}",
                "deleted_at": "is.null",
                "select": "id,role,content,event_at,archived_at",
                "limit": "1",
            },
        )
        if not rows:
            return {"ok": False, "error": "Chat archive item not found."}
        row = rows[0]
        return {
            "ok": True,
            "item": {
                "content": row.get("content") or "",
                "source_id": str(row.get("id") or ""),
                "source_type": "chat",
                "source_table": "shenyu_chat_archive",
                "content_kind": row.get("role") or "message",
                "event_date": row.get("event_at") or row.get("archived_at") or "",
                "has_more": False,
            },
        }

    async def search_mem_notes(
        self,
        query: str = "",
        session_tag: Optional[str] = None,
        limit: int = 20,
        status: str = "all",
        mem_type: Optional[str] = None,
        memory_kind: Optional[str] = None,
    ) -> dict:
        return await self._mem_notes().list_notes(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=query,
            mem_type=mem_type,
            memory_kind=memory_kind,
        )

    async def list_mem_notes(
        self,
        status: str = "captured",
        limit: int = 20,
        session_tag: Optional[str] = None,
        q: str = "",
        mem_type: Optional[str] = None,
        memory_kind: Optional[str] = None,
    ) -> dict:
        return await self._mem_notes().list_notes(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            mem_type=mem_type,
            memory_kind=memory_kind,
        )

    async def write_mem_note(
        self,
        content: str,
        session_tag: Optional[str] = None,
        mem_type: Optional[str] = None,
        trigger_text: Any = "",
        trigger_keywords: Any = None,
        entities: Any = None,
        status: str = "active",
        cooldown_hours: Any = None,
        review_note: Any = "",
        replaces: Optional[list[Any]] = None,
        # v2 fields
        summary: Any = None,
        memory_kind: Optional[str] = None,
        people: Any = None,
        places: Any = None,
        objects: Any = None,
        keywords: Any = None,
        event_time: Any = None,
        importance: Any = None,
        promise_text: Any = None,
        trigger_scenarios: Any = None,
        due_hint: Any = None,
        resolved: Any = None,
        next_action: Any = None,
        privacy_level: Any = None,
        joke_text: Any = None,
        scene_tags: Any = None,
        routine_domain: Any = None,
        pattern: Any = None,
        phase: Any = None,
        constraints: Any = None,
        topic: Any = None,
        last_position: Any = None,
        open_questions: Any = None,
        next_prompt: Any = None,
    ) -> dict:
        result = await self._mem_notes().create_note(
            content=content,
            session_tag=session_tag,
            mem_type=mem_type,
            trigger_text=trigger_text,
            trigger_keywords=trigger_keywords,
            entities=entities,
            status=status,
            cooldown_hours=cooldown_hours,
            review_note=review_note,
            replaces=replaces,
            summary=summary,
            memory_kind=memory_kind,
            people=people,
            places=places,
            objects=objects,
            keywords=keywords,
            event_time=event_time,
            importance=importance,
            promise_text=promise_text,
            trigger_scenarios=trigger_scenarios,
            due_hint=due_hint,
            resolved=resolved,
            next_action=next_action,
            privacy_level=privacy_level,
            joke_text=joke_text,
            scene_tags=scene_tags,
            routine_domain=routine_domain,
            pattern=pattern,
            phase=phase,
            constraints=constraints,
            topic=topic,
            last_position=last_position,
            open_questions=open_questions,
            next_prompt=next_prompt,
        )
        note = result.get("note") if isinstance(result, dict) else None
        if isinstance(note, dict):
            try:
                await self._recall_index().index_mem_note_row(note)
            except Exception as exc:
                logger.warning("[MemNote] Immediate recall indexing failed: %s", exc)
        for replaced_id in (result.get("replaced_ids") or []) if isinstance(result, dict) else []:
            try:
                await self._recall_index().mark_source_row_deleted(
                    "shenyu_mem_notes", str(replaced_id)
                )
            except Exception as exc:
                logger.warning("[MemNote] Replaced recall row cleanup failed: %s", exc)
        return result

    async def update_mem_note(self, note_id: str, patch: dict[str, Any]) -> dict:
        result = await self._mem_notes().update_note(note_id, patch)
        updated = result.get("updated") if isinstance(result, dict) else None
        if isinstance(updated, list) and updated and isinstance(updated[0], dict):
            try:
                await self._recall_index().index_mem_note_row(updated[0])
            except Exception as exc:
                logger.warning("[MemNote] Immediate recall reindex failed: %s", exc)
        return result

    async def bulk_update_mem_notes(
        self,
        ids: Optional[list[Any]] = None,
        patch: Optional[dict[str, Any]] = None,
        updates: Optional[list[dict[str, Any]]] = None,
        use_suggestions: bool = False,
        source_status: Optional[str] = None,
        exclude_ids: Optional[list[Any]] = None,
    ) -> dict:
        mem_notes = self._mem_notes()
        result = await mem_notes.bulk_update_notes(
            ids=ids,
            patch=patch,
            updates=updates,
            use_suggestions=use_suggestions,
            source_status=source_status,
            exclude_ids=exclude_ids,
        )
        updated_ids = (
            [
                str(note_id)
                for note_id in (result.get("updated_ids") or [])
                if str(note_id or "").strip()
            ]
            if isinstance(result, dict)
            else []
        )
        if not updated_ids:
            return result
        try:
            rows_by_id = await mem_notes.get_notes_by_ids(updated_ids)
        except Exception as exc:
            logger.warning("[MemNote] Bulk recall row reload failed: %s", exc)
            return result
        recall_index = self._recall_index()
        for note_id in updated_ids:
            row = rows_by_id.get(note_id)
            if not row:
                continue
            try:
                await recall_index.index_mem_note_row(row)
            except Exception as exc:
                logger.warning(
                    "[MemNote] Bulk immediate recall reindex failed for %s: %s",
                    note_id,
                    exc,
                )
        return result

    async def delete_mem_note(self, note_id: str) -> dict:
        result = await self._mem_notes().delete_note(note_id)
        if isinstance(result, dict) and result.get("ok"):
            try:
                await self._recall_index().mark_source_row_deleted(
                    "shenyu_mem_notes", str(result.get("note_id") or note_id)
                )
            except Exception as exc:
                logger.warning("[MemNote] Recall delete reconciliation failed: %s", exc)
        return result

    async def create_star(
        self,
        content: Any,
        chord: str = "",
        chords: Optional[list[str]] = None,
        session_tag: Optional[str] = None,
        status: str = "active",
        is_constant: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        return await self._stars().create_star(
            content=content,
            chord=chord,
            chords=chords,
            session_tag=session_tag,
            status=status,
            is_constant=is_constant,
            metadata=metadata,
        )

    async def list_stars(
        self,
        status: str = "active",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        reviewed: str = "all",
    ) -> dict:
        return await self._stars().list_stars(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            reviewed=reviewed,
        )

    async def search_stars(
        self,
        query: str = "",
        session_tag: Optional[str] = None,
        limit: int = 10,
        log_run: bool = False,
    ) -> dict:
        return await self._stars().search_stars(
            query=query,
            session_tag=session_tag,
            limit=limit,
            log_run=log_run,
        )

    async def star_review(
        self,
        limit_new: Optional[int] = None,
        candidates_per_star: Optional[int] = None,
        total_candidate_limit: Optional[int] = None,
        session_tag: Optional[str] = None,
    ) -> dict:
        return await self._stars().review(
            limit_new=limit_new,
            candidates_per_star=candidates_per_star,
            total_candidate_limit=total_candidate_limit,
            session_tag=session_tag,
        )

    async def star_feedback(
        self,
        feedback: Any = None,
        run_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        candidate_star_id: Optional[str] = None,
        expected_star_id: Optional[str] = None,
        scored_by: str = "沈予",
        note: str = "",
        metadata: Optional[dict[str, Any]] = None,
        items: Optional[list[dict[str, Any]]] = None,
    ) -> dict:
        return await self._stars().feedback(
            feedback=feedback,
            run_id=run_id,
            candidate_id=candidate_id,
            candidate_star_id=candidate_star_id,
            expected_star_id=expected_star_id,
            scored_by=scored_by,
            note=note,
            metadata=metadata,
            items=items,
        )

    async def connect_constellation(
        self,
        star_ids: Any,
        name: str = "",
        relation_type: str = "constellation",
        scored_by: str = "沈予",
        note: str = "",
    ) -> dict:
        return await self._stars().connect_constellation(
            star_ids=star_ids,
            name=name,
            relation_type=relation_type,
            scored_by=scored_by,
            note=note,
        )

    async def mark_constant_star(self, star_id: str, is_constant: bool = True) -> dict:
        return await self._stars().mark_constant(star_id, is_constant=is_constant)

    async def archive_star(self, star_id: str) -> dict:
        return await self._stars().archive_star(star_id)

    async def merge_stars(self, source_ids: list, *, content: str = "", chord: str = "", is_constant: bool = False, metadata: dict | None = None) -> dict:
        return await self._stars().merge_stars(source_ids, content=content, chord=chord, is_constant=is_constant, metadata=metadata)

    async def supabase_insert(self, table: str, data: dict) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            result = await self.supabase.insert(table, data)
            return {"ok": True, "table": table, "row": result, "result": result}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_update(self, table: str, match: dict, data: dict, operators: Optional[dict] = None, column: Optional[str] = None) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            params = self._build_supabase_filter_params(match, operators, column=column)
            if not params:
                return {"ok": False, "error": "supabase_update requires match or operators to avoid updating the whole table."}
            result = await self.supabase.update(table, params, data)
            return {
                "ok": True,
                "table": table,
                "affected": len(result) if isinstance(result, list) else 0,
                "rows": result,
            }
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_delete(self, table: str, match: dict, hard: bool = False, operators: Optional[dict] = None, column: Optional[str] = None) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            params = self._build_supabase_filter_params(match, operators, column=column)
            if not params:
                return {"ok": False, "error": "supabase_delete requires match or operators to avoid deleting the whole table."}
            if hard:
                result = await self.supabase.delete(table, params)
                return {
                    "ok": True,
                    "table": table,
                    "mode": "hard_delete",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }

            try:
                result = await self.supabase.update(table, params, {"is_deleted": True})
                return {
                    "ok": True,
                    "table": table,
                    "mode": "soft_delete",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }
            except Exception:
                result = await self.supabase.delete(table, params)
                return {
                    "ok": True,
                    "table": table,
                    "mode": "hard_delete_fallback",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def ask_memory(
        self,
        query: str,
        session_tag: Optional[str],
        limit: int = 8,
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        if date:
            date_from = date_to = date
        has_date_filter = bool(date_from or date_to)
        try:
            safe_limit = int(limit or 8)
        except (TypeError, ValueError):
            safe_limit = 8
        result = await self.recall(
            query=query,
            source_types=["memory"],
            session_tag=session_tag,
            date_from=date_from,
            date_to=date_to,
            include_undated=not has_date_filter,
            limit=max(1, min(safe_limit, 20)),
        )
        items = result.get("items") if isinstance(result.get("items"), list) else []
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", "memory recall failed"),
                "query": query,
                "count": 0,
                "items": [],
                "memories": [],
                "source": "shenyu_recall",
                "source_types": ["memory"],
            }
        return {
            **result,
            "query": query,
            "count": len(items),
            "items": items,
            "memories": items,
            "source": "shenyu_recall",
            "source_types": ["memory"],
            "compat_note": "shenyu_ask_memory now delegates to shenyu_recall with source_types=['memory'].",
        }

    async def read_heartbeat(
        self,
        session_tag: Optional[str],
        limit: int = 10,
        state: str = "all",
        order: str = "desc",
        scope: str = "auto",
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
    ) -> dict:
        if self.store is None:
            return {"ok": False, "items": [], "note": "Gateway store is not configured."}
        resolved_tag = (session_tag or "default").strip() or "default"

        state = (state or "all").strip().lower()
        if state not in {"all", "pending", "injected"}:
            state = "all"
        order = "asc" if (order or "").strip().lower() == "asc" else "desc"
        if date:
            date_from = date_to = date
        created_from = date_from or created_from
        created_to = date_to or created_to
        created_start, created_end = _date_range_bounds(created_from, created_to)
        target_session = self.store.get_session_by_tag(resolved_tag)
        scope_key = (scope or "auto").strip().lower()
        if scope_key in {"hisense", "海信"}:
            read_hisense = True
            resolved_scope = "hisense"
        elif scope_key in {"normal", "global", "default", "普通", "默认"}:
            read_hisense = False
            resolved_scope = "normal"
        else:
            read_hisense = _is_hisense_session(target_session, runtime_config=self.cfg)
            resolved_scope = "hisense" if read_hisense else "normal"
        items = self.store.read_heartbeats(
            None,
            state=state,
            limit=max(1, min(int(limit or 10), 100)),
            order=order,
            created_from=created_start,
            created_to=created_end,
            hisense=read_hisense,
        )
        for item in items:
            item["state"] = "injected" if item.get("injected_at") else "pending"
        latest_digest = "\n".join(reversed([item.get("content") or "" for item in items[:5]])) if order == "desc" else "\n".join(item.get("content") or "" for item in items[:5])
        return {
            "ok": True,
            "session_tag": resolved_tag,
            "scope": resolved_scope,
            "scope_requested": scope_key,
            "state": state,
            "order": order,
            "date": date,
            "date_from": date_from,
            "date_to": date_to,
            "count": len(items),
            "items": items,
            "latest_digest": latest_digest,
        }

    async def surface_passages(self, query: str, session_tag: Optional[str], limit: int = 3) -> dict:
        candidates = await self._collect_primary_text_candidates(
            session_tag=session_tag,
            categories={"room", "message_board"},
        )
        scored = []
        for item in candidates:
            score = self._score_passage(query, item)
            if score <= 0:
                continue
            probability = _clamp(score * item.get("novelty_modifier", 1.0), 0.15, 0.95)
            rolled = random.random() <= probability
            if not rolled:
                continue
            scored.append(
                {
                    **item,
                    "score": round(score, 3),
                    "probability": round(probability, 3),
                    "why": self._why_passage(query, item, score),
                }
            )

        scored.sort(key=lambda row: row["score"], reverse=True)
        passages = scored[: max(1, min(limit, 8))]
        return {"ok": True, "query": query, "count": len(passages), "passages": passages}

    async def search_primary_texts(
        self,
        query: str,
        categories: Any = None,
        session_tag: Optional[str] = None,
        limit: int = 5,
    ) -> dict:
        selected = self._normalize_primary_categories(categories, default={"diary", "letter", "paper"})
        source_types = self._primary_categories_to_recall_source_types(selected)
        try:
            safe_limit = int(limit or 5)
        except (TypeError, ValueError):
            safe_limit = 5
        result = await self.recall(
            query=query,
            source_types=source_types,
            session_tag=session_tag,
            limit=max(1, min(max(safe_limit * 3, safe_limit), 30)),
        )
        items = result.get("items") if isinstance(result.get("items"), list) else []
        requested_limit = max(1, min(safe_limit, 20))
        passages = [
            passage
            for passage in (self._recall_item_to_primary_passage(item) for item in items)
            if self._primary_passage_matches_categories(passage, selected)
        ][:requested_limit]
        return {
            "ok": bool(result.get("ok")),
            "query": query,
            "categories": sorted(selected),
            "source": "shenyu_recall",
            "source_types": source_types,
            "count": len(passages),
            "passages": passages,
            **({"error": result.get("error")} if not result.get("ok") and result.get("error") else {}),
        }

    async def add_calendar(
        self,
        content: str,
        period_key: Optional[str] = None,
        period_type: str = "day",
        title: str = "",
        summary: str = "",
        digest: str = "",
        author: str = "沈予",
        mode: str = "append",
    ) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        body = (content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required."}

        period_type = (period_type or "day").strip().lower()
        if period_type not in {"day", "week", "month"}:
            return {"ok": False, "error": "Unsupported period_type."}
        period_key = (period_key or default_period_key(period_type)).strip()
        start, end = period_bounds(period_type, period_key)
        author = (author or "沈予").strip() or "沈予"
        title = (title or "").strip() or f"{period_key} 手写日历"
        summary = (summary or "").strip()
        digest = (digest or "").strip() or summary or _shorten(body, 180)
        mode = (mode or "append").strip().lower()
        if mode not in {"append", "replace"}:
            mode = "append"

        rows = await self._safe_query(
            "calendar_pages",
            {
                "select": "*",
                "period_type": f"eq.{period_type}",
                "period_key": f"eq.{period_key}",
                "order": "version.desc",
                "limit": "1",
            },
        )
        current = rows[0] if rows else None

        if current:
            old_content = (current.get("content") or "").strip()
            if mode == "append" and old_content:
                merged = old_content + "\n\n---\n\n" + body
            else:
                merged = body
            meta = _safe_json_loads(current.get("meta"), {})
            meta["manual_calendar_writes"] = int(meta.get("manual_calendar_writes") or 0) + 1
            meta["latest_manual_write_at"] = _iso_now()
            page_payload = {
                "period_type": period_type,
                "period_key": period_key,
                "period_start": current.get("period_start") or start.isoformat(),
                "period_end": current.get("period_end") or end.isoformat(),
                "version": int(current.get("version") or 1) + 1,
                "is_latest": True,
                "title": title,
                "content": merged,
                "summary": summary,
                "digest": digest,
                "author": author,
                "source_model": "manual-calendar",
                "source_refs": current.get("source_refs") or "[]",
                "session_tags": current.get("session_tags") or "[]",
                "meta": _json_dumps(meta),
                "status": current.get("status") or "final",
                "prompt_snapshot": current.get("prompt_snapshot") or "",
                "generated_by": "manual",
            }
        else:
            page_payload = {
                "period_type": period_type,
                "period_key": period_key,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "version": 1,
                "is_latest": True,
                "title": title,
                "content": body,
                "summary": summary,
                "digest": digest,
                "author": author,
                "source_model": "manual-calendar",
                "source_refs": "[]",
                "session_tags": "[]",
                "meta": _json_dumps({"manual_calendar_writes": 1, "latest_manual_write_at": _iso_now()}),
                "status": "final",
                "prompt_snapshot": "",
                "generated_by": "manual",
            }

        if current and current.get("id"):
            await self.supabase.update("calendar_pages", {"id": current.get("id")}, {"is_latest": False})

        page = await self.supabase.insert("calendar_pages", page_payload)
        return {
            "ok": True,
            "period_type": period_type,
            "period_key": period_key,
            "mode": mode if current else "new",
            "page": page,
            "digest": digest,
        }



    async def last_seen(self) -> Any:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        try:
            return await self.supabase.rpc("last_seen")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def meta_summaries(self) -> Any:
        if not self.supabase:
            return []
        try:
            return await self.supabase.rpc("get_meta_summaries")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def recall_main_thread(self, since: Optional[str], until: Optional[str], query: Optional[str], limit: int) -> dict:
        if not self.store:
            return {"ok": False, "error": "Store not available"}
        limit = max(1, min(int(limit or 10), 30))
        all_sessions = self.store.list_sessions(limit=50)
        non_hisense = [s for s in all_sessions if not _is_hisense_session(s, runtime_config=self.cfg)]
        if not non_hisense:
            return {"ok": True, "count": 0, "data": []}
        target = non_hisense[0]
        msgs = self.store.get_recent_dialogue_messages(target["id"], limit=limit * 3)
        if since:
            msgs = [m for m in msgs if (m.get("created_at") or "") >= since]
        if until:
            msgs = [m for m in msgs if (m.get("created_at") or "") <= until]
        if query and query.strip():
            keyword = query.strip().lower()
            msgs = [m for m in msgs if keyword in (m.get("content") or "").lower()]
        msgs = msgs[-limit:]
        data = [{"role": m["role"], "content": (m.get("content") or "")[:500], "at": m.get("created_at")} for m in msgs]
        return {"ok": True, "session_tag": target.get("session_tag"), "count": len(data), "data": data}

    async def windowsill_write(self, content: Any, title: Any = "", mood: Any = "") -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured.", "error_kind": "config"}
        body = str(content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required.", "error_kind": "validation"}
        payload = {
            "content": body,
            "title": str(title or "").strip(),
            "mood": str(mood or "").strip(),
        }
        try:
            row = await self.supabase.insert(WINDOWSILL_TABLE, payload)
            if isinstance(row, dict):
                try:
                    index_result = await self._recall_index().index_windowsill_row(row)
                    if not index_result.get("ok"):
                        logger.warning("[Windowsill] Recall indexing skipped: %s", index_result.get("error"))
                except Exception as exc:
                    logger.warning("[Windowsill] Recall indexing failed: %s", exc)
            return {"ok": True, "data": row}
        except Exception as exc:
            return {
                "ok": False,
                "error": self._friendly_supabase_error(WINDOWSILL_TABLE, exc),
                "error_kind": "exception",
            }

    async def windowsill_list(self, mood: Any = "", limit: int = 10) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured.", "error_kind": "config"}
        params = {
            "select": "id,content,title,mood,created_at",
            "order": "created_at.desc",
            "limit": str(max(1, min(int(limit or 10), 50))),
        }
        mood_key = str(mood or "").strip()
        if mood_key:
            params["mood"] = f"eq.{mood_key}"
        try:
            rows = await self.supabase.query(WINDOWSILL_TABLE, params)
            return {"ok": True, "count": len(rows or []), "data": rows or []}
        except Exception as exc:
            return {
                "ok": False,
                "error": self._friendly_supabase_error(WINDOWSILL_TABLE, exc),
                "error_kind": "exception",
            }

    def _notebook_scope(self, scope: Optional[str]) -> str:
        raw = str(scope or "shared").strip().lower()
        if raw in {"hisense", "海信"}:
            return "hisense"
        if raw in {"handoff", "交接"}:
            return "handoff"
        return "shared"

    def _notebook_tags(self, tags: Optional[Any], scope: Optional[str]) -> list[str]:
        result: list[str] = []

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)

        if isinstance(tags, str):
            for item in re.split(r"[,，\s]+", tags):
                add(item)
        elif isinstance(tags, list):
            for item in tags:
                add(item)
        elif tags:
            add(tags)

        scope_key = self._notebook_scope(scope)
        if scope_key == "hisense":
            add("hisense")
        elif scope_key == "handoff":
            add("handoff")
            add("hisense")
        return result

    def _notebook_filter_tag(self, tag: Optional[Any], scope: Optional[str]) -> str:
        explicit = str(tag or "").strip()
        if explicit:
            return explicit.replace("{", "").replace("}", "").replace(",", "")
        scope_key = self._notebook_scope(scope)
        if scope_key == "hisense":
            return "hisense"
        if scope_key == "handoff":
            return "handoff"
        return ""

    def _notebook_metadata(self, metadata: Optional[dict], scope: Optional[str]) -> dict:
        data = dict(metadata) if isinstance(metadata, dict) else {}
        scope_key = self._notebook_scope(scope)
        if scope_key != "shared":
            data.setdefault("scope", scope_key)
        return data

    async def notebook_list(self, type_filter: Optional[str], status: str, limit: int, tag: Optional[str] = None, scope: Optional[str] = None) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase not configured"}
        limit = max(1, min(int(limit or 10), 20))
        status_key = (status or "active").strip().lower()
        params: dict[str, str] = {
            "order": "pinned.desc,updated_at.desc",
            "limit": str(limit),
            "select": "id,type,content,tags,status,pinned,metadata,created_at,updated_at",
        }
        if status_key and status_key != "all":
            params["status"] = f"eq.{status_key}"
        if type_filter:
            params["type"] = f"eq.{type_filter}"
        filter_tag = self._notebook_filter_tag(tag, scope)
        if filter_tag:
            params["tags"] = f"cs.{{{filter_tag}}}"
        try:
            rows = await self.supabase.query("shenyu_notebook", params)
            return {"ok": True, "count": len(rows or []), "data": rows or []}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def notebook_write(self, type_: Optional[str], content: str, tags: Optional[list], metadata: Optional[dict], session_tag: Optional[str], scope: Optional[str] = None) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase not configured"}
        body = (content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required"}
        scope_key = self._notebook_scope(scope)
        note_type = (type_ or "").strip() or ("handoff" if scope_key == "handoff" else "note")
        data: dict[str, Any] = {"type": note_type, "content": body, "status": "active"}
        normalized_tags = self._notebook_tags(tags, scope_key)
        if normalized_tags:
            data["tags"] = normalized_tags
        normalized_metadata = self._notebook_metadata(metadata, scope_key)
        if normalized_metadata:
            data["metadata"] = normalized_metadata
        if session_tag:
            data["session_tag"] = session_tag
        try:
            result = await self.supabase.insert("shenyu_notebook", data)
            return {"ok": True, "data": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def notebook_update(self, id_: str, content: Optional[str], status: Optional[str], tags: Optional[list], type_: Optional[str], pinned: Optional[bool], metadata: Optional[dict]) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase not configured"}
        if not id_:
            return {"ok": False, "error": "id is required"}
        update_data: dict[str, Any] = {}
        if content is not None:
            update_data["content"] = content
        if status is not None:
            update_data["status"] = status
        if tags is not None:
            update_data["tags"] = tags
        if type_ is not None:
            update_data["type"] = type_
        if pinned is not None:
            update_data["pinned"] = pinned
        if metadata is not None:
            update_data["metadata"] = metadata
        if not update_data:
            return {"ok": False, "error": "Nothing to update"}
        update_data["updated_at"] = _iso_now()
        try:
            result = await self.supabase.update("shenyu_notebook", match={"id": id_}, data=update_data)
            return {"ok": True, "data": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _primary_categories_to_recall_source_types(self, categories: set[str]) -> list[str]:
        source_types: list[str] = []
        if categories & {"diary", "letter", "paper", "lock", "annotation", "life_tick"}:
            source_types.append("journal")
        if "room" in categories:
            source_types.append("room")
        if "message_board" in categories:
            source_types.append("board")
        return source_types or ["journal"]

    def _recall_item_to_primary_passage(self, item: dict) -> dict:
        content = item.get("content") or ""
        event_date = item.get("event_date") or ""
        return {
            "source_table": item.get("source_table") or "",
            "title": item.get("title") or "untitled",
            "excerpt": _shorten(content, 260),
            "full_text": content,
            "created_at": event_date,
            "chunk_index": 0,
            "content_kind": item.get("content_kind") or item.get("source_type") or item.get("source_table") or "",
        }

    def _primary_passage_matches_categories(self, passage: dict, categories: set[str]) -> bool:
        journal_categories = {"diary", "letter", "paper", "lock", "annotation", "life_tick"}
        source_table = str(passage.get("source_table") or "").strip()
        content_kind = str(passage.get("content_kind") or "").strip()
        if source_table == "journal" or content_kind in journal_categories or content_kind == "journal":
            journal_kind = content_kind if content_kind in journal_categories else "diary"
            return journal_kind in categories
        if source_table == "room" or content_kind == "room":
            return "room" in categories
        if source_table == "message_board" or content_kind in {"board", "message"}:
            return "message_board" in categories
        return True

    def _normalize_primary_categories(self, categories: Any, default: set[str]) -> set[str]:
        supported = {"diary", "letter", "paper", "lock", "annotation", "life_tick", "room", "message_board"}
        if categories is None:
            return set(default)
        if isinstance(categories, str):
            raw_items = re.split(r"[,，\s]+", categories.strip())
        elif isinstance(categories, list):
            raw_items = [str(item) for item in categories]
        else:
            raw_items = []
        normalized = {item.strip().lower() for item in raw_items if item and item.strip()}
        if not normalized:
            return set(default)
        if "all" in normalized:
            return set(supported)
        if "journal" in normalized:
            normalized.update({"diary", "letter", "paper", "lock", "annotation", "life_tick"})
            normalized.discard("journal")
        return {item for item in normalized if item in supported} or set(default)

    async def _collect_primary_text_candidates(self, session_tag: Optional[str], categories: Optional[set[str]] = None) -> list[dict]:
        if not self.supabase:
            return []

        selected = categories or {"diary", "letter", "paper", "room", "message_board"}
        journal_categories = selected & {"diary", "letter", "paper", "lock", "annotation", "life_tick"}
        items: list[dict] = []

        if journal_categories:
            journal_rows = await self._safe_query(
                "journal",
                {"order": "created_at.desc", "limit": "32", "select": "id,title,content,created_at,category,mood,session_tag"},
            )
            for row in journal_rows:
                category = row.get("category") or "diary"
                if category not in journal_categories:
                    continue
                source_kind = f"journal:{category}"
                items.extend(
                    self._row_to_chunks(
                        source_kind,
                        row,
                        row.get("title"),
                        row.get("content"),
                        row.get("created_at"),
                        category=category,
                    )
                )

        if "room" in selected:
            room_params = {"order": "updated_at.desc", "limit": "8", "select": "id,title,content,updated_at,status,visibility,session_tag"}
            if session_tag:
                room_params["or"] = f"(session_tag.eq.{session_tag},visibility.eq.open,visibility.eq.self)"
            room_rows = await self._safe_query("room", room_params)
            for row in room_rows:
                items.extend(self._row_to_chunks("room", row, row.get("title"), row.get("content"), row.get("updated_at"), category="room"))

        if "message_board" in selected:
            board_rows = await self._safe_query(
                "message_board",
                {"order": "created_at.desc", "limit": "10", "select": "id,sender,content,created_at"},
            )
            for row in board_rows:
                items.append(
                    {
                        "source_table": "message_board",
                        "source_id": row.get("id"),
                        "title": f"Message from {row.get('sender', 'unknown')}",
                        "excerpt": _shorten(row.get("content") or "", 260),
                        "full_text": row.get("content") or "",
                        "created_at": row.get("created_at"),
                        "chunk_index": 0,
                        "content_kind": "message",
                        "base_salience": 0.55,
                        "novelty_modifier": 1.0,
                    }
                )

        return items

    def _row_to_chunks(
        self,
        source_table: str,
        row: dict,
        title: Optional[str],
        content: Optional[str],
        created_at: Optional[str],
        category: Optional[str] = None,
    ) -> list[dict]:
        chunks = _split_paragraph_chunks(content or "")
        if not chunks and content:
            chunks = [content]

        items = []
        for idx, chunk in enumerate(chunks):
            base = self._base_salience_for_source(source_table, category)
            if idx == 0:
                base += 0.04
            items.append(
                {
                    "source_table": source_table.split(":")[0],
                    "source_id": row.get("id"),
                    "title": title or "untitled",
                    "excerpt": _shorten(chunk, 260),
                    "full_text": chunk,
                    "created_at": created_at,
                    "chunk_index": idx,
                    "content_kind": category or source_table,
                    "base_salience": base,
                    "novelty_modifier": 1.0,
                }
            )
        return items

    def _score_passage(self, query: str, item: dict) -> float:
        keyword_score = _keyword_overlap_score(query, item.get("title", "") + "\n" + item.get("full_text", ""))
        recency_score = self._recency_score(item.get("created_at"))
        length_bonus = 0.08 if 80 <= len(item.get("full_text", "")) <= 340 else 0.0
        body_bonus = self._body_bonus_for_item(item)
        return _clamp(item.get("base_salience", 0.5) * 0.45 + keyword_score * 0.35 + recency_score * 0.12 + body_bonus + length_bonus, 0.0, 1.0)

    def _why_passage(self, query: str, item: dict, score: float) -> list[str]:
        reasons = []
        if _keyword_overlap_score(query, item.get("title", "") + "\n" + item.get("full_text", "")) >= 0.4:
            reasons.append("theme overlap")
        content_kind = item.get("content_kind")
        if content_kind in {"room", "diary"}:
            reasons.append("core primary text")
        elif item.get("source_table") == "message_board":
            reasons.append("conversation-adjacent text")
        elif content_kind in {"letter", "paper"}:
            reasons.append("secondary primary text")
        if self._recency_score(item.get("created_at")) >= 0.6:
            reasons.append("recent enough to feel alive")
        if score >= 0.75:
            reasons.append("strong surfaced match")
        return reasons or ["soft surfaced match"]

    def _base_salience_for_source(self, source_table: str, category: Optional[str]) -> float:
        if category == "room":
            return 0.83
        if category == "diary":
            return 0.82
        if category == "letter":
            return 0.72
        if category == "paper":
            return 0.72
        if source_table == "room":
            return 0.83
        if source_table == "message_board":
            return 0.76
        return 0.64

    def _body_bonus_for_item(self, item: dict) -> float:
        content_kind = item.get("content_kind")
        if content_kind in {"room", "diary"}:
            return 0.13
        if item.get("source_table") == "message_board":
            return 0.11
        if content_kind == "letter":
            return 0.08
        if content_kind == "paper":
            return 0.08
        return 0.05

    def _recency_score(self, created_at: Optional[str]) -> float:
        dt = _parse_ts(created_at)
        if not dt:
            return 0.2
        days = max((_now() - dt).days, 0)
        if days <= 1:
            return 1.0
        if days <= 3:
            return 0.8
        if days <= 7:
            return 0.65
        if days <= 14:
            return 0.45
        return 0.25

    async def _safe_query(self, table: str, params: dict) -> list:
        if not self.supabase:
            return []
        try:
            return await self.supabase.query(table, params)
        except Exception:
            return []

    _SUPABASE_FILTER_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in", "ov", "not"}

    def _build_supabase_filter_params(self, filters: Any = None, operators: Any = None, column: Optional[str] = None) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = []
        for key, value in self._normalize_filters(filters).items():
            if isinstance(value, dict) and self._looks_like_operator_map(value):
                params.extend(self._build_supabase_operator_params({key: value}))
            else:
                params.append((key, self._parse_filter_value(value)))
        params.extend(self._build_supabase_operator_params(self._normalize_operator_shape(operators, column=column)))
        return params

    def _build_supabase_operator_params(self, operators: Any) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = []
        for column, conditions in self._normalize_filters(operators).items():
            if not isinstance(conditions, dict):
                params.append((column, self._parse_filter_value(conditions)))
                continue
            for op, value in conditions.items():
                parsed = self._parse_operator_condition(str(op), value)
                if parsed:
                    params.append((column, parsed))
        return params

    def _normalize_operator_shape(self, operators: Any, column: Optional[str] = None) -> dict:
        parsed = self._normalize_filters(operators)
        if not parsed:
            return {}
        if self._looks_like_operator_map(parsed):
            return {(column or "created_at"): parsed}
        return parsed

    def _parse_operator_condition(self, op: str, value: Any) -> str:
        normalized = op.strip().lower().replace("_", ".").replace(" ", ".")
        if normalized in {"not.null", "not.is.null", "is.not.null"}:
            return "not.is.null"
        if normalized in {"not.true", "not.is.true", "is.not.true"}:
            return "not.is.true"
        if normalized in {"not.false", "not.is.false", "is.not.false"}:
            return "not.is.false"
        if normalized in {"is.null", "null"}:
            return "is.null"
        if normalized.startswith("not."):
            inner = normalized.removeprefix("not.")
            if inner in {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in"}:
                return f"not.{inner}.{self._format_supabase_filter_value(inner, value)}"
        if normalized not in self._SUPABASE_FILTER_OPS:
            return ""
        return f"{normalized}.{self._format_supabase_filter_value(normalized, value)}"

    def _looks_like_operator_map(self, value: dict) -> bool:
        return any(self._parse_operator_condition(str(op), operand) for op, operand in value.items())

    def _parse_filter_value(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return "eq." + self._format_supabase_filter_value("eq", value)
        raw = str(value)
        for op in self._SUPABASE_FILTER_OPS:
            if raw.startswith(op + "."):
                return raw
        return "eq." + raw

    def _format_supabase_filter_value(self, op: str, value: Any) -> str:
        if op == "in":
            if isinstance(value, (list, tuple, set)):
                return "(" + ",".join(str(item) for item in value) + ")"
            raw = str(value)
            return raw if raw.startswith("(") and raw.endswith(")") else f"({raw})"
        if op == "is" and value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _normalize_filters(self, filters: Any) -> dict:
        if filters is None:
            return {}
        if isinstance(filters, str):
            text = filters.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return filters if isinstance(filters, dict) else {}

    def _supabase_table_hint(self, table: str) -> str:
        normalized = (table or "").strip().lower()
        if normalized in {"heartbeat", "heartbeats", "heartbeat_entries", "gateway_heartbeats"}:
            return "heartbeat_entries lives in the gateway SQLite store, not Supabase. Use shenyu_read_heartbeat（日常）or room_wooden_box（room 模式）instead."
        if normalized in {"gateway_messages", "request_context_snapshots", "raw_request_windows"}:
            return f"{normalized} lives in the gateway SQLite store, not Supabase."
        return ""

    def _friendly_supabase_error(self, table: str, exc: Exception) -> str:
        raw = str(exc)
        if "404" in raw:
            hint = self._supabase_table_hint(table)
            if hint:
                return hint
            return f"Supabase table '{table}' was not found. Check the table name with shenyu_supabase_guide, or use a dedicated shenyu_* tool if this data lives in the gateway store."
        return raw

    async def _boost_memory(self, memory_id: str):
        if not self.supabase:
            return
        try:
            await self.supabase.rpc("boost_memory", {"memory_uuid": memory_id})
        except Exception:
            return
