from __future__ import annotations

import asyncio
import random
from datetime import timedelta
from typing import Any, Optional

from shenyu_gateway.recall import RecallIndexService, recall_terms
from shenyu_gateway.runtime import logger
from shenyu_gateway.utils import shorten as _shorten
from ..mem_notes_relevance import (
    CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE,
    CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE,
    CONTEXT_KEYWORD_MIN_SCORE,
    CONTEXT_RELATION_NAME_TERMS,
    CONTEXT_SEMANTIC_MIN_SCORE,
    CONTEXT_SEMANTIC_MIN_VECTOR_SCORE,
    CONTEXT_WEAK_KEYWORD_HITS,
    _anchor_match,
    _auto_generate_summary,
    _clean_context_query,
    _infer_memory_kind,
    _keyword_anchor_is_specific,
    _low_information_semantic_query,
    _overlap,
    _query_scene_terms,
    _semantic_anchor_hits,
    _skip_auto_surface,
    _terms,
    _trigger_overlap,
    running_joke_serendipity_rate,
)
from ..runtime import iso_now, now as _now, parse_ts as _parse_ts
from ._helpers import _MEM_NOTE_SELECT_FIELDS, _MEM_NOTE_SELECT_FIELDS_LIGHT, _normalize_note_id


class SearchMixin:

    # ------------------------------------------------------------------
    # Public search
    # ------------------------------------------------------------------

    async def search_notes(
        self,
        query: str,
        session_tag: Optional[str] = None,
        limit: int = 3,
        mark_triggered: bool = True,
        min_score: Optional[float] = None,
        session_id: Optional[str] = None,
        store: Any = None,
        cooldown_hours: Optional[int] = None,
        dedupe_turns: Optional[int] = None,
        specific_content_only: bool = False,
        rows_override: Optional[list[dict[str, Any]]] = None,
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
            "select": _MEM_NOTE_SELECT_FIELDS_LIGHT,
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        rows = (
            [self._effective_note(row) for row in rows_override]
            if rows_override is not None
            else [self._effective_note(row) for row in await self.supabase.query("shenyu_mem_notes", params)]
        )

        min_score = (
            self._float_range(min_score, 0.45, 0.0, 1.0)
            if min_score is not None
            else float(getattr(self.cfg, "mem_note_min_score", 0.45) or 0.45)
        )
        scored: list[tuple[float, dict, list[str]]] = []
        for row in rows:
            if not self._auto_surface_eligibility(row)[0]:
                continue
            if self._should_skip_retrigger(
                row,
                session_id=session_id,
                store=store,
                cooldown_hours=cooldown_hours,
                dedupe_turns=dedupe_turns,
            ):
                continue
            score, reasons = self._score(query, row, specific_content_only=specific_content_only)
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
        session_id: Optional[str] = None,
        store: Any = None,
        ignore_retrigger_limits: bool = False,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "note": "Supabase is not configured."}

        clean_query = _clean_context_query(query)
        if not clean_query:
            return {"ok": True, "query": clean_query, "count": 0, "items": []}

        target_limit = max(1, min(int(limit or 3), 5))

        # session_tag records provenance for normal mem notes; it is not a
        # visibility boundary. Hisense skips this context path entirely.
        active_rows = await self._load_active_rows(None)

        # --- Layer 0: running_joke serendipity (scene_tag match + random gate) ---
        joke_items = self._running_joke_serendipity_matches(
            clean_query,
            active_rows,
            session_id=session_id,
            store=store,
            ignore_retrigger_limits=ignore_retrigger_limits,
        )
        items = joke_items[:1]
        selected_ids = {str(item.get("id") or "") for item in items if item.get("id")}

        # --- Layer 1: entity match (precise, no threshold) ---
        entity_items = self._entity_match_notes(
            clean_query,
            active_rows,
            session_id=session_id,
            store=store,
            exclude_ids=selected_ids,
            ignore_retrigger_limits=ignore_retrigger_limits,
        )
        for ent_item in entity_items:
            ent_id = str(ent_item.get("id") or "")
            if ent_id and ent_id not in selected_ids:
                items.append(ent_item)
                selected_ids.add(ent_id)
                if len(items) >= target_limit:
                    break

        # --- Layer 2: keyword search (fill remaining slots) ---
        if len(items) < target_limit:
            keyword_min_score = self._float_range(
                getattr(self.cfg, "mem_note_context_keyword_min_score", CONTEXT_KEYWORD_MIN_SCORE),
                CONTEXT_KEYWORD_MIN_SCORE,
                0.0,
                1.0,
            )
            keyword_result = await self.search_notes(
                clean_query,
                session_tag=None,
                limit=target_limit,
                mark_triggered=False,
                min_score=keyword_min_score,
                session_id=session_id,
                store=store,
                cooldown_hours=0 if ignore_retrigger_limits else self._context_cooldown_hours(),
                dedupe_turns=0 if ignore_retrigger_limits else self._context_dedupe_turns(),
                specific_content_only=True,
                rows_override=active_rows,
            )
            for kw_item in keyword_result.get("items") or []:
                kw_id = str(kw_item.get("id") or "")
                if kw_id and kw_id not in selected_ids:
                    items.append(kw_item)
                    selected_ids.add(kw_id)
                    if len(items) >= target_limit:
                        break

        # --- Layer 3: semantic search (anchored rerank only, not slot-filler) ---
        if not _low_information_semantic_query(clean_query):
            semantic_items = await self._semantic_search_notes(
                clean_query,
                session_tag=None,
                limit=1,
                exclude_ids=selected_ids,
                recall_service=recall_service,
                session_id=session_id,
                store=store,
                ignore_retrigger_limits=ignore_retrigger_limits,
                rows_by_id_override={str(row.get("id") or ""): row for row in active_rows if row.get("id")},
            )
            for sem_item in semantic_items:
                sem_id = str(sem_item.get("id") or "")
                if sem_id and sem_id not in selected_ids and len(items) < target_limit:
                    items.append(sem_item)
                    selected_ids.add(sem_id)

        items = items[:target_limit]
        if mark_triggered and items:
            note_ids = [str(item.get("id") or "") for item in items if item.get("id")]
            rows_by_id = await self._get_notes_by_ids(note_ids)
            await self._mark_triggered([rows_by_id[note_id] for note_id in note_ids if note_id in rows_by_id])

        return {"ok": True, "query": clean_query, "count": len(items), "items": items}

    async def mark_context_items_triggered(self, items: list[dict[str, Any]]) -> None:
        note_ids = [str(item.get("id") or "") for item in items if item.get("id")]
        rows_by_id = await self._get_notes_by_ids(note_ids)
        await self._mark_triggered([rows_by_id[note_id] for note_id in note_ids if note_id in rows_by_id])

    async def auto_surface_active_ids(self, note_ids: list[str]) -> set[str]:
        """Return requested note ids that are still eligible for automatic recall."""
        rows_by_id = await self._get_notes_by_ids(note_ids)
        return {
            note_id
            for note_id, row in rows_by_id.items()
            if self._auto_surface_eligibility(row)[0]
        }

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_notes_for_context(self, notes: list[dict[str, Any]]) -> str:
        if not notes:
            return ""
        lines: list[str] = []
        for note in notes:
            summary = (note.get("summary") or "").strip()
            content = _shorten(note.get("content") or "", 200)
            text = summary or content
            if not text:
                continue
            anchors: list[str] = []
            for person in (note.get("people") or [])[:2]:
                anchors.append(f"人：{person}")
            for place in (note.get("places") or [])[:1]:
                anchors.append(f"地：{place}")
            for obj in (note.get("objects") or [])[:1]:
                anchors.append(f"物：{obj}")
            anchor_suffix = f"（{'；'.join(anchors)}）" if anchors else ""
            lines.append(f"（{text}{anchor_suffix}）")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(self, query: str, row: dict, *, specific_content_only: bool = False) -> tuple[float, list[str]]:
        keywords = row.get("trigger_keywords") or []
        trigger_text = row.get("trigger_text") or ""
        content = row.get("content") or ""
        mem_type = row.get("mem_type") or ""

        trigger_score, trigger_hits = _trigger_overlap(query, trigger_text, keywords)
        content_score = _overlap(query, content, specific_only=specific_content_only)
        type_score = _overlap(query, mem_type)
        recency_score = self._recency_score(row.get("updated_at") or row.get("created_at"))
        never_seen_bonus = 0.05 if not row.get("last_triggered_at") else 0.0

        anchor_score, anchor_hits = self._anchor_overlap(query, row)

        score = min(
            1.0,
            trigger_score * 0.50
            + content_score * 0.30
            + anchor_score * 0.10
            + type_score * 0.02
            + recency_score * 0.03
            + never_seen_bonus,
        )
        reasons = []
        if trigger_score > 0:
            reasons.append("trigger" + (":" + ",".join(trigger_hits[:5]) if trigger_hits else ""))
        if anchor_score > 0:
            reasons.append("anchor" + (":" + ",".join(anchor_hits[:3]) if anchor_hits else ""))
        if content_score > 0:
            reasons.append("content")
        if type_score > 0:
            reasons.append("type")
        if never_seen_bonus:
            reasons.append("not recently surfaced")
        return score, reasons or ["soft match"]

    def _anchor_overlap(self, query: str, row: dict) -> tuple[float, list[str]]:
        query_lower = query.lower()
        all_anchors: list[str] = []
        weak_relation_names = {item.lower() for item in CONTEXT_RELATION_NAME_TERMS}
        for field in ("people", "places", "objects", "keywords"):
            for anchor in row.get(field) or []:
                anchor_text = str(anchor)
                if field == "people" and anchor_text.lower() in weak_relation_names:
                    continue
                if field == "keywords" and not _keyword_anchor_is_specific(anchor_text):
                    continue
                all_anchors.append(anchor_text)
        if not all_anchors:
            return 0.0, []
        hits: list[str] = []
        for anchor in all_anchors:
            if _anchor_match(anchor.lower(), query_lower):
                hits.append(anchor)
        if not hits:
            return 0.0, []
        return min(1.0, len(hits) / max(1, len(all_anchors)) + 0.3), hits

    def _public_search_item(self, row: dict, reasons: list[str]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "session_tag": row.get("session_tag"),
            "content": row.get("content") or "",
            "mem_type": row.get("mem_type") or "",
            "trigger_text": row.get("trigger_text") or "",
            "trigger_keywords": row.get("trigger_keywords") or [],
            "entities": row.get("entities") or [],
            "matched_by": reasons,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            # v2 structured fields
            "summary": row.get("summary") or "",
            "memory_kind": row.get("memory_kind") or "",
            "people": row.get("people") or [],
            "places": row.get("places") or [],
            "objects": row.get("objects") or [],
            "keywords": row.get("keywords") or [],
            "event_time": row.get("event_time"),
            "importance": row.get("importance"),
            "joke_text": row.get("joke_text") or "",
            "scene_tags": row.get("scene_tags") or [],
            "last_used_at": row.get("last_used_at"),
        }

    # ------------------------------------------------------------------
    # Entity / joke / semantic matching
    # ------------------------------------------------------------------

    def _running_joke_serendipity_matches(
        self,
        query: str,
        rows: list[dict],
        *,
        session_id: Optional[str] = None,
        store: Any = None,
        ignore_retrigger_limits: bool = False,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        query_tokens = set(query_lower.split())
        hits: list[dict[str, Any]] = []
        for row in rows:
            if _skip_auto_surface(row):
                continue
            if (row.get("memory_kind") or "") != "running_joke":
                continue
            scene_tags = row.get("scene_tags") or []
            if not scene_tags:
                continue
            matched_tag = None
            for tag in scene_tags:
                tag_lower = tag.lower()
                if tag_lower in query_tokens or _anchor_match(tag_lower, query_lower):
                    matched_tag = tag
                    break
            if not matched_tag:
                continue
            rate = running_joke_serendipity_rate(row.get("last_used_at"))
            if rate <= 0 or random.random() > rate:
                continue
            if not ignore_retrigger_limits and self._should_skip_retrigger(
                row,
                session_id=session_id,
                store=store,
                cooldown_hours=self._context_cooldown_hours(),
                dedupe_turns=self._context_dedupe_turns(),
            ):
                continue
            item = self._public_search_item(row, [f"running_joke:{matched_tag}"])
            item["search_mode"] = "running_joke"
            hits.append(item)
        return hits

    def _entity_match_notes(
        self,
        query: str,
        rows: list[dict],
        *,
        session_id: Optional[str] = None,
        store: Any = None,
        exclude_ids: Optional[set[str]] = None,
        ignore_retrigger_limits: bool = False,
    ) -> list[dict[str, Any]]:
        exclude_ids = exclude_ids or set()
        query_lower = query.lower()
        scene_terms = _query_scene_terms(query) if len(query) > 40 else []
        scene_lower = {t.lower() for t in scene_terms}
        weak_relation_names = {item.lower() for item in CONTEXT_RELATION_NAME_TERMS}
        hits: list[dict[str, Any]] = []
        for row in rows:
            if _skip_auto_surface(row):
                continue
            note_id = str(row.get("id") or "")
            if note_id in exclude_ids:
                continue
            all_anchors: list[tuple[str, str]] = []
            for ent in (row.get("entities") or []):
                if ent.lower() not in weak_relation_names:
                    all_anchors.append((ent, "entity"))
            for p in (row.get("people") or []):
                if p.lower() not in weak_relation_names:
                    all_anchors.append((p, "person"))
            for p in (row.get("places") or []):
                all_anchors.append((p, "place"))
            for o in (row.get("objects") or []):
                all_anchors.append((o, "object"))
            for k in (row.get("keywords") or []):
                if _keyword_anchor_is_specific(k):
                    all_anchors.append((k, "keyword"))
            if not all_anchors:
                continue
            matched_anchor = None
            matched_type = None
            for anchor, atype in all_anchors:
                anchor_low = anchor.lower()
                if _anchor_match(anchor_low, query_lower):
                    matched_anchor = anchor
                    matched_type = atype
                    break
                if scene_lower and anchor_low in scene_lower:
                    matched_anchor = anchor
                    matched_type = f"scene_{atype}"
                    break
            if not matched_anchor:
                continue
            if not ignore_retrigger_limits and self._should_skip_retrigger(
                row,
                session_id=session_id,
                store=store,
                cooldown_hours=self._context_cooldown_hours(),
                dedupe_turns=self._context_dedupe_turns(),
            ):
                continue
            item = self._public_search_item(row, [f"{matched_type}:{matched_anchor}"])
            item["search_mode"] = "entity"
            hits.append(item)
        return hits

    async def _semantic_search_notes(
        self,
        query: str,
        session_tag: Optional[str],
        limit: int,
        *,
        exclude_ids: Optional[set[str]] = None,
        recall_service: Optional[RecallIndexService] = None,
        session_id: Optional[str] = None,
        store: Any = None,
        ignore_retrigger_limits: bool = False,
        rows_by_id_override: Optional[dict[str, dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        if not query.strip() or not self.supabase:
            return []
        exclude_ids = exclude_ids or set()
        service = recall_service or RecallIndexService(self.supabase, cfg=self.cfg)
        tokens = recall_terms(query)
        async def keyword_candidates() -> list[dict[str, Any]]:
            try:
                return await service._query_index(
                    source_types=["mem_note"],
                    query_text=query,
                    tokens=tokens,
                    allow_mem_note=True,
                )
            except Exception:
                return []

        async def vector_candidates() -> list[dict[str, Any]]:
            try:
                rows, _ = await service._vector_rows(query, source_types=["mem_note"], allow_mem_note=True)
                return rows
            except Exception:
                return []

        keyword_rows, vector_rows = await asyncio.gather(keyword_candidates(), vector_candidates())
        rows = service._merge_candidate_rows(keyword_rows, vector_rows)
        if not rows:
            return []

        candidate_ids: list[str] = []
        for row in rows:
            note_id = str(row.get("source_id") or "").strip()
            if note_id and note_id not in exclude_ids and note_id not in candidate_ids:
                candidate_ids.append(note_id)

        note_rows = dict(rows_by_id_override or {})
        missing_ids = [note_id for note_id in candidate_ids if note_id not in note_rows]
        if missing_ids:
            note_rows.update(await self._get_notes_by_ids(missing_ids))
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
        anchored_semantic_min_score = self._float_range(
            getattr(self.cfg, "mem_note_anchored_semantic_min_score", CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE),
            CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE,
            0.0,
            1.0,
        )
        anchored_semantic_min_vector_score = self._float_range(
            getattr(
                self.cfg,
                "mem_note_anchored_semantic_min_vector_score",
                CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE,
            ),
            CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE,
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
            if _skip_auto_surface(note):
                continue
            if not service._row_visible_for_session(row, None):
                continue
            if not ignore_retrigger_limits and self._should_skip_retrigger(
                note,
                session_id=session_id,
                store=store,
                cooldown_hours=self._context_cooldown_hours(),
                dedupe_turns=self._context_dedupe_turns(),
            ):
                continue
            score, reasons = service._score_row(row, query, tokens)
            vector_score = max(0.0, min(float(row.get("_vector_score") or 0.0), 1.0))
            has_direct_match = service._has_direct_match(reasons)
            if tokens and not has_direct_match and not vector_score:
                continue
            strong_hits = _semantic_anchor_hits(reasons)
            has_semantic_anchor = bool(strong_hits)
            is_strong_semantic = (
                has_semantic_anchor
                and score >= semantic_min_score
                and vector_score >= semantic_min_vector_score
            )
            is_anchored_semantic = (
                has_semantic_anchor
                and score >= anchored_semantic_min_score
                and vector_score >= anchored_semantic_min_vector_score
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

    # ------------------------------------------------------------------
    # Data loading helpers
    # ------------------------------------------------------------------

    async def _load_active_rows(self, session_tag: Optional[str] = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "status": "eq.active",
            "order": "updated_at.desc",
            "limit": "160",
            "select": _MEM_NOTE_SELECT_FIELDS_LIGHT,
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        rows = await self.supabase.query("shenyu_mem_notes", params)
        effective_rows = [self._effective_note(row) for row in rows]
        return [row for row in effective_rows if self._auto_surface_eligibility(row)[0]]

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
                "select": _MEM_NOTE_SELECT_FIELDS,
            },
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            note_id = str(row.get("id") or "").strip()
            if note_id:
                result[note_id] = self._effective_note(row)
        return result

    async def get_notes_by_ids(self, note_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return the current read-model rows for explicit note ids."""
        return await self._get_notes_by_ids(note_ids)

    def _effective_note(self, row: dict[str, Any]) -> dict[str, Any]:
        """Project legacy mem-note rows into the v2 read model without rewriting them."""
        note = dict(row)
        content = str(note.get("content") or "").strip()
        if not note.get("summary") and content:
            note["summary"] = _auto_generate_summary(content)
        if not note.get("memory_kind") and content:
            note["memory_kind"] = _infer_memory_kind(content, str(note.get("mem_type") or ""))
        return note

    # ------------------------------------------------------------------
    # Cooldown / dedup
    # ------------------------------------------------------------------

    def _context_cooldown_hours(self) -> Optional[int]:
        if hasattr(self.cfg, "mem_note_soft_cooldown_hours"):
            return self._int_range(getattr(self.cfg, "mem_note_soft_cooldown_hours"), 12, 0, 8760)
        return None

    def _context_dedupe_turns(self) -> int:
        return self._int_range(getattr(self.cfg, "mem_note_dedupe_turns", 6), 6, 0, 50)

    def _default_cooldown_hours(self) -> int:
        return self._int_range(getattr(self.cfg, "mem_note_default_cooldown_hours", 72), 72, 0, 8760)

    def _in_cooldown(self, row: dict, cooldown_hours: Optional[int] = None) -> bool:
        if cooldown_hours is None:
            cooldown_hours = self._int_range(row.get("cooldown_hours"), 72, 0, 8760)
        else:
            cooldown_hours = self._int_range(cooldown_hours, 12, 0, 8760)
        if cooldown_hours <= 0:
            return False
        triggered_at = _parse_ts(row.get("last_triggered_at"))
        if not triggered_at:
            return False
        return _now() < triggered_at + timedelta(hours=cooldown_hours)

    def _recent_turn_duplicate(
        self,
        row: dict,
        *,
        session_id: Optional[str],
        store: Any,
        dedupe_turns: Optional[int],
    ) -> bool:
        dedupe_turns = self._int_range(dedupe_turns, 0, 0, 50) if dedupe_turns is not None else 0
        if dedupe_turns <= 0 or not session_id or not store:
            return False
        triggered_at = row.get("last_triggered_at")
        if not triggered_at:
            return False
        try:
            messages_since = store.count_messages_since(session_id, triggered_at, role="user")
        except Exception as exc:
            logger.warning("Failed to check mem note turn dedupe: id=%s error=%s", row.get("id"), exc)
            return False
        return messages_since < dedupe_turns

    def _should_skip_retrigger(
        self,
        row: dict,
        *,
        session_id: Optional[str] = None,
        store: Any = None,
        cooldown_hours: Optional[int] = None,
        dedupe_turns: Optional[int] = None,
    ) -> bool:
        if self._recent_turn_duplicate(row, session_id=session_id, store=store, dedupe_turns=dedupe_turns):
            return True
        return self._in_cooldown(row, cooldown_hours=cooldown_hours)

    async def _mark_triggered(self, rows: list[dict]) -> None:
        now_ts = iso_now()
        for row in rows:
            note_id = row.get("id")
            if not note_id:
                continue
            try:
                patch: dict[str, Any] = {
                    "last_triggered_at": now_ts,
                    "trigger_count": int(row.get("trigger_count") or 0) + 1,
                }
                if (row.get("memory_kind") or "") == "running_joke":
                    patch["last_used_at"] = now_ts
                await self.supabase.update(
                    "shenyu_mem_notes",
                    {"id": note_id},
                    patch,
                )
            except Exception as exc:
                logger.warning("Failed to mark mem note triggered: id=%s error=%s", note_id, exc)
                continue

    # ------------------------------------------------------------------
    # Search text helpers
    # ------------------------------------------------------------------

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
                " ".join(str(item) for item in row.get("entities") or []),
                " ".join(str(item) for item in row.get("people") or []),
                " ".join(str(item) for item in row.get("places") or []),
                " ".join(str(item) for item in row.get("objects") or []),
                row.get("summary") or "",
                row.get("topic") or "",
                row.get("promise_text") or "",
                row.get("joke_text") or "",
            ]
        )

    def _legacy_search_text(self, row: dict) -> str:
        return "\n".join(
            str(part or "")
            for part in [
                row.get("subject"),
                row.get("owner"),
                row.get("content_surface"),
                row.get("time_hint"),
                row.get("memory_type"),
                " ".join(str(item) for item in row.get("tags_json") or []),
                " ".join(str(item) for item in row.get("entities_json") or []),
            ]
        )
