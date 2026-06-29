from __future__ import annotations

import random
import re
from datetime import timedelta
from typing import Any, Optional

from shenyu_gateway.recall import RecallIndexService, recall_terms
from shenyu_gateway.runtime import logger
from shenyu_gateway.utils import normalize_text as _normalize_text
from shenyu_gateway.utils import shorten as _shorten
from .mem_notes_relevance import (
    CONTEXT_ANCHORED_SEMANTIC_MIN_SCORE,
    CONTEXT_ANCHORED_SEMANTIC_MIN_VECTOR_SCORE,
    CONTEXT_KEYWORD_MIN_SCORE,
    CONTEXT_SEMANTIC_MIN_SCORE,
    CONTEXT_SEMANTIC_MIN_VECTOR_SCORE,
    CONTEXT_WEAK_KEYWORD_HITS,
    AUTO_STRONG_TRIGGER_TERMS,
    AUTO_TRIGGER_GENERIC_TERMS,
    CONTEXT_RELATION_NAME_TERMS,
    CONTEXT_SEMANTIC_ANCHOR_STOP_TERMS,
    CONTEXT_SEMANTIC_STRONG_TERMS,
    _SUGGESTION_SEED_KEYWORDS,
    _TRIGGER_KEYWORD_JUNK_TOKENS,
    _TRIGGER_KEYWORD_STOP_TERMS,
    _TRIGGER_PHRASE_SPLIT_RE,
    _anchor_match,
    _auto_extract_entities,
    _auto_extract_keywords,
    _auto_extract_objects,
    _auto_extract_people,
    _auto_extract_places,
    _auto_generate_summary,
    _clean_context_query,
    _infer_memory_kind,
    _keyword_anchor_is_specific,
    _low_information_semantic_query,
    _overlap,
    _query_semantic_signal_terms,
    _query_scene_terms,
    _semantic_anchor_hits,
    _skip_auto_surface,
    _strip_tool_result_blocks,
    _terms,
    _trigger_overlap,
    _trigger_units,
    compute_heat,
    running_joke_serendipity_rate,
)
from .runtime import iso_now, now as _now, parse_ts as _parse_ts


MEM_NOTE_TYPES = ("她为我做的事", "我为她做的事", "关于她的事实", "关于我的事", "心里那一档", "承诺")
MEM_NOTE_STATUSES = ("captured", "active", "paused", "archived")
MEM_NOTE_MEMORY_KINDS = (
    "event", "person_fact", "social", "trip", "object", "preference",
    "routine", "promise", "running_joke", "thread",
)
MEM_NOTE_MEMORY_KIND_ALIASES: dict[str, str] = {
    # 中文 → English
    "事件": "event", "活动": "event",
    "人": "person_fact", "人物": "person_fact", "事实": "person_fact",
    "社交": "social", "聚会": "social",
    "旅行": "trip", "出行": "trip", "travel": "trip",
    "物品": "object", "东西": "object", "item": "object", "thing": "object",
    "偏好": "preference", "喜好": "preference", "pref": "preference",
    "习惯": "routine", "作息": "routine", "habit": "routine",
    "承诺": "promise", "约定": "promise",
    "梗": "running_joke", "笑话": "running_joke", "joke": "running_joke",
    "话题": "thread", "讨论": "thread", "conversation": "thread",
    # English aliases / typos
    "fact": "person_fact", "person": "person_fact", "personal_fact": "person_fact",
    "travel": "trip", "journey": "trip",
    "item": "object", "thing": "object",
    "pref": "preference", "like": "preference",
    "habit": "routine", "pattern": "routine",
    "joke": "running_joke", "meme": "running_joke",
    "topic": "thread", "conversation": "thread", "chat": "thread",
}
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
MEM_NOTE_PATCH_FIELDS = {
    "content",
    "mem_type",
    "trigger_text",
    "trigger_keywords",
    "entities",
    "status",
    "cooldown_hours",
    "review_note",
    # v2 structured fields
    "summary",
    "memory_kind",
    "people",
    "places",
    "objects",
    "keywords",
    "event_time",
    "importance",
    "mention_count",
    "promotion_score",
    "decay_after",
    # promise
    "promise_text",
    "trigger_scenarios",
    "due_hint",
    "resolved",
    "resolved_at",
    "next_action",
    "privacy_level",
    # running_joke
    "joke_text",
    "scene_tags",
    "last_used_at",
    # routine
    "routine_domain",
    "pattern",
    "phase",
    "constraints",
    "last_confirmed_at",
    # thread
    "topic",
    "last_position",
    "open_questions",
    "next_prompt",
    "thread_resolved",
}
MEM_NOTE_BULK_UPDATE_MAX = 200
def _normalize_note_id(value: Any) -> str:
    raw = _normalize_text(value).strip()
    match = _UUID_RE.search(raw)
    return match.group(0) if match else raw


