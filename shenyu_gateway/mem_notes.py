from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Optional

from shenyu_gateway.recall import RecallIndexService, recall_terms
from .runtime import iso_now, now as _now, parse_ts as _parse_ts


MEM_NOTE_TYPES = ("她为我做的事", "我为她做的事", "关于她的事实", "关于我的事", "心里那一档", "承诺")
MEM_NOTE_STATUSES = ("captured", "active", "paused", "archived")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_CONTEXT_QUERY_ATTACHMENT_RE = re.compile(
    r"\s*<attachment\b(?=[^>]*\bid\s*=\s*['\"]?message_insert_extra_bundle_[^'\"\s>]+['\"]?)[^>]*>.*?</attachment>",
    re.IGNORECASE | re.DOTALL,
)
CONTEXT_KEYWORD_MIN_SCORE = 0.35
CONTEXT_SEMANTIC_MIN_SCORE = 0.40
CONTEXT_SEMANTIC_MIN_VECTOR_SCORE = 0.58
CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE = 0.30
CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE = 0.48
CONTEXT_WEAK_KEYWORD_HITS = {
    "0",
    "mem",
    "note",
    "一下",
    "可以",
    "东西",
    "为什么",
    "为什",
    "什么",
    "现在",
    "到底",
    "还是",
    "不是",
    "是不",
    "自己",
    "怎么",
    "方式",
    "的方",
    "类的",
    "写的",
}


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


def _normalize_note_id(value: Any) -> str:
    raw = _normalize_text(value).strip()
    match = _UUID_RE.search(raw)
    return match.group(0) if match else raw


