from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shenyu_gateway.memory_graph import MemoryGraphService
from shenyu_gateway.runtime import logger
from shenyu_gateway.utils import normalize_text as _normalize_text

from ._base import RECALL_INDEX_TABLE
from ._documents import RecallDocument, _make_documents
from ._text import _json_list


class SourcesMixin:
    async def rebuild(self, source_types: Optional[list[str]] = None, *, embed: bool = True) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}

        adapters = self._adapter_names(source_types)
        total_docs = 0
        source_counts: dict[str, int] = {}
        errors: dict[str, str] = {}
        for name in adapters:
            try:
                docs = await self._load_documents(name)
                await self._upsert_documents(docs)
                await self._mark_stale_source_deleted(name, docs)
                await self._sync_graph_documents_fail_soft(docs)
                total_docs += len(docs)
                source_counts[name] = len(docs)
            except Exception as exc:
                errors[name] = str(exc)
        result = {
            "ok": not errors,
            "indexed": total_docs,
            "sources": source_counts,
            "errors": errors,
        }
        if embed and not errors:
            result["embedding"] = await self.embed_pending(limit=500)
        return result

    async def index_windowsill_row(self, row: dict[str, Any]) -> dict[str, Any]:
        docs = self._windowsill_documents(row)
        if not docs:
            return {"ok": False, "indexed": 0, "error": "windowsill row has no content."}
        await self._upsert_documents(docs)
        await self._sync_graph_documents_fail_soft(docs)
        return {"ok": True, "indexed": len(docs)}

    async def index_mem_note_row(self, row: dict[str, Any]) -> dict[str, Any]:
        source_id = str(row.get("id") or "").strip()
        if not source_id:
            return {"ok": False, "indexed": 0, "error": "mem note row has no id."}
        if str(row.get("status") or "") != "active":
            await self.mark_source_row_deleted("shenyu_mem_notes", source_id)
            return {"ok": True, "indexed": 0, "deleted": True}
        docs = self._mem_note_documents(row)
        if not docs:
            return {"ok": False, "indexed": 0, "error": "mem note row has no content."}
        await self._upsert_documents(docs)
        await self._sync_graph_documents_fail_soft(docs)
        return {"ok": True, "indexed": len(docs)}

    async def _sync_graph_documents_fail_soft(self, docs: list[RecallDocument]) -> None:
        try:
            result = await MemoryGraphService(self.supabase).sync_recall_documents(docs)
            if not result.get("ok"):
                logger.warning("Memory graph mention sync was partial: %s", result.get("errors"))
        except Exception as exc:
            logger.info("Memory graph is not ready; recall indexing continues without it: %s", exc)

    async def mark_source_row_deleted(self, source_table: str, source_id: str) -> None:
        await self.supabase.update(
            RECALL_INDEX_TABLE,
            {"source_table": source_table, "source_id": source_id},
            {"deleted_at": datetime.now(timezone.utc).isoformat()},
        )

    async def _upsert_documents(self, docs: list[RecallDocument]) -> None:
        if not docs:
            return
        existing_hashes = await self._existing_content_hashes(docs[0].source_table)
        rows = []
        for doc in docs:
            row = doc.to_row()
            key = (doc.source_id, doc.chunk_index)
            if existing_hashes.get(key) != doc.content_hash:
                row.update(
                    {
                        "embedding": None,
                        "embedding_model": None,
                        "embedding_status": "pending" if doc.embedding_text else "skipped",
                        "embedding_error": None,
                        "embedded_at": None,
                    }
                )
            rows.append(row)
        if hasattr(self.supabase, "upsert"):
            rows_by_columns: dict[tuple[str, ...], list[dict[str, Any]]] = {}
            for row in rows:
                rows_by_columns.setdefault(tuple(sorted(row)), []).append(row)
            upsert = getattr(self.supabase, "upsert_minimal", self.supabase.upsert)
            for matching_rows in rows_by_columns.values():
                for start in range(0, len(matching_rows), 100):
                    await upsert(
                        RECALL_INDEX_TABLE,
                        matching_rows[start : start + 100],
                        on_conflict="source_table,source_id,chunk_index",
                    )
            return

        for row in rows:
            match = {
                "source_table": row["source_table"],
                "source_id": row["source_id"],
                "chunk_index": row["chunk_index"],
            }
            updated = await self.supabase.update(RECALL_INDEX_TABLE, match, row)
            if not updated:
                await self.supabase.insert(RECALL_INDEX_TABLE, row)

    async def _existing_content_hashes(self, source_table: str) -> dict[tuple[str, int], str]:
        rows = await self._query_all_rows(
            RECALL_INDEX_TABLE,
            {
                "select": "source_id,chunk_index,content_hash",
                "source_table": f"eq.{source_table}",
                "order": "source_id.asc,chunk_index.asc",
            },
        )
        hashes: dict[tuple[str, int], str] = {}
        for row in rows:
            hashes[(str(row.get("source_id") or ""), int(row.get("chunk_index") or 0))] = str(row.get("content_hash") or "")
        return hashes

    def _adapter_names(self, source_types: Optional[list[str]] = None) -> list[str]:
        mapping = {
            "journal": "journal",
            "windowsill": "windowsill",
            "heartbeat": "shenyu_heartbeat_archive",
            "room": "room",
            "board": "message_board",
            "message_board": "message_board",
            "memory": "memories",
            "memories": "memories",
            "calendar": "calendar_pages",
            "mem_note": "shenyu_mem_notes",
            "notebook": "shenyu_notebook",
        }
        requested = self._requested_source_types(source_types)
        if not requested:
            return [
                "journal",
                "windowsill",
                "shenyu_heartbeat_archive",
                "room",
                "message_board",
                "memories",
                "calendar_pages",
                "shenyu_mem_notes",
                "shenyu_notebook",
            ]
        names = []
        for source_type in requested:
            mapped = mapping.get(str(source_type).strip())
            if mapped and mapped not in names:
                names.append(mapped)
        return names

    async def _load_documents(self, source_table: str) -> list[RecallDocument]:
        loaders = {
            "journal": self._load_journal,
            "windowsill": self._load_windowsill,
            "shenyu_heartbeat_archive": self._load_heartbeat_archive,
            "room": self._load_room,
            "message_board": self._load_message_board,
            "memories": self._load_memories,
            "calendar_pages": self._load_calendar_pages,
            "shenyu_mem_notes": self._load_mem_notes,
            "atomic_memories": self._load_atomic_memories,
            "shenyu_notebook": self._load_notebook,
            "meta_summaries": self._load_meta_summaries,
        }
        return await loaders[source_table]()

    def _windowsill_documents(self, row: dict[str, Any]) -> list[RecallDocument]:
        mood = _normalize_text(row.get("mood")).strip()
        origin = _normalize_text(row.get("origin")).strip() or "normal"
        metadata = {}
        if mood:
            metadata["mood"] = mood
        if origin == "room":
            metadata["origin"] = origin
        return _make_documents(
            source_table="windowsill",
            source_id=row.get("id"),
            source_type="windowsill",
            title=row.get("title"),
            body=row.get("content"),
            tags=[mood] if mood else [],
            metadata=metadata,
            event_date=row.get("created_at"),
            created_at=row.get("created_at"),
            updated_at=row.get("created_at"),
            status="active",
            importance=0.7,
        )

    async def _load_windowsill(self) -> list[RecallDocument]:
        rows = await self._query_all_rows(
            "windowsill",
            {"select": "*", "order": "created_at.desc"},
        )
        docs = []
        for row in rows:
            docs.extend(self._windowsill_documents(row))
        return docs

    async def _load_heartbeat_archive(self) -> list[RecallDocument]:
        rows = await self._query_all_rows(
            "shenyu_heartbeat_archive",
            {
                "select": "*",
                "scope": "eq.normal",
                "deleted_at": "is.null",
                "order": "created_at.desc",
            },
        )
        docs = []
        for row in rows:
            docs.extend(
                _make_documents(
                    source_table="shenyu_heartbeat_archive",
                    source_id=row.get("id"),
                    source_type="heartbeat",
                    title="",
                    body=row.get("content"),
                    metadata={"scope": "normal"},
                    event_date=row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("archived_at") or row.get("created_at"),
                    status="active",
                    importance=0.68,
                    chunk=False,
                )
            )
        return docs

    async def _load_journal(self) -> list[RecallDocument]:
        rows = await self._query_all_rows(
            "journal",
            {"select": "*", "order": "updated_at.desc"},
        )
        docs = []
        for row in rows:
            tags = [row.get("category"), row.get("mood"), row.get("author"), "favorited" if row.get("is_favorited") else ""]
            docs.extend(
                _make_documents(
                    source_table="journal",
                    source_id=row.get("id"),
                    source_type="journal",
                    title=row.get("title"),
                    body=row.get("content"),
                    session_tag=row.get("session_tag"),
                    tags=tags,
                    metadata={"category": row.get("category"), "mood": row.get("mood"), "temperature": row.get("temperature")},
                    event_date=row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status="active",
                    importance=0.85 if row.get("is_favorited") else 0.65,
                )
            )
        return docs

    async def _load_room(self) -> list[RecallDocument]:
        rows = await self._query_all_rows("room", {"select": "*", "order": "updated_at.desc"})
        docs = []
        for row in rows:
            tags = _json_list(row.get("tags")) + [row.get("mood")]
            docs.extend(
                _make_documents(
                    source_table="room",
                    source_id=row.get("id"),
                    source_type="room",
                    title=row.get("title") or "room",
                    body=row.get("content"),
                    session_tag=row.get("session_tag"),
                    tags=tags,
                    metadata={"mood": row.get("mood")},
                    event_date=row.get("updated_at") or row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    visibility=row.get("visibility"),
                    importance=0.9,
                )
            )
        return docs

    async def _load_message_board(self) -> list[RecallDocument]:
        rows = await self._query_all_rows("message_board", {"select": "*", "order": "created_at.desc"})
        docs = []
        for row in rows:
            docs.extend(
                _make_documents(
                    source_table="message_board",
                    source_id=row.get("id"),
                    source_type="board",
                    title=f"Message from {row.get('sender') or 'unknown'}",
                    body=row.get("content"),
                    tags=[row.get("sender")],
                    event_date=row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("created_at"),
                    status="active",
                    importance=0.55,
                    chunk=False,
                )
            )
        return docs

    async def _load_memories(self) -> list[RecallDocument]:
        rows = await self._query_all_rows(
            "memories",
            {"select": "*", "is_deleted": "eq.false", "order": "weight.desc,date.desc"},
        )
        tag_rows = await self._query_all_rows(
            "memory_tags",
            {"select": "memory_id,tag,tag_type", "order": "memory_id.asc"},
        )
        tags_by_memory: dict[str, list[str]] = {}
        entities_by_memory: dict[str, list[str]] = {}
        for tag in tag_rows:
            memory_id = str(tag.get("memory_id"))
            target = entities_by_memory if str(tag.get("tag_type") or "").lower() == "entity" else tags_by_memory
            target.setdefault(memory_id, []).append(tag.get("tag"))
        docs = []
        for row in rows:
            memory_id = str(row.get("id"))
            body = "\n\n".join(
                part
                for part in [
                    row.get("summary"),
                    row.get("facts"),
                    row.get("emotional_context"),
                    row.get("detailed_content"),
                ]
                if part
            )
            tags = _json_list(row.get("emotions")) + _json_list(row.get("type")) + tags_by_memory.get(memory_id, [])
            weight = float(row.get("weight") or 1.0)
            importance = min(1.0, (float(row.get("importance") or 3) / 5.0) * 0.65 + min(weight / 2.0, 0.35))
            docs.extend(
                _make_documents(
                    source_table="memories",
                    source_id=memory_id,
                    source_type="memory",
                    title=row.get("title"),
                    body=body,
                    session_tag=row.get("session_tag"),
                    tags=tags,
                    entities=entities_by_memory.get(memory_id, []),
                    metadata={"type": row.get("type"), "emotions": row.get("emotions"), "source_model": row.get("source_model")},
                    event_date=row.get("date"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at") or row.get("last_activated"),
                    status="active",
                    importance=importance,
                )
            )
        return docs

    async def _load_calendar_pages(self) -> list[RecallDocument]:
        rows = await self._query_all_rows(
            "calendar_pages",
            {"select": "*", "is_latest": "eq.true", "status": "eq.final", "order": "period_start.desc"},
        )
        docs = []
        for row in rows:
            body = "\n\n".join(part for part in [row.get("summary"), row.get("digest"), row.get("content")] if part)
            docs.extend(
                _make_documents(
                    source_table="calendar_pages",
                    source_id=row.get("id"),
                    source_type="calendar",
                    title=row.get("title") or row.get("period_key"),
                    body=body,
                    tags=[row.get("period_type"), row.get("period_key"), row.get("author")],
                    metadata={
                        "period_type": row.get("period_type"),
                        "period_key": row.get("period_key"),
                        "period_end": row.get("period_end"),
                        "source_refs": row.get("source_refs"),
                        "session_tags": row.get("session_tags"),
                    },
                    event_date=row.get("period_start"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    importance=0.76,
                )
            )
        return docs

    async def _load_mem_notes(self) -> list[RecallDocument]:
        rows = await self._query_all_rows(
            "shenyu_mem_notes",
            {"select": "*", "status": "eq.active", "order": "updated_at.desc"},
        )
        docs = []
        for row in rows:
            docs.extend(self._mem_note_documents(row))
        return docs

    def _mem_note_documents(self, row: dict[str, Any]) -> list[RecallDocument]:
        return _make_documents(
            source_table="shenyu_mem_notes",
            source_id=row.get("id"),
            source_type="mem_note",
            title="",
            body=row.get("content"),
            session_tag=row.get("session_tag"),
            event_date=row.get("event_time") or row.get("updated_at"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            status=row.get("status"),
            importance=0.5,
            chunk=False,
        )

    async def _load_atomic_memories(self) -> list[RecallDocument]:
        rows = await self._query_all_rows(
            "atomic_memories",
            {"select": "*", "status": "eq.active", "order": "heat.desc,importance.desc,updated_at.desc"},
        )
        docs = []
        for row in rows:
            tags = _json_list(row.get("tags_json")) + [row.get("memory_type"), row.get("owner"), row.get("applies_to")]
            body = row.get("content_surface") or ""
            importance = min(1.0, float(row.get("importance") or 3) / 5.0 * 0.55 + float(row.get("heat") or 0.5) * 0.45)
            docs.extend(
                _make_documents(
                    source_table="atomic_memories",
                    source_id=row.get("id"),
                    source_type="atomic",
                    title=" ".join(part for part in [row.get("subject"), row.get("memory_type"), row.get("time_hint")] if part),
                    body=body,
                    session_tag=row.get("session_tag"),
                    tags=tags,
                    entities=_json_list(row.get("entities_json")),
                    metadata={"tier": row.get("tier"), "speaker_perspective": row.get("speaker_perspective")},
                    event_date=row.get("valid_from") or row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    importance=importance,
                    chunk=False,
                )
            )
        return docs

    async def _load_notebook(self) -> list[RecallDocument]:
        rows = await self._query_all_rows("shenyu_notebook", {"select": "*", "order": "updated_at.desc"})
        docs = []
        for row in rows:
            docs.extend(
                _make_documents(
                    source_table="shenyu_notebook",
                    source_id=row.get("id"),
                    source_type="notebook",
                    title=f"{row.get('type') or 'note'}{' pinned' if row.get('pinned') else ''}",
                    body=row.get("content"),
                    session_tag=row.get("session_tag"),
                    tags=_json_list(row.get("tags")) + [row.get("type")],
                    metadata=row.get("metadata"),
                    event_date=row.get("updated_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    importance=0.9 if row.get("pinned") else 0.65,
                )
            )
        return docs

    async def _load_meta_summaries(self) -> list[RecallDocument]:
        rows = await self._query_all_rows(
            "meta_summaries",
            {"select": "*", "is_active": "eq.true", "order": "priority.desc,last_updated.desc"},
        )
        docs = []
        for row in rows:
            docs.extend(
                _make_documents(
                    source_table="meta_summaries",
                    source_id=row.get("id"),
                    source_type="meta",
                    title=row.get("title"),
                    body=row.get("content"),
                    session_tag=row.get("session_tag"),
                    tags=[row.get("category")],
                    metadata={"category": row.get("category"), "source_model": row.get("source_model")},
                    event_date=row.get("last_updated"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("last_updated"),
                    status="active" if row.get("is_active") else "inactive",
                    importance=min(1.0, float(row.get("priority") or 1) / 5.0),
                )
            )
        return docs
