from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Optional

from .runtime import iso_now, now as _now, parse_ts as _parse_ts


MEM_NOTE_TYPES = ("她为我做的事", "关于她的事实", "心里那一档", "承诺")
MEM_NOTE_STATUSES = ("captured", "active", "paused", "archived")


def _normalize_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(part for part in parts if part)
    return str(content)


def _terms(query: str) -> list[str]:
    raw = (query or "").replace("\n", " ")
    result: list[str] = []
    seen: set[str] = set()

    def add(term: str):
        term = term.strip().lower()
        if term and term not in seen:
            seen.add(term)
            result.append(term)

    for token in re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]+", raw):
        add(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            for size in (2, 3):
                for index in range(0, len(token) - size + 1):
                    add(token[index : index + size])
    return result


def _overlap(query: str, text: str) -> float:
    terms = _terms(query)
    if not terms:
        return 0.0
    haystack = (text or "").lower()
    hits = sum(1 for term in terms if term in haystack)
    return hits / max(len(terms), 1)


def _shorten(text: str, limit: int = 220) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


class MemNoteService:
    def __init__(self, cfg: Any, supabase_client: Any):
        self.cfg = cfg
        self.supabase = supabase_client

    async def process_inline_memories(
        self,
        session: dict,
        inline_memories: list[Any],
        assistant_text: str,
        source_model: str,
    ) -> dict[str, Any]:
        if not getattr(self.cfg, "enable_inline_memory_capture", False):
            return {"ok": False, "reason": "inline memory capture disabled."}
        if not self.supabase:
            return {"ok": False, "reason": "Supabase is not configured."}

        notes = [item for item in inline_memories if self._inline_note_content(item)]
        if not notes:
            return {"ok": False, "reason": "no inline memories."}

        inserted: list[str | None] = []
        discarded = 0
        for note in notes[:4]:
            payload = self._inline_note_to_row(note, session, assistant_text, source_model)
            if not payload:
                discarded += 1
                continue
            row = await self.supabase.insert("shenyu_mem_notes", payload)
            inserted.append(row.get("id") if isinstance(row, dict) else None)

        return {
            "ok": True,
            "inline_count": len(notes),
            "inserted_count": len([item for item in inserted if item]),
            "discarded_count": discarded,
        }

    async def search_notes(
        self,
        query: str,
        session_tag: Optional[str] = None,
        limit: int = 3,
        mark_triggered: bool = True,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "note": "Supabase is not configured."}
        query = (query or "").strip()
        if not query:
            return {"ok": True, "query": query, "count": 0, "items": []}

        params: dict[str, str] = {
            "status": "eq.active",
            "order": "updated_at.desc",
            "limit": "160",
            "select": (
                "id,session_tag,content,mem_type,trigger_text,trigger_keywords,status,"
                "cooldown_hours,last_triggered_at,trigger_count,source_model,created_at,updated_at"
            ),
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        rows = await self.supabase.query("shenyu_mem_notes", params)

        min_score = float(getattr(self.cfg, "mem_note_min_score", 0.45) or 0.45)
        scored: list[tuple[float, dict, list[str]]] = []
        for row in rows:
            if self._in_cooldown(row):
                continue
            score, reasons = self._score(query, row)
            if score >= min_score:
                scored.append((score, row, reasons))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[: max(1, min(int(limit or 3), 5))]
        items = [self._public_search_item(row, reasons) for _, row, reasons in selected]
        if mark_triggered and items:
            await self._mark_triggered([row for _, row, _ in selected])
        return {"ok": True, "query": query, "count": len(items), "items": items}

    async def list_notes(
        self,
        status: str = "captured",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        mem_type: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "items": [], "error": "Supabase is not configured."}
        status = self._status(status, fallback="captured", allow_all=True)
        params: dict[str, str] = {
            "order": "updated_at.desc",
            "limit": str(max(1, min(int(limit or 50), 200))),
            "select": (
                "id,session_tag,content,mem_type,trigger_text,trigger_keywords,status,"
                "cooldown_hours,last_triggered_at,trigger_count,source_model,source_session_id,"
                "source_excerpt,review_note,reviewed_at,created_at,updated_at"
            ),
        }
        if status != "all":
            params["status"] = f"eq.{status}"
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        if mem_type and mem_type in MEM_NOTE_TYPES:
            params["mem_type"] = f"eq.{mem_type}"
        rows = await self.supabase.query("shenyu_mem_notes", params)

        terms = _terms(q)
        if terms:
            rows = [
                row
                for row in rows
                if any(term in self._search_text(row).lower() for term in terms)
            ]
        return {"ok": True, "items": rows, "status": status, "count": len(rows)}

    async def update_note(self, note_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        current = await self._get_note(note_id)
        if not current:
            return {"ok": False, "error": "note not found."}
        update: dict[str, Any] = {}
        if "content" in patch:
            content = _normalize_text(patch.get("content")).strip()
            if not content:
                return {"ok": False, "error": "content is required."}
            update["content"] = content
        if "mem_type" in patch:
            update["mem_type"] = self._mem_type(patch.get("mem_type"), allow_empty=True)
        if "trigger_text" in patch:
            update["trigger_text"] = _normalize_text(patch.get("trigger_text")).strip()
        if "trigger_keywords" in patch:
            update["trigger_keywords"] = self._keyword_list(patch.get("trigger_keywords"))
        if "status" in patch:
            update["status"] = self._status(patch.get("status"), fallback="captured")
        if "cooldown_hours" in patch:
            update["cooldown_hours"] = self._int_range(patch.get("cooldown_hours"), 72, 0, 8760)
        if "review_note" in patch:
            update["review_note"] = _normalize_text(patch.get("review_note")).strip()
        if update:
            update["reviewed_at"] = iso_now()
        if not update:
            return {"ok": False, "error": "Nothing to update."}
        candidate = {**current, **update}
        active_error = self._active_validation_error(candidate)
        if active_error:
            return {"ok": False, "error": active_error}
        rows = await self.supabase.update("shenyu_mem_notes", {"id": note_id}, update)
        return {"ok": True, "note_id": note_id, "updated": rows}

    async def delete_note(self, note_id: str) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        rows = await self.supabase.delete("shenyu_mem_notes", {"id": note_id})
        return {"ok": True, "note_id": note_id, "deleted": rows}

    async def legacy_atomic_memories(
        self,
        limit: int = 30,
        session_tag: Optional[str] = None,
        q: str = "",
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "items": [], "error": "Supabase is not configured."}
        params: dict[str, str] = {
            "order": "created_at.desc",
            "limit": str(max(1, min(int(limit or 30), 100))),
            "select": (
                "id,session_tag,subject,owner,content_surface,quote,time_hint,memory_type,"
                "tier,importance,entities_json,tags_json,source_excerpt,source_model,status,created_at,updated_at"
            ),
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        rows = await self.supabase.query("atomic_memories", params)
        terms = _terms(q)
        if terms:
            rows = [
                row
                for row in rows
                if any(term in self._legacy_search_text(row).lower() for term in terms)
            ]
        return {"ok": True, "count": len(rows), "items": rows}

    def render_notes_for_context(self, notes: list[dict[str, Any]]) -> str:
        if not notes:
            return ""
        lines = ["## 你以前给自己留过"]
        for note in notes:
            mem_type = (note.get("mem_type") or "").strip()
            content = _shorten(note.get("content") or "", 260)
            if not content:
                continue
            if mem_type:
                lines.append(f"- {mem_type}：{content}")
            else:
                lines.append(f"- {content}")
        return "\n".join(lines)

    def _inline_note_content(self, note: Any) -> str:
        if isinstance(note, dict):
            content = _normalize_text(note.get("content")).strip()
        else:
            content = _normalize_text(note).strip()
        if not content:
            return ""
        if not re.sub(r"[\W_]+", "", content, flags=re.UNICODE):
            return ""
        return content

    def _inline_note_to_row(self, note: Any, session: dict, assistant_text: str, source_model: str) -> Optional[dict]:
        content = self._inline_note_content(note)
        if not content:
            return None
        return {
            "session_tag": session.get("session_tag") or "default",
            "content": content,
            "status": "captured",
            "cooldown_hours": int(getattr(self.cfg, "mem_note_default_cooldown_hours", 72) or 72),
            "source_model": f"inline-mem:{source_model}",
            "source_session_id": session.get("id"),
            "source_excerpt": _shorten(assistant_text, 600),
        }

    def _score(self, query: str, row: dict) -> tuple[float, list[str]]:
        keywords = row.get("trigger_keywords") or []
        keyword_text = " ".join(str(item) for item in keywords)
        trigger_text = row.get("trigger_text") or ""
        content = row.get("content") or ""
        mem_type = row.get("mem_type") or ""

        trigger_score = _overlap(query, trigger_text + "\n" + keyword_text)
        content_score = _overlap(query, content)
        type_score = _overlap(query, mem_type)
        recency_score = self._recency_score(row.get("updated_at") or row.get("created_at"))
        never_seen_bonus = 0.05 if not row.get("last_triggered_at") else 0.0
        score = min(
            1.0,
            trigger_score * 0.55
            + content_score * 0.30
            + type_score * 0.05
            + recency_score * 0.05
            + never_seen_bonus,
        )
        reasons = []
        if trigger_score > 0:
            reasons.append("trigger")
        if content_score > 0:
            reasons.append("content")
        if type_score > 0:
            reasons.append("type")
        if never_seen_bonus:
            reasons.append("not recently surfaced")
        return score, reasons or ["soft match"]

    def _public_search_item(self, row: dict, reasons: list[str]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "session_tag": row.get("session_tag"),
            "content": row.get("content") or "",
            "mem_type": row.get("mem_type") or "",
            "trigger_text": row.get("trigger_text") or "",
            "trigger_keywords": row.get("trigger_keywords") or [],
            "matched_by": reasons,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _search_text(self, row: dict) -> str:
        return "\n".join(
            [
                row.get("content") or "",
                row.get("mem_type") or "",
                row.get("trigger_text") or "",
                " ".join(str(item) for item in row.get("trigger_keywords") or []),
                row.get("review_note") or "",
            ]
        )

    def _legacy_search_text(self, row: dict) -> str:
        return "\n".join(
            str(part or "")
            for part in [
                row.get("subject"),
                row.get("owner"),
                row.get("content_surface"),
                row.get("quote"),
                row.get("time_hint"),
                row.get("memory_type"),
                row.get("source_excerpt"),
                " ".join(str(item) for item in row.get("tags_json") or []),
                " ".join(str(item) for item in row.get("entities_json") or []),
            ]
        )

    def _in_cooldown(self, row: dict) -> bool:
        cooldown_hours = self._int_range(row.get("cooldown_hours"), 72, 0, 8760)
        if cooldown_hours <= 0:
            return False
        triggered_at = _parse_ts(row.get("last_triggered_at"))
        if not triggered_at:
            return False
        return _now() < triggered_at + timedelta(hours=cooldown_hours)

    async def _mark_triggered(self, rows: list[dict]) -> None:
        for row in rows:
            note_id = row.get("id")
            if not note_id:
                continue
            try:
                await self.supabase.update(
                    "shenyu_mem_notes",
                    {"id": note_id},
                    {
                        "last_triggered_at": iso_now(),
                        "trigger_count": int(row.get("trigger_count") or 0) + 1,
                    },
                )
            except Exception:
                continue

    async def _get_note(self, note_id: str) -> Optional[dict[str, Any]]:
        note_id = (note_id or "").strip()
        if not note_id or not self.supabase:
            return None
        rows = await self.supabase.query(
            "shenyu_mem_notes",
            {
                "id": f"eq.{note_id}",
                "limit": "1",
                "select": "id,content,mem_type,trigger_text,trigger_keywords,status,cooldown_hours,review_note",
            },
        )
        return rows[0] if rows else None

    def _active_validation_error(self, row: dict[str, Any]) -> str:
        if row.get("status") != "active":
            return ""
        mem_type = row.get("mem_type")
        trigger_text = _normalize_text(row.get("trigger_text")).strip()
        trigger_keywords = self._keyword_list(row.get("trigger_keywords"))
        if mem_type not in MEM_NOTE_TYPES:
            return "active mem note requires one of the four mem_type values."
        if not trigger_text and not trigger_keywords:
            return "active mem note requires trigger_text or trigger_keywords."
        return ""

    def _mem_type(self, value: Any, allow_empty: bool = False) -> Optional[str]:
        raw = _normalize_text(value).strip()
        if not raw and allow_empty:
            return None
        return raw if raw in MEM_NOTE_TYPES else "心里那一档"

    def _status(self, value: Any, fallback: str = "captured", allow_all: bool = False) -> str:
        raw = _normalize_text(value).strip().lower()
        if allow_all and raw == "all":
            return "all"
        return raw if raw in MEM_NOTE_STATUSES else fallback

    def _keyword_list(self, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            raw_items = re.split(r"[,，、\s]+", value)
        elif isinstance(value, (list, tuple, set)):
            raw_items = [str(item) for item in value]
        else:
            raw_items = [str(value)]
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            keyword = item.strip()
            if keyword and keyword not in seen:
                seen.add(keyword)
                result.append(keyword)
        return result[:24]

    def _int_range(self, value: Any, fallback: int, min_value: int, max_value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(min_value, min(parsed, max_value))

    def _recency_score(self, value: Optional[str]) -> float:
        dt = _parse_ts(value)
        if not dt:
            return 0.0
        days = max((_now() - dt).days, 0)
        if days <= 1:
            return 1.0
        if days <= 7:
            return 0.65
        if days <= 30:
            return 0.25
        return 0.0
