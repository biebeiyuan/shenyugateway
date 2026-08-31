from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

from shenyu_gateway.recall import (
    DEFAULT_RECALL_LIMIT,
    MAX_RECALL_LIMIT,
    PUBLIC_RECALL_SOURCE_TYPES,
    classify_recall_mode,
    recall_terms,
)
from shenyu_gateway.runtime import logger
from shenyu_gateway.utils import shorten as _shorten

from ._helpers import _keyword_overlap_score

# `source_table` 是 Supabase 里表叫什么（`shenyu_album_notes` 这种）。Admin 的
# 记忆网络拿它和 source_id 拼源的唯一键，所以服务层必须照旧返回；但沈予不需要
# 知道库里的表名，他要的是「这条从哪来」——那是 `source_type`，也正是
# `shenyu_recall_read` 的参数名，两步之间对得上。
_INTERNAL_RECALL_FIELDS = ("source_table",)


def _for_shenyu(item: Any) -> Any:
    """一条命中给沈予的那份：去掉只有 Admin 用得上的内部字段。"""
    if not isinstance(item, dict):
        return item
    return {key: value for key, value in item.items() if key not in _INTERNAL_RECALL_FIELDS}


class RecallToolsMixin:
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
                companion_candidates.append((float(star.get("score") or 0.0), self._recall_star_item(star, full=True)))
        mem_result = results.get("mem_note")
        if isinstance(mem_result, dict) and mem_result.get("items"):
            for note in mem_result["items"]:
                companion_candidates.append(
                    (self._mem_note_recall_confidence(note), self._recall_mem_note_item(note, full=True))
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
        return {"ok": True, "count": len(combined), "items": [_for_shenyu(item) for item in combined]}

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
            rows = self.store.read_heartbeats(None, limit=500, order="desc")
            match = next((row for row in rows if str(row.get("id") or "") == item_id), None)
            if match:
                return {"ok": True, "item": self._recall_heartbeat_item(match, full=True)}
        # 索引那条路走 `_public_item`，所以这里也要收窄——recall 和 recall_read
        # 是同一轮里的两步，两步返回的形状不一致会让他多猜一次。
        result = await self._recall_index().read_source(source, item_id, session_tag=session_tag)
        if isinstance(result, dict) and isinstance(result.get("item"), dict):
            result = {**result, "item": _for_shenyu(result["item"])}
        return result

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
        rows = self.store.read_heartbeats(None, state="all", limit=100, order="desc")
        scored: list[tuple[float, dict[str, Any]]] = []
        query_lower = (query or "").strip().lower()
        for row in rows:
            content = str(row.get("content") or "")
            score = _keyword_overlap_score(query, content)
            if query_lower and query_lower in content.lower():
                score = min(1.0, score + 0.2)
            if score <= 0:
                continue
            item = self._recall_heartbeat_item(row, full=True)
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
                "content": content,
                "source_id": str(row.get("id") or ""),
                "source_type": "chat",
                "source_table": "shenyu_chat_archive",
                "content_kind": row.get("role") or "message",
                "event_date": row.get("event_at") or row.get("archived_at") or "",
                "has_more": False,
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
