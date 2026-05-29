from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.mem_notes import MemNoteService, _clean_context_query


class FakeSupabase:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []
        self.updates = []

    async def query(self, table: str, params: dict):
        self.queries.append({"table": table, "params": params})
        if params.get("id") == "eq.88eb939b-8742-4e17-8186-3de6a3e9a016":
            return [
                {
                    "id": "88eb939b-8742-4e17-8186-3de6a3e9a016",
                    "content": "note",
                    "status": "captured",
                    "trigger_keywords": [],
                }
            ]
        if params.get("id", "").startswith("in.("):
            wanted = {item.strip() for item in params["id"].removeprefix("in.").strip("()").split(",") if item.strip()}
            return [row for row in self.rows if row.get("id") in wanted]
        if table == "shenyu_mem_notes":
            rows = list(self.rows)
            status_filter = params.get("status")
            if status_filter and status_filter.startswith("eq."):
                rows = [row for row in rows if row.get("status") == status_filter.removeprefix("eq.")]
            session_filter = params.get("session_tag")
            if session_filter and session_filter.startswith("eq."):
                rows = [row for row in rows if row.get("session_tag") == session_filter.removeprefix("eq.")]
            return rows
        return []

    async def update(self, table: str, match: dict, data: dict):
        self.updates.append({"table": table, "match": match, "data": data})
        return [{"id": match["id"], **data}]


def test_update_note_normalizes_uuid_from_pasted_text():
    supabase = FakeSupabase()
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.update_note(
            "id: 88eb939b-8742-4e17-8186-3de6a3e9a016.",
            {"review_note": "checked"},
        )
    )

    assert result["ok"] is True
    assert result["note_id"] == "88eb939b-8742-4e17-8186-3de6a3e9a016"
    assert supabase.queries[0]["params"]["id"] == "eq.88eb939b-8742-4e17-8186-3de6a3e9a016"
    assert supabase.updates[0]["match"] == {"id": "88eb939b-8742-4e17-8186-3de6a3e9a016"}


def test_clean_context_query_removes_operit_extra_bundle_attachment():
    query = (
        "圆儿在说工具提醒 "
        "<attachment id=\"message_insert_extra_bundle_123\">很长的设备状态 工具 关键词</attachment>"
        " 工作描述"
    )

    clean = _clean_context_query(query)

    assert clean == "圆儿在说工具提醒 工作描述"
    assert "message_insert_extra_bundle" not in clean
    assert "设备状态" not in clean


class FakeRecallService:
    def __init__(self, rows):
        self.rows = rows

    async def _query_index(self, source_types=None, query_text="", tokens=None):
        return []

    async def _vector_rows(self, query, source_types=None):
        return self.rows, {"enabled": True, "used": True, "count": len(self.rows)}

    def _merge_candidate_rows(self, keyword_rows, vector_rows):
        merged = list(keyword_rows)
        seen = {(row.get("source_table"), row.get("source_id"), row.get("chunk_index", 0)) for row in merged}
        for row in vector_rows:
            key = (row.get("source_table"), row.get("source_id"), row.get("chunk_index", 0))
            if key not in seen:
                merged.append(row)
                seen.add(key)
        return merged

    def _row_visible_for_session(self, row, session_tag):
        return row.get("session_tag") == session_tag

    def _score_row(self, row, query, tokens):
        return row.get("_score", 0.7), row.get("_reasons", ["semantic"])

    def _has_direct_match(self, reasons):
        return any(reason.startswith("keyword:") or reason in {"title", "tag/entity", "phrase"} for reason in reasons)


def test_contextual_search_uses_semantic_fallback_without_changing_keyword_search():
    note = {
        "id": "note-1",
        "session_tag": "5.15",
        "content": "工具是我的手。",
        "mem_type": "心里那一档",
        "trigger_text": "工具是我的手",
        "trigger_keywords": ["工具"],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    supabase = FakeSupabase(rows=[note])
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72, mem_note_min_score=0.95), supabase)
    recall = FakeRecallService(
        [
            {
                "source_table": "shenyu_mem_notes",
                "source_id": "note-1",
                "source_type": "mem_note",
                "chunk_index": 0,
                "session_tag": "5.15",
                "search_text": "工具是我的手",
                "search_tokens": ["工具"],
                "tags_json": [],
                "entities_json": [],
                "importance": 0.82,
                "source_updated_at": "2026-05-24T00:00:00+00:00",
                "status": "active",
                "_vector_score": 0.86,
                "_score": 0.72,
                "_reasons": ["keyword:工具", "semantic"],
            }
        ]
    )

    keyword_result = asyncio.run(service.search_notes("工具提醒 工作描述", session_tag="5.15", mark_triggered=False))
    contextual_result = asyncio.run(
        service.search_notes_contextual(
            "工具提醒 工作描述",
            session_tag="5.15",
            mark_triggered=False,
            recall_service=recall,
        )
    )

    assert keyword_result["count"] == 0
    assert contextual_result["count"] == 1
    assert contextual_result["items"][0]["id"] == "note-1"
    assert contextual_result["items"][0]["search_mode"] == "semantic"