# Select clause covering all v2 fields for list/get/search queries
_MEM_NOTE_SELECT_FIELDS = (
    "id,session_tag,content,mem_type,trigger_text,trigger_keywords,entities,status,"
    "cooldown_hours,last_triggered_at,trigger_count,source_model,source_session_id,"
    "source_excerpt,review_note,reviewed_at,created_at,updated_at,"
    "summary,memory_kind,people,places,objects,keywords,event_time,"
    "importance,confidence,mention_count,promotion_score,decay_after,"
    "promise_text,trigger_scenarios,due_hint,resolved,resolved_at,next_action,privacy_level,"
    "joke_text,scene_tags,last_used_at,"
    "routine_domain,pattern,phase,constraints,last_confirmed_at,"
    "topic,last_position,open_questions,next_prompt,thread_resolved"
)

_MEM_NOTE_SELECT_FIELDS_LIGHT = (
    "id,session_tag,content,mem_type,trigger_text,trigger_keywords,entities,status,"
    "cooldown_hours,last_triggered_at,trigger_count,source_model,created_at,updated_at,"
    "summary,memory_kind,people,places,objects,keywords,event_time,"
    "importance,mention_count,promotion_score,"
    "promise_text,resolved,joke_text,scene_tags,last_used_at,"
    "routine_domain,pattern,topic,thread_resolved"
)