def _clean_context_query(query: Any) -> str:
    text = _normalize_text(query)
    if not text:
        return ""
    text = _CONTEXT_QUERY_ATTACHMENT_RE.sub(" ", text)
    text = re.sub(r"<attachment\b[^>]*>", " ", text, flags=re.IGNORECASE)
    text = text.replace("</attachment>", " ")
    text = re.sub(r"message_insert_extra_bundle_[0-9A-Za-z_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
        min_score: Optional[float] = None,
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

        min_score = (
            self._float_range(min_score, 0.45, 0.0, 1.0)
            if min_score is not None
            else float(getattr(self.cfg, "mem_note_min_score", 0.45) or 0.45)
        )
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

    async def search_notes_contextual(
        self,
        query: str,
        session_tag: Optional[str] = None,
        limit: int = 3,
        mark_triggered: bool = True,
        recall_service: Optional[RecallIndexService] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "note": "Supabase is not configured."}

        clean_query = _clean_context_query(query)
        if not clean_query:
            return {"ok": True, "query": clean_query, "count": 0, "items": []}

        target_limit = max(1, min(int(limit or 3), 5))
        keyword_min_score = self._float_range(
            getattr(self.cfg, "mem_note_context_keyword_min_score", CONTEXT_KEYWORD_MIN_SCORE),
            CONTEXT_KEYWORD_MIN_SCORE,
            0.0,
            1.0,
        )
        keyword_result = await self.search_notes(
            clean_query,
            session_tag=session_tag,
            limit=target_limit,
            mark_triggered=False,
            min_score=keyword_min_score,
        )
        items = list(keyword_result.get("items") or [])
        selected_ids = {str(item.get("id") or "") for item in items if item.get("id")}

        if not items:
            semantic_items = await self._semantic_search_notes(
                clean_query,
                session_tag=session_tag,
                limit=target_limit,
                exclude_ids=selected_ids,
                recall_service=recall_service,
            )
            items.extend(semantic_items)

        items = items[:target_limit]
        if mark_triggered and items:
            note_ids = [str(item.get("id") or "") for item in items if item.get("id")]
            rows_by_id = await self._get_notes_by_ids(note_ids)
            await self._mark_triggered([rows_by_id[note_id] for note_id in note_ids if note_id in rows_by_id])

        return {"ok": True, "query": clean_query, "count": len(items), "items": items}

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

    async def create_note(
        self,
        content: Any,
        session_tag: Optional[str] = None,
        mem_type: Optional[str] = None,
        trigger_text: Any = "",
        trigger_keywords: Any = None,
        status: str = "active",
        cooldown_hours: Any = None,
        review_note: Any = "",
        source_model: str = "tool:shenyu_write_mem_note",
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        normalized_content = _normalize_text(content).strip()
        if not normalized_content:
            return {"ok": False, "error": "content is required."}

        resolved_status = self._status(status, fallback="captured")
        resolved_session_tag = (session_tag or "default").strip() or "default"
        default_cooldown = int(getattr(self.cfg, "mem_note_default_cooldown_hours", 72) or 72)
        payload: dict[str, Any] = {
            "session_tag": resolved_session_tag,
            "content": normalized_content,
            "status": resolved_status,
            "cooldown_hours": self._int_range(cooldown_hours, default_cooldown, 0, 8760),
            "source_model": source_model,
        }

        resolved_type = self._mem_type(mem_type, allow_empty=True)
        if resolved_status == "active" and not resolved_type:
            resolved_type = "心里那一档"
        if resolved_type:
            payload["mem_type"] = resolved_type

        normalized_trigger = _normalize_text(trigger_text).strip()
        keywords = self._keyword_list(trigger_keywords)
        if resolved_status == "active" and not normalized_trigger and not keywords:
            normalized_trigger = normalized_content
        if normalized_trigger:
            payload["trigger_text"] = normalized_trigger

        if keywords:
            payload["trigger_keywords"] = keywords

        normalized_review_note = _normalize_text(review_note).strip()
        if normalized_review_note:
            payload["review_note"] = normalized_review_note
            payload["reviewed_at"] = iso_now()

        active_error = self._active_validation_error(payload)
        if active_error:
            return {"ok": False, "error": active_error}

        row = await self.supabase.insert("shenyu_mem_notes", payload)
        return {
            "ok": True,
            "note_id": row.get("id") if isinstance(row, dict) else None,
            "note": row,
        }

    async def update_note(self, note_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        note_id = _normalize_note_id(note_id)
        if not note_id:
            return {"ok": False, "error": "note_id is required."}
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
        note_id = _normalize_note_id(note_id)
        if not note_id:
            return {"ok": False, "error": "note_id is required."}
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

    async def _get_notes_by_ids(self, note_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not note_ids or not self.supabase:
            return {}
        unique_ids: list[str] = []
        seen: set[str] = set()
        for note_id in note_ids:
            normalized = _normalize_note_id(note_id)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_ids.append(normalized)
        if not unique_ids:
            return {}
        rows = await self.supabase.query(
            "shenyu_mem_notes",
            {
                "id": "in.(" + ",".join(unique_ids) + ")",
                "limit": str(len(unique_ids)),
                "select": (
                    "id,session_tag,content,mem_type,trigger_text,trigger_keywords,status,"
                    "cooldown_hours,last_triggered_at,trigger_count,source_model,source_session_id,"
                    "source_excerpt,review_note,reviewed_at,created_at,updated_at"
                ),
            },
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            note_id = str(row.get("id") or "").strip()
            if note_id:
                result[note_id] = row
        return result

    async def _semantic_search_notes(
        self,
        query: str,
        session_tag: Optional[str],
        limit: int,
        *,
        exclude_ids: Optional[set[str]] = None,
        recall_service: Optional[RecallIndexService] = None,
    ) -> list[dict[str, Any]]:
        if not query.strip() or not self.supabase:
            return []
        exclude_ids = exclude_ids or set()
        service = recall_service or RecallIndexService(self.supabase, cfg=self.cfg)
        tokens = recall_terms(query)
        try:
            keyword_rows = await service._query_index(source_types=["mem_note"], query_text=query, tokens=tokens)
        except Exception:
            keyword_rows = []
        try:
            vector_rows, _ = await service._vector_rows(query, source_types=["mem_note"])
        except Exception:
            vector_rows = []
        rows = service._merge_candidate_rows(keyword_rows, vector_rows)
        if not rows:
            return []

        candidate_ids: list[str] = []
        for row in rows:
            note_id = str(row.get("source_id") or "").strip()
            if note_id and note_id not in exclude_ids and note_id not in candidate_ids:
                candidate_ids.append(note_id)

        note_rows = await self._get_notes_by_ids(candidate_ids)
        candidates: list[tuple[float, list[str], dict[str, Any], dict[str, Any]]] = []
        seen_ids: set[str] = set()
        semantic_min_score = self._float_range(
            getattr(self.cfg, "mem_note_semantic_min_score", CONTEXT_SEMANTIC_MIN_SCORE),
            CONTEXT_SEMANTIC_MIN_SCORE,
            0.0,
            1.0,
        )
        semantic_min_vector_score = self._float_range(
            getattr(self.cfg, "mem_note_semantic_min_vector_score", CONTEXT_SEMANTIC_MIN_VECTOR_SCORE),
            CONTEXT_SEMANTIC_MIN_VECTOR_SCORE,
            0.0,
            1.0,
        )
        for row in rows:
            note_id = str(row.get("source_id") or "").strip()
            if not note_id or note_id in seen_ids or note_id in exclude_ids:
                continue
            note = note_rows.get(note_id)
            if not note or (note.get("status") or "") != "active":
                continue
            if session_tag and (note.get("session_tag") or "").strip() != session_tag:
                continue
            if not service._row_visible_for_session(row, session_tag):
                continue
            if self._in_cooldown(note):
                continue
            score, reasons = service._score_row(row, query, tokens)
            vector_score = max(0.0, min(float(row.get("_vector_score") or 0.0), 1.0))
            has_direct_match = service._has_direct_match(reasons)
            if tokens and not has_direct_match and not vector_score:
                continue
            strong_hits = self._context_strong_keyword_hits(reasons)
            is_strong_semantic = score >= semantic_min_score and vector_score >= semantic_min_vector_score
            is_anchored_semantic = (
                bool(strong_hits)
                and score >= CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE
                and vector_score >= CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE
            )
            if not is_strong_semantic and not is_anchored_semantic:
                continue
            candidates.append((score, reasons, note, row))
            seen_ids.add(note_id)

        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = candidates[: max(1, min(int(limit or 3), 5))]
        items: list[dict[str, Any]] = []
        for score, reasons, note, row in selected:
            item = self._public_search_item(note, reasons)
            item["score"] = round(score, 3)
            item["search_mode"] = "semantic"
            if row.get("_vector_score") is not None:
                try:
                    item["semantic_score"] = round(float(row.get("_vector_score") or 0.0), 3)
                except (TypeError, ValueError):
                    item["semantic_score"] = 0.0
            items.append(item)
        return items

    def _context_strong_keyword_hits(self, reasons: list[str]) -> list[str]:
        hits: list[str] = []
        for reason in reasons:
            if not reason.startswith("keyword:"):
                continue
            raw_hits = reason.removeprefix("keyword:").split(",")
            for hit in raw_hits:
                normalized = hit.strip().lower()
                if not normalized or normalized in CONTEXT_WEAK_KEYWORD_HITS:
                    continue
                hits.append(normalized)
        return hits

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
        note_id = _normalize_note_id(note_id)
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
            return "active mem note requires a known mem_type value."
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

    def _float_range(self, value: Any, fallback: float, min_value: float, max_value: float) -> float:
        try:
            parsed = float(value)
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
