from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shenyu_gateway.calendar import default_period_key, period_bounds
from shenyu_gateway.mem_notes import MemNoteService
from shenyu_gateway.recall import RecallIndexService, recall_terms
from shenyu_gateway.runtime import (
    iso_now as _iso_now,
    json_dumps as _json_dumps,
    logger,
    now as _now,
    parse_ts as _parse_ts,
)

_UNSET = object()


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


def _shorten(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


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
想一口气处理剩下的 captured，用 `shenyu_bulk_update_mem_notes(source_status="captured", use_suggestions=true, patch={"status":"active"})`。
notebook 是共享手边事项；海信那边或跨窗口要留事用 `shenyu_notebook_write` / `shenyu_notebook_list`。
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

    def _recall_index(self) -> RecallIndexService:
        return RecallIndexService(self.supabase, cfg=self.cfg)

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
        session_tag: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_undated: bool = True,
        limit: int = 8,
        auto_sync: Optional[bool] = None,
    ) -> dict:
        return await self._recall_index().recall(
            query=query,
            source_types=self._recall_source_types(source_types),
            session_tag=session_tag,
            date_from=date_from,
            date_to=date_to,
            include_undated=include_undated,
            limit=limit,
            auto_sync=auto_sync,
        )

    async def rebuild_recall_index(self, source_types: Any = None) -> dict:
        return await self._recall_index().rebuild(self._recall_source_types(source_types))

    async def search_mem_notes(
        self,
        query: str = "",
        session_tag: Optional[str] = None,
        limit: int = 30,
        status: str = "all",
        mem_type: Optional[str] = None,
    ) -> dict:
        return await self._mem_notes().list_notes(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=query,
            mem_type=mem_type,
        )

    async def list_mem_notes(
        self,
        status: str = "captured",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        mem_type: Optional[str] = None,
    ) -> dict:
        return await self._mem_notes().list_notes(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            mem_type=mem_type,
        )

    async def write_mem_note(
        self,
        content: str,
        session_tag: Optional[str] = None,
        mem_type: Optional[str] = None,
        trigger_text: Any = "",
        trigger_keywords: Any = None,
        status: str = "active",
        cooldown_hours: Any = None,
        review_note: Any = "",
        replaces: Optional[list[Any]] = None,
    ) -> dict:
        return await self._mem_notes().create_note(
            content=content,
            session_tag=session_tag,
            mem_type=mem_type,
            trigger_text=trigger_text,
            trigger_keywords=trigger_keywords,
            status=status,
            cooldown_hours=cooldown_hours,
            review_note=review_note,
            replaces=replaces,
        )

    async def update_mem_note(self, note_id: str, patch: dict[str, Any]) -> dict:
        return await self._mem_notes().update_note(note_id, patch)

    async def bulk_update_mem_notes(
        self,
        ids: Optional[list[Any]] = None,
        patch: Optional[dict[str, Any]] = None,
        updates: Optional[list[dict[str, Any]]] = None,
        use_suggestions: bool = False,
        source_status: Optional[str] = None,
        exclude_ids: Optional[list[Any]] = None,
    ) -> dict:
        return await self._mem_notes().bulk_update_notes(
            ids=ids,
            patch=patch,
            updates=updates,
            use_suggestions=use_suggestions,
            source_status=source_status,
            exclude_ids=exclude_ids,
        )

    async def delete_mem_note(self, note_id: str) -> dict:
        return await self._mem_notes().delete_note(note_id)

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
        if not self.supabase:
            return {
                "ok": False,
                "error": "Supabase is not configured.",
                "query": query,
                "count": 0,
                "memories": [],
                "note": "Supabase is not configured.",
            }

        query_text = query or ""
        params: list[tuple[str, str]] = [
            ("is_deleted", "eq.false"),
            ("order", "weight.desc,date.desc"),
            ("limit", str(max(1, min(limit, 20)))),
            ("select", "id,title,date,summary,facts,emotional_context"),
        ]
        if query_text.strip() and query_text.strip() != "*":
            escaped = query_text.replace(",", " ").replace("(", " ").replace(")", " ")
            params.append((
                "or",
                f"(title.ilike.*{escaped}*,summary.ilike.*{escaped}*,"
                f"facts.ilike.*{escaped}*,emotional_context.ilike.*{escaped}*)"
            ))
        if date:
            params.append(("date", f"eq.{date}"))
        else:
            if date_from:
                params.append(("date", f"gte.{date_from}"))
            if date_to:
                params.append(("date", f"lte.{date_to}"))
        if session_tag:
            params.append(("session_tag", f"eq.{session_tag}"))

        try:
            memories = await self.supabase.query("memories", params)
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "query": query,
                "count": 0,
                "memories": [],
            }

        cards = []
        for memory in memories:
            memory_id = memory.get("id")
            cards.append(
                {
                    "title": memory.get("title"),
                    "date": memory.get("date"),
                    "summary": memory.get("summary"),
                    "facts": memory.get("facts"),
                    "emotional_context": memory.get("emotional_context"),
                }
            )

            if memory_id:
                await self._boost_memory(memory_id)

        return {
            "ok": True,
            "query": query,
            "count": len(cards),
            "memories": cards,
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
        candidates = await self._collect_primary_text_candidates(
            session_tag=session_tag,
            categories=selected,
        )
        scored = []
        for item in candidates:
            score = self._score_passage(query, item)
            if score <= 0:
                continue
            scored.append(
                {
                    **item,
                    "score": round(score, 3),
                    "why": self._why_passage(query, item, score),
                }
            )

        scored.sort(key=lambda row: row["score"], reverse=True)
        passages = scored[: max(1, min(int(limit or 5), 20))]
        return {
            "ok": True,
            "query": query,
            "categories": sorted(selected),
            "count": len(passages),
            "passages": passages,
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
                "content": body,
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

        page = await self.supabase.insert("calendar_pages", page_payload)
        return {
            "ok": True,
            "period_type": period_type,
            "period_key": period_key,
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
            return "heartbeat_entries lives in the gateway SQLite store, not Supabase. Use shenyu_read_heartbeat with date/date_from/date_to instead."
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