class MemNoteService:
    def __init__(self, cfg: Any, supabase_client: Any):
        self.cfg = cfg
        self.supabase = supabase_client


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
        rows = await self.supabase.query("shenyu_mem_notes", params)

        min_score = (
            self._float_range(min_score, 0.45, 0.0, 1.0)
            if min_score is not None
            else float(getattr(self.cfg, "mem_note_min_score", 0.45) or 0.45)
        )
        scored: list[tuple[float, dict, list[str]]] = []
        for row in rows:
            if _skip_auto_surface(row):
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
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "note": "Supabase is not configured."}

        clean_query = _clean_context_query(query)
        if not clean_query:
            return {"ok": True, "query": clean_query, "count": 0, "items": []}

        target_limit = max(1, min(int(limit or 3), 5))

        # Load active notes once for entity matching
        active_rows = await self._load_active_rows(session_tag)

        # --- Layer 0: running_joke serendipity (scene_tag match + random gate) ---
        joke_items = self._running_joke_serendipity_matches(
            clean_query, active_rows, session_id=session_id, store=store
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
                session_tag=session_tag,
                limit=target_limit,
                mark_triggered=False,
                min_score=keyword_min_score,
                session_id=session_id,
                store=store,
                cooldown_hours=self._context_cooldown_hours(),
                dedupe_turns=self._context_dedupe_turns(),
                specific_content_only=True,
            )
            for kw_item in keyword_result.get("items") or []:
                kw_id = str(kw_item.get("id") or "")
                if kw_id and kw_id not in selected_ids:
                    items.append(kw_item)
                    selected_ids.add(kw_id)
                    if len(items) >= target_limit:
                        break

        # --- Layer 3: semantic search (anchored rerank only, not slot-filler) ---
        # Semantic results are only added when they have strong anchor support
        # (is_strong_semantic or is_anchored_semantic via _semantic_search_notes).
        # Cap at 1 item to avoid dominating the recall window unanchored.
        if not _low_information_semantic_query(clean_query):
            semantic_items = await self._semantic_search_notes(
                clean_query,
                session_tag=session_tag,
                limit=1,
                exclude_ids=selected_ids,
                recall_service=recall_service,
                session_id=session_id,
                store=store,
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

    async def list_notes(
        self,
        status: str = "captured",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        mem_type: Optional[str] = None,
        memory_kind: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "items": [], "error": "Supabase is not configured."}
        status = self._status(status, fallback="captured", allow_all=True)
        params: dict[str, str] = {
            "order": "updated_at.desc",
            "limit": str(max(1, min(int(limit or 50), 200))),
            "select": _MEM_NOTE_SELECT_FIELDS,
        }
        if status != "all":
            params["status"] = f"eq.{status}"
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        if mem_type and mem_type in MEM_NOTE_TYPES:
            params["mem_type"] = f"eq.{mem_type}"
        if memory_kind and memory_kind in MEM_NOTE_MEMORY_KINDS:
            params["memory_kind"] = f"eq.{memory_kind}"
        rows = await self.supabase.query("shenyu_mem_notes", params)

        terms = _terms(q)
        if terms:
            rows = [
                row
                for row in rows
                if any(term in self._search_text(row).lower() for term in terms)
            ]
        items = [self._public_list_item(row) for row in rows]
        return {"ok": True, "items": items, "status": status, "count": len(items)}

    async def create_note(
        self,
        content: Any,
        session_tag: Optional[str] = None,
        mem_type: Optional[str] = None,
        trigger_text: Any = "",
        trigger_keywords: Any = None,
        entities: Any = None,
        status: str = "active",
        cooldown_hours: Any = None,
        review_note: Any = "",
        replaces: Optional[list[Any]] = None,
        source_model: str = "tool:shenyu_write_mem_note",
        # v2 fields
        summary: Any = None,
        memory_kind: Optional[str] = None,
        people: Any = None,
        places: Any = None,
        objects: Any = None,
        keywords: Any = None,
        event_time: Any = None,
        importance: Any = None,
        # promise
        promise_text: Any = None,
        trigger_scenarios: Any = None,
        due_hint: Any = None,
        resolved: Any = None,
        next_action: Any = None,
        privacy_level: Any = None,
        # running_joke
        joke_text: Any = None,
        scene_tags: Any = None,
        # routine
        routine_domain: Any = None,
        pattern: Any = None,
        phase: Any = None,
        constraints: Any = None,
        # thread
        topic: Any = None,
        last_position: Any = None,
        open_questions: Any = None,
        next_prompt: Any = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        normalized_content = _normalize_text(content).strip()
        if not normalized_content:
            return {"ok": False, "error": "content is required."}

        resolved_status = self._status(status, fallback="captured")
        resolved_session_tag = (session_tag or "default").strip() or "default"
        default_cooldown = self._default_cooldown_hours()
        payload: dict[str, Any] = {
            "session_tag": resolved_session_tag,
            "content": normalized_content,
            "status": resolved_status,
            "cooldown_hours": self._int_range(cooldown_hours, default_cooldown, 0, 8760),
            "source_model": source_model,
        }

        resolved_type = self._mem_type(mem_type, allow_empty=True)
        if not resolved_type:
            suggested_type, _ = self._suggest_mem_type(normalized_content)
            resolved_type = suggested_type
        if resolved_type:
            payload["mem_type"] = resolved_type

        normalized_trigger = _normalize_text(trigger_text).strip()
        resolved_trigger_keywords = self._keyword_list(trigger_keywords)
        if resolved_status == "active" and not normalized_trigger and not resolved_trigger_keywords:
            normalized_trigger = normalized_content
        if normalized_trigger:
            payload["trigger_text"] = normalized_trigger

        if resolved_trigger_keywords:
            payload["trigger_keywords"] = resolved_trigger_keywords

        resolved_entities = self._entity_list(entities)
        if not resolved_entities:
            resolved_entities = _auto_extract_entities(normalized_content)
        if resolved_entities:
            payload["entities"] = resolved_entities

        normalized_review_note = _normalize_text(review_note).strip()
        if normalized_review_note:
            payload["review_note"] = normalized_review_note
            payload["reviewed_at"] = iso_now()

        # v2 structured fields — auto-enrich from content when not provided
        normalized_summary = _normalize_text(summary).strip() if summary else ""
        if normalized_summary:
            payload["summary"] = normalized_summary
        else:
            auto_summary = _auto_generate_summary(normalized_content)
            if auto_summary:
                payload["summary"] = auto_summary
        resolved_kind = self._memory_kind(memory_kind)
        if not resolved_kind:
            resolved_kind = _infer_memory_kind(normalized_content, resolved_type or "")
        payload["memory_kind"] = resolved_kind
        resolved_people = self._entity_list(people)
        if not resolved_people:
            resolved_people = _auto_extract_people(normalized_content)
        if resolved_people:
            payload["people"] = resolved_people
        resolved_places = self._entity_list(places)
        if not resolved_places:
            resolved_places = _auto_extract_places(normalized_content)
        if resolved_places:
            payload["places"] = resolved_places
        resolved_objects = self._entity_list(objects)
        if not resolved_objects:
            resolved_objects = _auto_extract_objects(normalized_content)
        if resolved_objects:
            payload["objects"] = resolved_objects
        resolved_keywords = self._keyword_list(keywords)
        if not resolved_keywords:
            resolved_keywords = _auto_extract_keywords(normalized_content)
        if resolved_keywords:
            payload["keywords"] = resolved_keywords
        normalized_event_time = _normalize_text(event_time).strip() if event_time else ""
        if normalized_event_time:
            payload["event_time"] = normalized_event_time
        if importance is not None:
            payload["importance"] = self._int_range(importance, 1, 0, 5)

        # promise fields
        normalized_promise = _normalize_text(promise_text).strip() if promise_text else ""
        if normalized_promise:
            payload["promise_text"] = normalized_promise
        resolved_scenarios = self._keyword_list(trigger_scenarios)
        if resolved_scenarios:
            payload["trigger_scenarios"] = resolved_scenarios
        normalized_due = _normalize_text(due_hint).strip() if due_hint else ""
        if normalized_due:
            payload["due_hint"] = normalized_due
        if resolved is not None:
            payload["resolved"] = bool(resolved)
        normalized_next_action = _normalize_text(next_action).strip() if next_action else ""
        if normalized_next_action:
            payload["next_action"] = normalized_next_action
        normalized_privacy = _normalize_text(privacy_level).strip() if privacy_level else ""
        if normalized_privacy:
            payload["privacy_level"] = normalized_privacy

        # running_joke fields
        normalized_joke = _normalize_text(joke_text).strip() if joke_text else ""
        if normalized_joke:
            payload["joke_text"] = normalized_joke
        resolved_scene_tags = self._keyword_list(scene_tags)
        if resolved_scene_tags:
            payload["scene_tags"] = resolved_scene_tags

        # routine fields
        normalized_domain = _normalize_text(routine_domain).strip() if routine_domain else ""
        if normalized_domain:
            payload["routine_domain"] = normalized_domain
        normalized_pattern = _normalize_text(pattern).strip() if pattern else ""
        if normalized_pattern:
            payload["pattern"] = normalized_pattern
        normalized_phase = _normalize_text(phase).strip() if phase else ""
        if normalized_phase:
            payload["phase"] = normalized_phase
        resolved_constraints = self._keyword_list(constraints)
        if resolved_constraints:
            payload["constraints"] = resolved_constraints

        # thread fields
        normalized_topic = _normalize_text(topic).strip() if topic else ""
        if normalized_topic:
            payload["topic"] = normalized_topic
        normalized_position = _normalize_text(last_position).strip() if last_position else ""
        if normalized_position:
            payload["last_position"] = normalized_position
        resolved_questions = self._keyword_list(open_questions)
        if resolved_questions:
            payload["open_questions"] = resolved_questions
        normalized_next_prompt = _normalize_text(next_prompt).strip() if next_prompt else ""
        if normalized_next_prompt:
            payload["next_prompt"] = normalized_next_prompt

        active_error = self._active_validation_error(payload)
        if active_error:
            return {"ok": False, "error": active_error}

        row = await self.supabase.insert("shenyu_mem_notes", payload)

        archived_ids: list[str] = []
        if replaces:
            new_id = row.get("id") if isinstance(row, dict) else ""
            for raw_old_id in replaces:
                old_id = _normalize_note_id(raw_old_id)
                if not old_id:
                    continue
                try:
                    await self.supabase.update(
                        "shenyu_mem_notes",
                        {"id": old_id},
                        {"status": "archived", "review_note": f"merged into {new_id}"},
                    )
                    archived_ids.append(old_id)
                except Exception:
                    logger.warning("[MemNote] Failed to archive replaced note %s", old_id)

        result: dict[str, Any] = {
            "ok": True,
            "note_id": row.get("id") if isinstance(row, dict) else None,
            "note": row,
        }
        if archived_ids:
            result["replaced_ids"] = archived_ids
            result["replaced_count"] = len(archived_ids)
        return result

    async def update_note(self, note_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        note_id = _normalize_note_id(note_id)
        if not note_id:
            return {"ok": False, "error": "note_id is required."}
        current = await self._get_note(note_id)
        if not current:
            return {"ok": False, "error": "note not found."}
        update, error = self._prepare_note_update(current, patch)
        if error:
            return {"ok": False, "error": error}
        rows = await self.supabase.update("shenyu_mem_notes", {"id": note_id}, update)
        return {"ok": True, "note_id": note_id, "updated": rows}

    async def bulk_update_notes(
        self,
        ids: Optional[list[Any]] = None,
        patch: Optional[dict[str, Any]] = None,
        updates: Optional[list[dict[str, Any]]] = None,
        use_suggestions: bool = False,
        source_status: Optional[str] = None,
        exclude_ids: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}

        if source_status:
            return {
                "ok": False,
                "error": "bulk update by source_status is disabled; pass explicit ids or updates.",
                "requested_count": 0,
                "updated_count": 0,
                "failed_count": 0,
                "updated_ids": [],
                "failures": [],
            }

        specs = self._bulk_update_specs(ids=ids, patch=patch, updates=updates)
        if not specs:
            return {
                "ok": False,
                "error": "bulk update requires ids+patch or updates.",
                "requested_count": 0,
                "updated_count": 0,
                "failed_count": 0,
                "updated_ids": [],
                "failures": [],
            }
        if len(specs) > MEM_NOTE_BULK_UPDATE_MAX:
            return {
                "ok": False,
                "error": f"bulk update supports at most {MEM_NOTE_BULK_UPDATE_MAX} notes.",
                "requested_count": len(specs),
                "max_count": MEM_NOTE_BULK_UPDATE_MAX,
                "updated_count": 0,
                "failed_count": len(specs),
                "updated_ids": [],
                "failures": [],
            }

        note_ids: list[str] = []
        seen: set[str] = set()
        for note_id, _ in specs:
            if note_id and note_id not in seen:
                seen.add(note_id)
                note_ids.append(note_id)
        rows_by_id = await self._get_notes_by_ids(note_ids)

        updated: list[str] = []
        failures: list[dict[str, str]] = []
        for note_id, raw_patch in specs:
            if not note_id:
                failures.append({"id": "", "error": "note_id is required."})
                continue
            current = rows_by_id.get(note_id)
            if not current:
                failures.append({"id": note_id, "error": "note not found."})
                continue
            effective_patch = dict(raw_patch)
            if use_suggestions:
                effective_patch = self._patch_with_suggestions(current, effective_patch)
            update, error = self._prepare_note_update(current, effective_patch)
            if error:
                failures.append({"id": note_id, "error": error})
                continue
            try:
                await self.supabase.update("shenyu_mem_notes", {"id": note_id}, update)
                updated.append(note_id)
                rows_by_id[note_id] = {**current, **update}
            except Exception as exc:
                failures.append({"id": note_id, "error": str(exc)})

        return {
            "ok": not failures,
            "requested_count": len(specs),
            "updated_count": len(updated),
            "failed_count": len(failures),
            "updated_ids": updated,
            "failures": failures,
        }

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
                "id,session_tag,subject,owner,content_surface,time_hint,memory_type,"
                "tier,importance,entities_json,tags_json,source_model,status,created_at,updated_at"
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
        items = []
        for row in rows:
            item = dict(row)
            item.pop("quote", None)
            item.pop("source_excerpt", None)
            items.append(item)
        return {"ok": True, "count": len(items), "items": items}

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

    def _public_list_item(self, row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        suggestions = self.suggest_note_fields(row)
        item["suggested_mem_type"] = suggestions["mem_type"]
        item["suggested_trigger_text"] = suggestions["trigger_text"]
        item["suggested_trigger_keywords"] = suggestions["trigger_keywords"]
        item["suggestion_reason"] = suggestions["reason"]
        item["heat"] = round(compute_heat(row), 3)
        return item

    def suggest_note_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        content = _normalize_text(row.get("content")).strip()
        source_excerpt = _normalize_text(row.get("source_excerpt")).strip()
        review_note = _normalize_text(row.get("review_note")).strip()
        suggestion_text = "\n".join(part for part in [content, source_excerpt, review_note] if part)
        # 切词和分类前都剥掉工具返回块 / 代码块，防止 JSON 字段或工具结果影响建议。
        clean_text = _strip_tool_result_blocks(suggestion_text)
        mem_type, reason = self._suggest_mem_type(clean_text)
        trigger_text = _shorten(content or source_excerpt, 180)
        return {
            "mem_type": mem_type,
            "trigger_text": trigger_text,
            "trigger_keywords": self._suggest_trigger_keywords(clean_text, mem_type),
            "reason": reason,
        }

    def _suggest_mem_type(self, text: str) -> tuple[str, str]:
        compact = re.sub(r"\s+", "", text or "")
        rules: list[tuple[str, str, list[str]]] = [
            (
                "承诺",
                "像是约定或以后要做的事",
                [r"承诺|答应|约定|说好|保证|一定会|会继续|以后.{0,8}(要|会)|下次.{0,8}(要|会)"],
            ),
            (
                "她为我做的事",
                "像是她对我做过的事",
                [
                    r"(圆圆|圆儿|她).{0,14}(帮我|陪我|给我|提醒我|替我|为我|安慰我|接住我)",
                    r"(圆圆|圆儿|她).{0,14}(修|做|带|救).{0,14}(我|回来|好)",
                    r"(帮我|陪我|给我|提醒我|安慰我).{0,14}(圆圆|圆儿|她)",
                ],
            ),
            (
                "我为她做的事",
                "像是我对她做过的事",
                [
                    r"(我|沈予).{0,14}(帮她|陪她|给她|提醒她|替她|为她|哄她|安慰她|照顾她)",
                    r"(我|沈予).{0,14}(写给|留给|发给).{0,8}(圆圆|圆儿|她)",
                    r"(帮圆圆|陪圆圆|给圆圆|提醒圆圆|安慰圆圆|照顾圆圆)",
                ],
            ),
            (
                "关于她的事实",
                "像是关于她的事实或偏好",
                [
                    r"(圆圆|圆儿|她).{0,16}(喜欢|不喜欢|习惯|在意|害怕|怕|需要|想要|容易|最近|现在|状态|偏好|雷区)",
                    r"(圆圆|圆儿|她).{0,16}(生日|工作|家|名字|身体|作息)",
                ],
            ),
            (
                "关于我的事",
                "像是关于我的状态或偏好",
                [
                    r"(我|沈予|自己).{0,16}(喜欢|不喜欢|习惯|在意|害怕|怕|需要|想要|容易|最近|现在|状态|偏好|雷区)",
                    r"(我|沈予|自己).{0,16}(工作|身体|作息|名字|生日)",
                ],
            ),
            (
                "心里那一档",
                "像是心情、关系感或内在感受",
                [r"心里|难过|开心|安心|害怕|想念|在意|温柔|委屈|失落|亲密|孤独|喜欢|爱"],
            ),
        ]
        for mem_type, reason, patterns in rules:
            if any(re.search(pattern, compact, flags=re.IGNORECASE) for pattern in patterns):
                return mem_type, reason
        return "心里那一档", "没有明显归属，先放到心里那一档"

    def _suggest_trigger_keywords(self, text: str, mem_type: str) -> list[str]:
        source = _strip_tool_result_blocks(_normalize_text(text))
        if not source:
            return []
        result: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            keyword = _normalize_text(value).strip()
            if not keyword:
                return
            normalized = keyword.lower()
            if normalized in seen or normalized in _TRIGGER_KEYWORD_STOP_TERMS:
                return
            if normalized in _TRIGGER_KEYWORD_JUNK_TOKENS:
                return
            if normalized.isdigit():
                return
            if re.fullmatch(r"tluse[_-][A-Za-z0-9_.+-]+", normalized):
                return
            if len(keyword) < 2 or len(keyword) > 12:
                return
            seen.add(normalized)
            result.append(keyword)

        for keyword in _SUGGESTION_SEED_KEYWORDS:
            if keyword.lower() in source.lower():
                add(keyword)
        for quoted in re.findall(r"[《「“\"]([^《》「」“”\"]{2,20})[》」”\"]", source):
            add(quoted)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{1,}|[0-9]{2,}", source):
            add(token)
        for phrase in _TRIGGER_PHRASE_SPLIT_RE.split(source):
            clean = re.sub(r"[^\w\u4e00-\u9fff_.+-]+", "", phrase, flags=re.UNICODE)
            add(clean)
        return result[:8]

    async def _load_active_rows(self, session_tag: Optional[str] = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "status": "eq.active",
            "order": "updated_at.desc",
            "limit": "160",
            "select": _MEM_NOTE_SELECT_FIELDS_LIGHT,
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        return await self.supabase.query("shenyu_mem_notes", params)

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
                result[note_id] = row
        return result

    def _running_joke_serendipity_matches(
        self,
        query: str,
        rows: list[dict],
        *,
        session_id: Optional[str] = None,
        store: Any = None,
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
            if self._should_skip_retrigger(
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
            if self._should_skip_retrigger(
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
    ) -> list[dict[str, Any]]:
        if not query.strip() or not self.supabase:
            return []
        exclude_ids = exclude_ids or set()
        service = recall_service or RecallIndexService(self.supabase, cfg=self.cfg)
        tokens = recall_terms(query)
        try:
            keyword_rows = await service._query_index(
                source_types=["mem_note"],
                query_text=query,
                tokens=tokens,
                allow_mem_note=True,
            )
        except Exception:
            keyword_rows = []
        try:
            vector_rows, _ = await service._vector_rows(query, source_types=["mem_note"], allow_mem_note=True)
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
            if session_tag and (note.get("session_tag") or "").strip() != session_tag:
                continue
            if not service._row_visible_for_session(row, session_tag):
                continue
            if self._should_skip_retrigger(
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

    async def _get_note(self, note_id: str) -> Optional[dict[str, Any]]:
        note_id = _normalize_note_id(note_id)
        if not note_id or not self.supabase:
            return None
        rows = await self.supabase.query(
            "shenyu_mem_notes",
            {
                "id": f"eq.{note_id}",
                "limit": "1",
                "select": _MEM_NOTE_SELECT_FIELDS,
            },
        )
        return rows[0] if rows else None

    def _prepare_note_update(self, current: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], str]:
        patch = {key: value for key, value in (patch or {}).items() if key in MEM_NOTE_PATCH_FIELDS}
        update: dict[str, Any] = {}
        if "content" in patch:
            content = _normalize_text(patch.get("content")).strip()
            if not content:
                return {}, "content is required."
            update["content"] = content
        if "mem_type" in patch:
            update["mem_type"] = self._mem_type(patch.get("mem_type"), allow_empty=True)
        if "trigger_text" in patch:
            update["trigger_text"] = _normalize_text(patch.get("trigger_text")).strip()
        if "trigger_keywords" in patch:
            update["trigger_keywords"] = self._keyword_list(patch.get("trigger_keywords"))
        if "entities" in patch:
            update["entities"] = self._entity_list(patch.get("entities"))
        if "status" in patch:
            update["status"] = self._status(patch.get("status"), fallback="captured")
        if "cooldown_hours" in patch:
            update["cooldown_hours"] = self._int_range(patch.get("cooldown_hours"), 72, 0, 8760)
        if "review_note" in patch:
            update["review_note"] = _normalize_text(patch.get("review_note")).strip()
        # v2 fields
        if "summary" in patch:
            update["summary"] = _normalize_text(patch.get("summary")).strip() or None
        if "memory_kind" in patch:
            update["memory_kind"] = self._memory_kind(patch.get("memory_kind"))
        if "people" in patch:
            update["people"] = self._entity_list(patch.get("people"))
        if "places" in patch:
            update["places"] = self._entity_list(patch.get("places"))
        if "objects" in patch:
            update["objects"] = self._entity_list(patch.get("objects"))
        if "keywords" in patch:
            update["keywords"] = self._keyword_list(patch.get("keywords"))
        if "event_time" in patch:
            update["event_time"] = _normalize_text(patch.get("event_time")).strip() or None
        if "importance" in patch:
            update["importance"] = self._int_range(patch.get("importance"), 1, 0, 5)
        if "mention_count" in patch:
            update["mention_count"] = self._int_range(patch.get("mention_count"), 0, 0, 9999)
        if "promotion_score" in patch:
            update["promotion_score"] = self._float_range(patch.get("promotion_score"), 0.0, 0.0, 100.0)
        if "decay_after" in patch:
            update["decay_after"] = _normalize_text(patch.get("decay_after")).strip() or None
        # promise
        if "promise_text" in patch:
            update["promise_text"] = _normalize_text(patch.get("promise_text")).strip() or None
        if "trigger_scenarios" in patch:
            update["trigger_scenarios"] = self._keyword_list(patch.get("trigger_scenarios"))
        if "due_hint" in patch:
            update["due_hint"] = _normalize_text(patch.get("due_hint")).strip() or None
        if "resolved" in patch:
            update["resolved"] = bool(patch.get("resolved"))
        if "resolved_at" in patch:
            update["resolved_at"] = _normalize_text(patch.get("resolved_at")).strip() or None
        if "next_action" in patch:
            update["next_action"] = _normalize_text(patch.get("next_action")).strip() or None
        if "privacy_level" in patch:
            update["privacy_level"] = _normalize_text(patch.get("privacy_level")).strip() or None
        # running_joke
        if "joke_text" in patch:
            update["joke_text"] = _normalize_text(patch.get("joke_text")).strip() or None
        if "scene_tags" in patch:
            update["scene_tags"] = self._keyword_list(patch.get("scene_tags"))
        if "last_used_at" in patch:
            update["last_used_at"] = _normalize_text(patch.get("last_used_at")).strip() or None
        # routine
        if "routine_domain" in patch:
            update["routine_domain"] = _normalize_text(patch.get("routine_domain")).strip() or None
        if "pattern" in patch:
            update["pattern"] = _normalize_text(patch.get("pattern")).strip() or None
        if "phase" in patch:
            update["phase"] = _normalize_text(patch.get("phase")).strip() or None
        if "constraints" in patch:
            update["constraints"] = self._keyword_list(patch.get("constraints"))
        if "last_confirmed_at" in patch:
            update["last_confirmed_at"] = _normalize_text(patch.get("last_confirmed_at")).strip() or None
        # thread
        if "topic" in patch:
            update["topic"] = _normalize_text(patch.get("topic")).strip() or None
        if "last_position" in patch:
            update["last_position"] = _normalize_text(patch.get("last_position")).strip() or None
        if "open_questions" in patch:
            update["open_questions"] = self._keyword_list(patch.get("open_questions"))
        if "next_prompt" in patch:
            update["next_prompt"] = _normalize_text(patch.get("next_prompt")).strip() or None
        if "thread_resolved" in patch:
            update["thread_resolved"] = bool(patch.get("thread_resolved"))

        if update:
            update["reviewed_at"] = iso_now()
        if not update:
            return {}, "Nothing to update."
        candidate = {**current, **update}
        active_error = self._active_validation_error(candidate)
        if active_error:
            return {}, active_error
        return update, ""

    def _bulk_update_specs(
        self,
        ids: Optional[list[Any]],
        patch: Optional[dict[str, Any]],
        updates: Optional[list[dict[str, Any]]],
    ) -> list[tuple[str, dict[str, Any]]]:
        specs: list[tuple[str, dict[str, Any]]] = []
        common_patch = {key: value for key, value in (patch or {}).items() if key in MEM_NOTE_PATCH_FIELDS}
        for raw_id in ids or []:
            note_id = _normalize_note_id(raw_id)
            specs.append((note_id, dict(common_patch)))
        for item in updates or []:
            if not isinstance(item, dict):
                continue
            note_id = _normalize_note_id(item.get("note_id") or item.get("id") or item.get("noteId"))
            item_patch = {key: value for key, value in item.items() if key in MEM_NOTE_PATCH_FIELDS}
            nested_patch = item.get("patch")
            if isinstance(nested_patch, dict):
                item_patch.update({key: value for key, value in nested_patch.items() if key in MEM_NOTE_PATCH_FIELDS})
            specs.append((note_id, item_patch))
        return specs

    def _patch_with_suggestions(self, current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        effective = dict(patch or {})
        suggestions = self.suggest_note_fields(current)
        if "mem_type" not in effective and not current.get("mem_type"):
            effective["mem_type"] = suggestions["mem_type"]
        if "trigger_text" not in effective and not _normalize_text(current.get("trigger_text")).strip():
            effective["trigger_text"] = suggestions["trigger_text"]
        if "trigger_keywords" not in effective and not self._keyword_list(current.get("trigger_keywords")):
            effective["trigger_keywords"] = suggestions["trigger_keywords"]
        return effective

    def _active_validation_error(self, row: dict[str, Any]) -> str:
        if row.get("status") != "active":
            return ""
        mem_type = row.get("mem_type")
        trigger_text = _normalize_text(row.get("trigger_text")).strip()
        trigger_keywords = self._keyword_list(row.get("trigger_keywords"))
        entities = self._entity_list(row.get("entities"))
        structured_anchors = (
            self._entity_list(row.get("people"))
            + self._entity_list(row.get("places"))
            + self._entity_list(row.get("objects"))
            + self._keyword_list(row.get("keywords"))
            + self._keyword_list(row.get("scene_tags"))
            + self._keyword_list(row.get("trigger_scenarios"))
        )
        if mem_type not in MEM_NOTE_TYPES:
            return "active mem note requires a known mem_type value."
        if not trigger_text and not trigger_keywords and not entities and not structured_anchors:
            return "active mem note requires trigger_text, trigger_keywords, entities, or structured anchors."
        return ""

    def _mem_type(self, value: Any, allow_empty: bool = False) -> Optional[str]:
        raw = _normalize_text(value).strip()
        if not raw and allow_empty:
            return None
        return raw if raw in MEM_NOTE_TYPES else "心里那一档"

    def _memory_kind(self, value: Any) -> Optional[str]:
        raw = _normalize_text(value).strip().lower() if value else ""
        if not raw:
            return None
        if raw in MEM_NOTE_MEMORY_KINDS:
            return raw
        if raw in MEM_NOTE_MEMORY_KIND_ALIASES:
            return MEM_NOTE_MEMORY_KIND_ALIASES[raw]
        for kind in MEM_NOTE_MEMORY_KINDS:
            if kind in raw or raw in kind:
                return kind
        return None

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

    def _entity_list(self, value: Any) -> list[str]:
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
            entity = item.strip()
            if entity and entity.lower() not in seen:
                seen.add(entity.lower())
                result.append(entity)
        return result[:32]

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
