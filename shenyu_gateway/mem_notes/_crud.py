from __future__ import annotations

from typing import Any, Optional

from shenyu_gateway.runtime import logger
from shenyu_gateway.utils import normalize_text as _normalize_text
from ..mem_notes_relevance import (
    _auto_extract_entities,
    _auto_extract_keywords,
    _auto_extract_objects,
    _auto_extract_people,
    _auto_extract_places,
    _auto_generate_summary,
    _infer_memory_kind,
    _terms,
)
from ..runtime import iso_now
from ._helpers import (
    MEM_NOTE_BULK_UPDATE_MAX,
    MEM_NOTE_MEMORY_KINDS,
    MEM_NOTE_PATCH_FIELDS,
    MEM_NOTE_TYPES,
    _MEM_NOTE_SELECT_FIELDS,
    _normalize_note_id,
)


class CrudMixin:

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

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

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
