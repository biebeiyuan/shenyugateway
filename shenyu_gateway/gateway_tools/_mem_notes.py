from __future__ import annotations

from typing import Any, Optional

from shenyu_gateway.runtime import logger


class MemNoteToolsMixin:
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
