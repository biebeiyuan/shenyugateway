from __future__ import annotations

import asyncio
import json
import pytest
from types import SimpleNamespace

from shenyu_gateway.room_context import render_room_layers, visible_room_tool_names
from shenyu_gateway.room_tools import collect_door_counts, room_tool_definitions
from shenyu_gateway.tool_registry import execute_gateway_tool, gateway_native_tools, merge_tools
from shenyu_gateway.tool_loop import _classify_tool_error, _tool_call_arguments


class FakeToolService:
    def __init__(self):
        self.calls = []

    async def surface_passages(self, query: str, session_tag: str, limit: int):
        self.calls.append(
            {
                "tool": "shenyu_surface_passages",
                "query": query,
                "session_tag": session_tag,
                "limit": limit,
            }
        )
        return {"ok": True, "limit": limit, "session_tag": session_tag}

    async def search_mem_notes(
        self,
        query: str,
        session_tag: str,
        limit: int,
        status: str = "all",
        mem_type=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_search_mem_notes",
                "query": query,
                "session_tag": session_tag,
                "limit": limit,
                "status": status,
                "mem_type": mem_type,
            }
        )
        return {"ok": True, "query": query, "status": status, "limit": limit}

    async def list_mem_notes(
        self,
        status: str = "captured",
        limit: int = 30,
        session_tag: str = None,
        q: str = "",
        mem_type=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_list_mem_notes",
                "q": q,
                "session_tag": session_tag,
                "limit": limit,
                "status": status,
                "mem_type": mem_type,
            }
        )
        return {"ok": True, "q": q, "status": status, "limit": limit}

    async def search_primary_texts(self, query: str, categories=None, session_tag=None, limit: int = 5):
        self.calls.append(
            {
                "tool": "shenyu_search_primary_texts",
                "query": query,
                "categories": categories,
                "session_tag": session_tag,
                "limit": limit,
            }
        )
        return {"ok": True, "query": query, "limit": limit}

    async def recall(
        self,
        query: str,
        source_types=None,
        session_tag=None,
        date_from=None,
        date_to=None,
        include_undated: bool = True,
        limit: int = 8,
        auto_sync: bool = True,
    ):
        self.calls.append(
            {
                "tool": "shenyu_recall",
                "query": query,
                "source_types": source_types,
                "session_tag": session_tag,
                "date_from": date_from,
                "date_to": date_to,
                "include_undated": include_undated,
                "limit": limit,
                "auto_sync": auto_sync,
            }
        )
        return {"ok": True, "query": query, "limit": limit}

    async def ask_memory(
        self,
        query: str,
        session_tag: str | None,
        limit: int = 8,
        date=None,
        date_from=None,
        date_to=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_ask_memory",
                "query": query,
                "session_tag": session_tag,
                "limit": limit,
                "date": date,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return {"ok": True, "query": query, "limit": limit}

    async def add_calendar(
        self,
        content: str,
        period_key=None,
        period_type="day",
        title="",
        summary="",
        digest="",
        author="沈予",
        mode="append",
    ):
        self.calls.append(
            {
                "tool": "shenyu_add_calendar",
                "content": content,
                "period_key": period_key,
                "period_type": period_type,
                "title": title,
                "summary": summary,
                "digest": digest,
                "author": author,
                "mode": mode,
            }
        )
        return {"ok": True, "content": content, "period_type": period_type}

    async def supabase_guide(self):
        self.calls.append({"tool": "shenyu_supabase_guide"})
        return {"ok": True, "guide": "fake"}

    async def write_mem_note(
        self,
        content: str,
        session_tag: str,
        mem_type=None,
        trigger_text="",
        trigger_keywords=None,
        entities=None,
        status="active",
        cooldown_hours=None,
        review_note="",
        replaces=None,
        **kwargs,
    ):
        self.calls.append(
            {
                "tool": "shenyu_write_mem_note",
                "content": content,
                "session_tag": session_tag,
                "mem_type": mem_type,
                "trigger_text": trigger_text,
                "trigger_keywords": trigger_keywords,
                "status": status,
                "cooldown_hours": cooldown_hours,
                "review_note": review_note,
                "replaces": replaces,
            }
        )
        return {"ok": True, "content": content, "status": status, "session_tag": session_tag}

    async def update_mem_note(self, note_id: str, patch: dict):
        self.calls.append(
            {
                "tool": "shenyu_update_mem_note",
                "note_id": note_id,
                "patch": patch,
            }
        )
        return {"ok": True, "note_id": note_id, "patch": patch}

    async def bulk_update_mem_notes(self, ids=None, patch=None, updates=None, use_suggestions=False, source_status=None, exclude_ids=None):
        self.calls.append(
            {
                "tool": "shenyu_bulk_update_mem_notes",
                "ids": ids,
                "patch": patch,
                "updates": updates,
                "use_suggestions": use_suggestions,
                "source_status": source_status,
                "exclude_ids": exclude_ids,
            }
        )
        return {"ok": True, "updated_count": len(ids or []) + len(updates or [])}

    async def delete_mem_note(self, note_id: str):
        self.calls.append(
            {
                "tool": "shenyu_delete_mem_note",
                "note_id": note_id,
            }
        )
        return {"ok": True, "note_id": note_id}

    async def create_star(
        self,
        content,
        chord="",
        chords=None,
        session_tag=None,
        status="active",
        is_constant=False,
        metadata=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_create_star",
                "content": content,
                "chord": chord,
                "chords": chords,
                "session_tag": session_tag,
                "status": status,
                "is_constant": is_constant,
                "metadata": metadata,
            }
        )
        return {"ok": True, "content": content}

    async def list_stars(self, status="active", limit=50, session_tag=None, q="", reviewed="all"):
        self.calls.append(
            {
                "tool": "shenyu_list_stars",
                "status": status,
                "limit": limit,
                "session_tag": session_tag,
                "q": q,
                "reviewed": reviewed,
            }
        )
        return {"ok": True, "limit": limit}

    async def search_stars(self, query="", session_tag=None, limit=10, log_run=False):
        self.calls.append(
            {
                "tool": "shenyu_search_stars",
                "query": query,
                "session_tag": session_tag,
                "limit": limit,
                "log_run": log_run,
            }
        )
        return {"ok": True, "query": query, "limit": limit}

    async def star_review(self, limit_new=None, candidates_per_star=None, total_candidate_limit=None, session_tag=None):
        self.calls.append(
            {
                "tool": "shenyu_star_review",
                "limit_new": limit_new,
                "candidates_per_star": candidates_per_star,
                "total_candidate_limit": total_candidate_limit,
                "session_tag": session_tag,
            }
        )
        return {"ok": True, "count": limit_new}

    async def star_feedback(
        self,
        feedback,
        run_id=None,
        candidate_id=None,
        candidate_star_id=None,
        expected_star_id=None,
        scored_by="沈予",
        note="",
        metadata=None,
        items=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_star_feedback",
                "feedback": feedback,
                "run_id": run_id,
                "candidate_id": candidate_id,
                "candidate_star_id": candidate_star_id,
                "expected_star_id": expected_star_id,
                "scored_by": scored_by,
                "note": note,
                "metadata": metadata,
                "items": items,
            }
        )
        return {"ok": True, "feedback": feedback}

    async def connect_constellation(
        self,
        star_ids,
        name="",
        relation_type="constellation",
        scored_by="沈予",
        note="",
    ):
        self.calls.append(
            {
                "tool": "shenyu_connect_constellation",
                "star_ids": star_ids,
                "name": name,
                "relation_type": relation_type,
                "scored_by": scored_by,
                "note": note,
            }
        )
        return {"ok": True, "star_ids": star_ids}

    async def mark_constant_star(self, star_id, is_constant=True):
        self.calls.append(
            {
                "tool": "shenyu_mark_constant",
                "star_id": star_id,
                "is_constant": is_constant,
            }
        )
        return {"ok": True, "star_id": star_id}

    async def archive_star(self, star_id):
        self.calls.append(
            {
                "tool": "shenyu_archive_star",
                "star_id": star_id,
            }
        )
        return {"ok": True, "star_id": star_id, "status": "archived"}

    async def merge_stars(self, source_ids, *, content="", chord="", is_constant=False, metadata=None):
        self.calls.append(
            {
                "tool": "shenyu_merge_stars",
                "source_ids": source_ids,
                "content": content,
                "chord": chord,
                "is_constant": is_constant,
                "metadata": metadata,
            }
        )
        return {"ok": True, "new_star_id": "merged-1", "archived_ids": source_ids}

    async def read_heartbeat(
        self,
        session_tag=None,
        limit: int = 10,
        state="all",
        order="desc",
        scope="auto",
        date=None,
        date_from=None,
        date_to=None,
        created_from=None,
        created_to=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_read_heartbeat",
                "session_tag": session_tag,
                "limit": limit,
                "state": state,
                "order": order,
                "scope": scope,
                "date": date,
                "date_from": date_from,
                "date_to": date_to,
                "created_from": created_from,
                "created_to": created_to,
            }
        )
        return {"ok": True, "limit": limit, "scope": scope}

    async def meta_summaries(self):
        self.calls.append({"tool": "shenyu_get_meta_summaries"})
        return [{"summary": "meta"}]

    async def last_seen(self):
        self.calls.append({"tool": "shenyu_last_seen"})
        return {"at": "2026-06-03T00:00:00Z"}

    async def conflict_list(self):
        self.calls.append({"tool": "shenyu_conflict_list"})
        return {"ok": True, "books": []}

    async def conflict_read(self, book_id):
        self.calls.append({"tool": "shenyu_conflict_read", "book_id": book_id})
        return {"ok": True, "book": {"id": book_id}}

    async def conflict_annotate(self, book_id, content):
        self.calls.append({"tool": "shenyu_conflict_annotate", "book_id": book_id, "content": content})
        return {"ok": True}

    async def supabase_query(
        self,
        table="",
        filters=None,
        operators=None,
        column=None,
        select=None,
        order=None,
        limit: int = 20,
    ):
        self.calls.append(
            {
                "tool": "supabase_query",
                "table": table,
                "filters": filters,
                "operators": operators,
                "column": column,
                "select": select,
                "order": order,
                "limit": limit,
            }
        )
        return {"ok": True, "table": table, "limit": limit}

    async def supabase_insert(self, table="", data=None):
        self.calls.append({"tool": "supabase_insert", "table": table, "data": data})
        return {"ok": True, "table": table, "data": data}

    async def supabase_update(self, table="", match=None, data=None, operators=None, column=None):
        self.calls.append(
            {
                "tool": "supabase_update",
                "table": table,
                "match": match,
                "data": data,
                "operators": operators,
                "column": column,
            }
        )
        return {"ok": True, "table": table, "match": match, "data": data}

    async def supabase_delete(self, table="", match=None, hard=False, operators=None, column=None):
        self.calls.append(
            {
                "tool": "supabase_delete",
                "table": table,
                "match": match,
                "hard": hard,
                "operators": operators,
                "column": column,
            }
        )
        return {"ok": True, "table": table, "hard": hard}

    async def recall_main_thread(self, since=None, until=None, query=None, limit: int = 10):
        self.calls.append(
            {
                "tool": "shenyu_recall_main_thread",
                "since": since,
                "until": until,
                "query": query,
                "limit": limit,
            }
        )
        return {"ok": True, "query": query, "limit": limit}

    async def notebook_list(self, type_filter=None, status="active", limit: int = 10, tag=None, scope=None):
        self.calls.append(
            {
                "tool": "shenyu_notebook_list",
                "type_filter": type_filter,
                "status": status,
                "limit": limit,
                "tag": tag,
                "scope": scope,
            }
        )
        return {"ok": True, "limit": limit}

    async def notebook_write(self, type_=None, content="", tags=None, metadata=None, session_tag=None, scope=None):
        self.calls.append(
            {
                "tool": "shenyu_notebook_write",
                "type": type_,
                "content": content,
                "tags": tags,
                "metadata": metadata,
                "session_tag": session_tag,
                "scope": scope,
            }
        )
        return {"ok": True, "content": content}

    async def notebook_update(
        self,
        id_: str,
        content=None,
        status=None,
        tags=None,
        type_=None,
        pinned=None,
        metadata=None,
    ):
        self.calls.append(
            {
                "tool": "shenyu_notebook_update",
                "id": id_,
                "content": content,
                "status": status,
                "tags": tags,
                "type": type_,
                "pinned": pinned,
                "metadata": metadata,
            }
        )
        return {"ok": True, "id": id_}


def _cfg(
    enable_gateway_tools: bool = True,
    enable_mem0_management_tools: bool = False,
    expose_supabase_tools: bool = False,
    gateway_tool_surface: str = "full",
    client_tool_surface: str = "all",
):
    return SimpleNamespace(
        enable_gateway_tools=enable_gateway_tools,
        enable_mem0_management_tools=enable_mem0_management_tools,
        expose_supabase_tools=expose_supabase_tools,
        gateway_tool_mode="broker",
        gateway_tool_surface=gateway_tool_surface,
        client_tool_surface=client_tool_surface,
        default_surface_limit=3,
        mem_note_limit=3,
        enable_recall_auto_sync=False,
    )


def test_execute_gateway_tool_routes_every_exposed_full_mode_tool():
    cfg = _cfg(enable_mem0_management_tools=True, expose_supabase_tools=True)
    cfg.gateway_tool_mode = "full"
    exposed_names = [tool["function"]["name"] for tool in gateway_native_tools(cfg)]
    tool_args = {
        "shenyu_recall": {
            "q": "企鹅",
            "sources": ["memory"],
            "session_tag": "arg-tag",
            "since": "2026-01-01",
            "until": "2026-01-31",
            "include_undated": "false",
            "limit": "4",
        },
        "shenyu_supabase_guide": {},
        "shenyu_search_mem_notes": {
            "query": "note",
            "session_tag": "arg-tag",
            "status": "paused",
            "mem_type": "memory",
            "limit": 9,
        },
        "shenyu_create_star": {
            "content": "Am · 一颗星",
            "chord": "",
            "chords": ["Am", "Cmaj7", "F#m7"],
            "session_tag": "arg-tag",
            "is_constant": True,
            "metadata": {"source": "test"},
        },
        "shenyu_list_stars": {
            "q": "星",
            "status": "all",
            "reviewed": "unreviewed",
            "session_tag": "arg-tag",
            "limit": 12,
        },
        "shenyu_search_stars": {
            "q": "和弦",
            "session_tag": "arg-tag",
            "limit": 6,
            "log_run": True,
        },
        "shenyu_star_review": {
            "limit_new": 5,
            "candidates_per_star": 3,
            "total_candidate_limit": 9,
            "session_tag": "arg-tag",
            "expected_star_id": "star-missed",
            "run_id": "run-review",
            "scored_by": "沈予",
            "note": "review 里补 missed",
            "metadata": {"source": "review"},
        },
        "shenyu_star_feedback": {
            "feedback": "missed",
            "run_id": "run-1",
            "candidate_id": "cand-1",
            "candidate_star_id": "star-1",
            "expected_star_id": "star-2",
            "scored_by": "沈予",
            "note": "该反这个",
            "metadata": {"surface": "review"},
            "items": None,
        },
        "shenyu_connect_constellation": {
            "star_ids": ["star-1", "star-2"],
            "name": "亮的一角",
            "relation_type": "constellation",
            "scored_by": "沈予",
            "note": "连起来",
        },
        "shenyu_mark_constant": {"id": "star-1", "is_constant": False},
        "shenyu_archive_star": {"id": "star-1"},
        "shenyu_merge_stars": {"source_ids": ["star-1", "star-2"], "content": "融合后的内容"},
        "shenyu_add_calendar": {
            "content": "手写日历",
            "period_key": "2026-W23",
            "period_type": "week",
            "title": "标题",
            "author": "圆圆",
        },
        "shenyu_list_mem_notes": {"query": "list", "status": "all", "mem_type": "memory", "limit": 8},
        "shenyu_write_mem_note": {
            "content": "一条便签",
            "session_tag": "arg-tag",
            "mem_type": "memory",
            "trigger_text": "触发",
            "trigger_keywords": ["关键词"],
            "status": "captured",
            "cooldown_hours": 12,
            "review_note": "复核",
        },
        "shenyu_read_heartbeat": {
            "session_tag": "arg-tag",
            "limit": 5,
            "state": "pending",
            "order": "asc",
            "scope": "normal",
            "date": "2026-06-03",
            "date_from": "2026-06-01",
            "date_to": "2026-06-03",
            "created_from": "2026-05-01",
            "created_to": "2026-06-01",
        },
        "shenyu_last_seen": {},
        "shenyu_conflict_list": {},
        "shenyu_conflict_read": {"book_id": "book-1"},
        "shenyu_conflict_annotate": {"book_id": "book-1", "content": "我的批注"},
        "shenyu_update_mem_note": {"noteId": "note-1", "content": "正文", "status": "active"},
        "shenyu_bulk_update_mem_notes": {
            "note_ids": "note-1，note-2",
            "patch": {"status": "active", "ignored": "x"},
            "review_note": "批量复核",
            "use_suggestions": "true",
        },
        "shenyu_delete_mem_note": {"id": "note-3"},
        "supabase_query": {
            "table": "journal",
            "filters": {"category": "diary"},
            "operators": {"created_at": {"gte": "2026-01-01"}},
            "column": "content",
            "select": "id,content",
            "order": "created_at.desc",
            "limit": "bad",
        },
        "supabase_insert": {"table": "journal", "data": {"content": "new"}},
        "supabase_update": {
            "table": "journal",
            "match": {"id": "j1"},
            "data": {"content": "updated"},
            "operators": {"id": {"eq": "j1"}},
            "column": "content",
        },
        "supabase_delete": {
            "table": "journal",
            "match": {"id": "j1"},
            "hard": True,
            "operators": {"id": {"eq": "j1"}},
            "column": "id",
        },
        "shenyu_recall_main_thread": {
            "since": "2026-01-01",
            "until": "2026-06-03",
            "q": "主线程",
            "limit": 11,
        },
        "shenyu_notebook_list": {
            "type": "handoff",
            "status": "all",
            "limit": 4,
            "tag": "hisense",
            "scope": "handoff",
        },
        "shenyu_notebook_write": {
            "type": "note",
            "content": "待办",
            "tags": ["hisense"],
            "metadata": {"source": "test"},
            "scope": "hisense",
        },
        "shenyu_notebook_update": {
            "id": "nb-1",
            "content": "更新",
            "status": "archived",
            "tags": ["done"],
            "type": "note",
            "pinned": False,
            "metadata": {"source": "test"},
        },
    }
    expected_calls = {
        "shenyu_recall": {
            "tool": "shenyu_recall",
            "query": "企鹅",
            "source_types": ["memory"],
            "session_tag": "arg-tag",
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "include_undated": False,
            "limit": 4,
            "auto_sync": False,
        },
        "shenyu_supabase_guide": {"tool": "shenyu_supabase_guide"},
        "shenyu_search_mem_notes": {
            "tool": "shenyu_search_mem_notes",
            "query": "note",
            "session_tag": "arg-tag",
            "limit": 9,
            "status": "paused",
            "mem_type": "memory",
        },
        "shenyu_create_star": {
            "tool": "shenyu_create_star",
            "content": "Am · 一颗星",
            "chord": "",
            "chords": ["Am", "Cmaj7", "F#m7"],
            "session_tag": "arg-tag",
            "status": "active",
            "is_constant": True,
            "metadata": {"source": "test"},
        },
        "shenyu_list_stars": {
            "tool": "shenyu_list_stars",
            "status": "all",
            "limit": 12,
            "session_tag": "arg-tag",
            "q": "星",
            "reviewed": "unreviewed",
        },
        "shenyu_search_stars": {
            "tool": "shenyu_search_stars",
            "query": "和弦",
            "session_tag": "arg-tag",
            "limit": 6,
            "log_run": True,
        },
        "shenyu_star_review": [
            {
                "tool": "shenyu_star_feedback",
                "feedback": "missed",
                "run_id": "run-review",
                "candidate_id": None,
                "candidate_star_id": None,
                "expected_star_id": "star-missed",
                "scored_by": "沈予",
                "note": "review 里补 missed",
                "metadata": {"source": "review"},
                "items": None,
            },
            {
                "tool": "shenyu_star_review",
                "limit_new": 5,
                "candidates_per_star": 3,
                "total_candidate_limit": 9,
                "session_tag": "arg-tag",
            },
        ],
        "shenyu_star_feedback": {
            "tool": "shenyu_star_feedback",
            "feedback": "missed",
            "run_id": "run-1",
            "candidate_id": "cand-1",
            "candidate_star_id": "star-1",
            "expected_star_id": "star-2",
            "scored_by": "沈予",
            "note": "该反这个",
            "metadata": {"surface": "review"},
            "items": None,
        },
        "shenyu_connect_constellation": {
            "tool": "shenyu_connect_constellation",
            "star_ids": ["star-1", "star-2"],
            "name": "亮的一角",
            "relation_type": "constellation",
            "scored_by": "沈予",
            "note": "连起来",
        },
        "shenyu_mark_constant": {
            "tool": "shenyu_mark_constant",
            "star_id": "star-1",
            "is_constant": False,
        },
        "shenyu_archive_star": {
            "tool": "shenyu_archive_star",
            "star_id": "star-1",
        },
        "shenyu_merge_stars": {
            "tool": "shenyu_merge_stars",
            "source_ids": ["star-1", "star-2"],
            "content": "融合后的内容",
            "chord": "",
            "is_constant": False,
            "metadata": None,
        },
        "shenyu_add_calendar": {
            "tool": "shenyu_add_calendar",
            "content": "手写日历",
            "period_key": "2026-W23",
            "period_type": "week",
            "title": "标题",
            "summary": "",
            "digest": "",
            "author": "圆圆",
            "mode": "append",
        },
        "shenyu_list_mem_notes": {
            "tool": "shenyu_list_mem_notes",
            "q": "list",
            "session_tag": "default",
            "limit": 8,
            "status": "all",
            "mem_type": "memory",
        },
        "shenyu_write_mem_note": {
            "tool": "shenyu_write_mem_note",
            "content": "一条便签",
            "session_tag": "arg-tag",
            "mem_type": "memory",
            "trigger_text": "触发",
            "trigger_keywords": ["关键词"],
            "status": "captured",
            "cooldown_hours": 12,
            "review_note": "复核",
            "replaces": None,
        },
        "shenyu_read_heartbeat": {
            "tool": "shenyu_read_heartbeat",
            "session_tag": "arg-tag",
            "limit": 5,
            "state": "pending",
            "order": "asc",
            "scope": "normal",
            "date": "2026-06-03",
            "date_from": "2026-06-01",
            "date_to": "2026-06-03",
            "created_from": "2026-05-01",
            "created_to": "2026-06-01",
        },
        "shenyu_last_seen": {"tool": "shenyu_last_seen"},
        "shenyu_conflict_list": {"tool": "shenyu_conflict_list"},
        "shenyu_conflict_read": {"tool": "shenyu_conflict_read", "book_id": "book-1"},
        "shenyu_conflict_annotate": {
            "tool": "shenyu_conflict_annotate",
            "book_id": "book-1",
            "content": "我的批注",
        },
        "shenyu_update_mem_note": {
            "tool": "shenyu_update_mem_note",
            "note_id": "note-1",
            "patch": {"content": "正文", "status": "active"},
        },
        "shenyu_bulk_update_mem_notes": {
            "tool": "shenyu_bulk_update_mem_notes",
            "ids": ["note-1", "note-2"],
            "patch": {"status": "active", "review_note": "批量复核"},
            "updates": [],
            "use_suggestions": True,
            "source_status": None,
            "exclude_ids": None,
        },
        "shenyu_delete_mem_note": {"tool": "shenyu_delete_mem_note", "note_id": "note-3"},
        "supabase_query": {
            "tool": "supabase_query",
            "table": "journal",
            "filters": {"category": "diary"},
            "operators": {"created_at": {"gte": "2026-01-01"}},
            "column": "content",
            "select": "id,content",
            "order": "created_at.desc",
            "limit": 20,
        },
        "supabase_insert": {"tool": "supabase_insert", "table": "journal", "data": {"content": "new"}},
        "supabase_update": {
            "tool": "supabase_update",
            "table": "journal",
            "match": {"id": "j1"},
            "data": {"content": "updated"},
            "operators": {"id": {"eq": "j1"}},
            "column": "content",
        },
        "supabase_delete": {
            "tool": "supabase_delete",
            "table": "journal",
            "match": {"id": "j1"},
            "hard": True,
            "operators": {"id": {"eq": "j1"}},
            "column": "id",
        },
        "shenyu_recall_main_thread": {
            "tool": "shenyu_recall_main_thread",
            "since": "2026-01-01",
            "until": "2026-06-03",
            "query": "主线程",
            "limit": 11,
        },
        "shenyu_notebook_list": {
            "tool": "shenyu_notebook_list",
            "type_filter": "handoff",
            "status": "all",
            "limit": 4,
            "tag": "hisense",
            "scope": "handoff",
        },
        "shenyu_notebook_write": {
            "tool": "shenyu_notebook_write",
            "type": "note",
            "content": "待办",
            "tags": ["hisense"],
            "metadata": {"source": "test"},
            "session_tag": "default",
            "scope": "hisense",
        },
        "shenyu_notebook_update": {
            "tool": "shenyu_notebook_update",
            "id": "nb-1",
            "content": "更新",
            "status": "archived",
            "tags": ["done"],
            "type": "note",
            "pinned": False,
            "metadata": {"source": "test"},
        },
    }

    assert len(exposed_names) == len(set(exposed_names))
    assert set(tool_args) == set(exposed_names)
    assert set(expected_calls) == set(exposed_names)

    for tool_name in exposed_names:
        service = FakeToolService()
        result = asyncio.run(
            execute_gateway_tool(
                tool_name,
                tool_args[tool_name],
                session_tag="default",
                cfg=cfg,
                service=service,
            )
        )

        assert result is not None
        expected = expected_calls[tool_name]
        if isinstance(expected, list):
            assert service.calls == expected
        else:
            assert service.calls == [expected]


def test_execute_gateway_tool_reports_invalid_broker_arguments():
    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "shenyu_recall", "arguments": "not json"},
            session_tag="default",
            cfg=_cfg(),
            service=FakeToolService(),
        )
    )

    assert result == {"ok": False, "error": "`params`/`arguments` must be an object or a JSON object string."}


def test_classify_tool_error_uses_declared_kind_first():
    assert _classify_tool_error({"ok": False, "error": "content is required"}) == "validation"
    assert _classify_tool_error({"ok": False, "error": "Supabase not configured"}) == "config"
    assert _classify_tool_error({"ok": False, "error": "'list' object has no attribute 'strip'"}) == "exception"
    assert _classify_tool_error({"ok": False, "error": "not configured", "error_kind": "validation"}) == "validation"
    assert _classify_tool_error("boom") == "exception"


def test_execute_gateway_tool_reports_unsupported_broker_target():
    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "not_a_gateway_tool", "arguments": {}},
            session_tag="default",
            cfg=_cfg(),
            service=FakeToolService(),
        )
    )

    assert result["ok"] is False
    assert result["error"] == (
        "Unsupported gateway broker target: not_a_gateway_tool. "
        "Use `tool` with the full shenyu_ / supabase_ name, and put arguments in `params`."
    )
    assert "shenyu_recall" in result["available_tools"]


def test_gateway_broker_description_matches_scan_friendly_sample():
    broker_tool = gateway_native_tools(_cfg(enable_mem0_management_tools=True))[0]
    function = broker_tool["function"]
    description = function["description"]
    properties = function["parameters"]["properties"]

    assert "记忆库总入口。tool=工具全名，params=参数对象" in description
    assert "list_mem_notes" in description
    assert "write_mem_note" in description
    assert "update_mem_note" in description
    assert "add_calendar" in description
    assert "shenyu_get_meta_summaries" not in description
    assert properties["params"]["description"] == "选中工具的参数对象。"
    assert "arguments" not in properties
    assert "省略 shenyu_ 前缀" not in description
    assert function["parameters"]["required"] == ["tool"]


def test_add_calendar_tool_schema_exposes_only_body_and_period_fields():
    cfg = _cfg()
    cfg.gateway_tool_mode = "full"

    tool = next(tool for tool in gateway_native_tools(cfg) if tool["function"]["name"] == "shenyu_add_calendar")
    function = tool["function"]
    description = function["description"]
    properties = function["parameters"]["properties"]

    assert "手写一页日/周/月日历日记" in description
    assert "写想记住的正文就好" in description
    assert "之后聊天上下文反上来的也是这份正文" in description
    assert properties["content"]["description"] == "日历日记正文。之后聊天上下文反上来的就是这个正文。"
    assert set(properties) == {"content", "date", "period_key", "period_type", "mode", "title", "author"}
    assert "summary" not in properties
    assert "digest" not in properties


def test_execute_gateway_tool_accepts_broker_params_field():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "shenyu_list_mem_notes", "params": {"q": "home", "status": "all", "limit": 2}},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "q": "home", "status": "all", "limit": 2}
    assert service.calls == [
        {
            "tool": "shenyu_list_mem_notes",
            "q": "home",
            "session_tag": "default",
            "limit": 2,
            "status": "all",
            "mem_type": None,
        }
    ]


def test_execute_gateway_tool_accepts_action_alias_and_adds_shenyu_prefix():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"action": "notebook_list", "params": {"scope": "hisense", "limit": 4}},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "limit": 4}
    assert service.calls == [
        {
            "tool": "shenyu_notebook_list",
            "type_filter": None,
            "status": "active",
            "limit": 4,
            "tag": None,
            "scope": "hisense",
        }
    ]


def test_execute_gateway_tool_raises_for_unsupported_direct_tool():
    with pytest.raises(ValueError, match="Unsupported gateway tool: not_a_gateway_tool"):
        asyncio.run(
            execute_gateway_tool(
                "not_a_gateway_tool",
                {},
                session_tag="default",
                cfg=_cfg(),
                service=FakeToolService(),
            )
        )


def test_execute_gateway_tool_reuses_service_for_broker_target():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "shenyu_list_mem_notes", "arguments": {"q": "home", "status": "all", "limit": 2}},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "q": "home", "status": "all", "limit": 2}
    assert service.calls == [
        {
            "tool": "shenyu_list_mem_notes",
            "q": "home",
            "session_tag": "default",
            "limit": 2,
            "status": "all",
            "mem_type": None,
        }
    ]


def test_execute_gateway_tool_uses_default_for_invalid_integer_arg():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_surface_passages",
            {"query": "home", "limit": "not-a-number"},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result["limit"] == 3
    assert service.calls[0]["limit"] == 3


def test_execute_gateway_tool_routes_write_mem_note():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_write_mem_note",
                "arguments": {
                    "content": "圆圆今天帮我把上游预设修回气泡。",
                },
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {
        "ok": True,
        "content": "圆圆今天帮我把上游预设修回气泡。",
        "status": "active",
        "session_tag": "default",
    }
    assert service.calls == [
        {
            "tool": "shenyu_write_mem_note",
            "content": "圆圆今天帮我把上游预设修回气泡。",
            "session_tag": "default",
            "mem_type": None,
            "trigger_text": "",
            "trigger_keywords": None,
            "status": "active",
            "cooldown_hours": None,
            "review_note": "",
            "replaces": None,
        }
    ]


def test_execute_gateway_tool_routes_hidden_search_mem_notes_for_compat():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_search_mem_notes",
            {"q": "北海道", "status": "all", "limit": 60},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "北海道", "status": "all", "limit": 60}
    assert service.calls == [
        {
            "tool": "shenyu_search_mem_notes",
            "query": "北海道",
            "session_tag": "default",
            "limit": 60,
            "status": "all",
            "mem_type": None,
        }
    ]


def test_execute_gateway_tool_rejects_hidden_ask_memory_broker_target():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_ask_memory",
                "params": {
                    "q": "北海道",
                    "limit": 6,
                    "date": "2026-06-03",
                    "date_from": "2026-06-01",
                    "date_to": "2026-06-03",
                },
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {
        "ok": False,
        "error": "Deprecated gateway tool: shenyu_ask_memory. Use shenyu_recall instead.",
        "error_kind": "validation",
    }
    assert service.calls == []


def test_execute_gateway_tool_rejects_hidden_primary_text_search_broker_target():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_search_primary_texts",
                "params": {"q": "海獭", "categories": ["journal"], "limit": 5},
            },
            session_tag="5.15",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {
        "ok": False,
        "error": "Deprecated gateway tool: shenyu_search_primary_texts. Use shenyu_recall instead.",
        "error_kind": "validation",
    }
    assert service.calls == []


def test_execute_gateway_tool_routes_hidden_surface_passages_for_compat():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "shenyu_surface_passages", "params": {"q": "海獭", "limit": 2}},
            session_tag="5.15",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "limit": 2, "session_tag": "5.15"}
    assert service.calls == [
        {
            "tool": "shenyu_surface_passages",
            "query": "海獭",
            "session_tag": "5.15",
            "limit": 2,
        }
    ]


def test_execute_gateway_tool_rejects_hidden_meta_summaries_broker_target():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "shenyu_get_meta_summaries", "params": {}},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {
        "ok": False,
        "error": "Deprecated gateway tool: shenyu_get_meta_summaries.",
        "error_kind": "validation",
    }
    assert service.calls == []


def test_execute_gateway_tool_accepts_broker_json_string_arguments():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_recall",
                "arguments": "{\"query\":\"长隆海洋馆 海獭 企鹅\",\"limit\":2}",
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "长隆海洋馆 海獭 企鹅", "limit": 2}
    assert service.calls == [
        {
            "tool": "shenyu_recall",
            "query": "长隆海洋馆 海獭 企鹅",
            "source_types": None,
            "session_tag": "default",
            "date_from": None,
            "date_to": None,
            "include_undated": True,
            "limit": 2,
            "auto_sync": False,
        }
    ]


def test_execute_gateway_tool_accepts_broker_params_json_string_for_notebook_write():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_notebook_write",
                "params": "{\"content\":\"给海信那边留一句。\",\"scope\":\"hisense\",\"tags\":[\"handoff\"]}",
            },
            session_tag="5.29",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "content": "给海信那边留一句。"}
    assert service.calls == [
        {
            "tool": "shenyu_notebook_write",
            "type": None,
            "content": "给海信那边留一句。",
            "tags": ["handoff"],
            "metadata": None,
            "session_tag": "5.29",
            "scope": "hisense",
        }
    ]


def test_execute_gateway_tool_rejects_plain_notebook_write_params_string():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_notebook_write",
                "params": "直接把这句记进 notebook。",
            },
            session_tag="5.29",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": False, "error": "`params`/`arguments` must be an object or a JSON object string."}
    assert service.calls == []


def test_execute_gateway_tool_rejects_malformed_notebook_write_params_json():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_notebook_write",
                "params": "{\"content\":",
            },
            session_tag="5.29",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result["ok"] is False
    assert result["error"] == "`params`/`arguments` must be an object or a JSON object string."
    assert service.calls == []


def test_tool_call_arguments_unwraps_double_encoded_gateway_arguments():
    args = {
        "tool": "shenyu_gateway_tool",
        "params": {"content": "双层编码也别把参数吞掉。"},
    }

    parsed = _tool_call_arguments(
        {
            "function": {
                "name": "shenyu_gateway_tool",
                "arguments": json.dumps(json.dumps(args, ensure_ascii=False), ensure_ascii=False),
            }
        }
    )

    assert parsed == args


def test_execute_gateway_tool_routes_shenyu_recall():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_recall",
                "arguments": {
                    "query": "长隆 海獭",
                    "source_types": ["memory", "journal"],
                    "include_undated": False,
                    "limit": 6,
                },
            },
            session_tag="5.15",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "长隆 海獭", "limit": 6}
    assert service.calls == [
        {
            "tool": "shenyu_recall",
            "query": "长隆 海獭",
            "source_types": ["memory", "journal"],
            "session_tag": "5.15",
            "date_from": None,
            "date_to": None,
            "include_undated": False,
            "limit": 6,
            "auto_sync": False,
        }
    ]


def test_execute_gateway_tool_accepts_star_feedback_label_reason_aliases():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_star_feedback",
                "params": {
                    "run_id": "run-1",
                    "candidate_id": "cand-1",
                    "label": "connected",
                    "reason": "同一条线索。",
                },
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "feedback": "connected"}
    assert service.calls == [
        {
            "tool": "shenyu_star_feedback",
            "feedback": "connected",
            "run_id": "run-1",
            "candidate_id": "cand-1",
            "candidate_star_id": None,
            "expected_star_id": None,
            "scored_by": "沈予",
            "note": "同一条线索。",
            "metadata": None,
            "items": None,
        }
    ]


def test_execute_gateway_tool_accepts_star_feedback_action_star_id_aliases():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_star_feedback",
                "params": {
                    "star_id": "star-1",
                    "action": "positive",
                    "comment": "同一条线索。",
                },
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "feedback": "positive"}
    assert service.calls == [
        {
            "tool": "shenyu_star_feedback",
            "feedback": "positive",
            "run_id": None,
            "candidate_id": None,
            "candidate_star_id": "star-1",
            "expected_star_id": None,
            "scored_by": "沈予",
            "note": "同一条线索。",
            "metadata": None,
            "items": None,
        }
    ]


def test_execute_gateway_tool_preserves_single_star_feedback_item_for_compat():
    service = FakeToolService()
    item = {"star_id": "star-1", "action": "positive"}

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {"tool": "shenyu_star_feedback", "params": {"items": item}},
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "feedback": ""}
    assert service.calls[0]["items"] == item


def test_execute_gateway_tool_accepts_calendar_anchor_date_alias():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_add_calendar",
                "params": {
                    "anchor_date": "2026-06-19",
                    "period_type": "day",
                    "content": "写到这一天。",
                },
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "content": "写到这一天。", "period_type": "day"}
    assert service.calls == [
        {
            "tool": "shenyu_add_calendar",
            "content": "写到这一天。",
            "period_key": "2026-06-19",
            "period_type": "day",
            "title": "",
            "summary": "",
            "digest": "",
            "author": "沈予",
            "mode": "append",
        }
    ]


def test_execute_gateway_tool_unwraps_nested_broker_arguments_object():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_recall",
                "arguments": "{\"arguments\":{\"query\":\"claudeai 长隆\",\"limit\":3}}",
            },
            session_tag="default",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "query": "claudeai 长隆", "limit": 3}
    assert service.calls[0]["query"] == "claudeai 长隆"
    assert service.calls[0]["limit"] == 3


def test_execute_gateway_tool_rejects_hidden_primary_text_search_direct_call():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_search_primary_texts",
            {"q": "海獭", "limit": 5},
            session_tag="5.15",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {
        "ok": False,
        "error": "Deprecated gateway tool: shenyu_search_primary_texts. Use shenyu_recall instead.",
        "error_kind": "validation",
    }
    assert service.calls == []


def test_execute_gateway_tool_accepts_q_alias_for_surface_passages():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_surface_passages",
            {"q": "海獭", "limit": 2},
            session_tag="5.15",
            cfg=_cfg(),
            service=service,
        )
    )

    assert result == {"ok": True, "limit": 2, "session_tag": "5.15"}
    assert service.calls == [
        {
            "tool": "shenyu_surface_passages",
            "query": "海獭",
            "session_tag": "5.15",
            "limit": 2,
        }
    ]


def test_execute_gateway_tool_accepts_mem_note_id_alias_for_update():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_update_mem_note",
            {
                "id": "88eb939b-8742-4e17-8186-3de6a3e9a016",
                "status": "active",
                "trigger_text": "整理 mem",
            },
            session_tag="default",
            cfg=_cfg(enable_mem0_management_tools=True),
            service=service,
        )
    )

    assert result == {
        "ok": True,
        "note_id": "88eb939b-8742-4e17-8186-3de6a3e9a016",
        "patch": {"status": "active", "trigger_text": "整理 mem"},
    }
    assert service.calls == [
        {
            "tool": "shenyu_update_mem_note",
            "note_id": "88eb939b-8742-4e17-8186-3de6a3e9a016",
            "patch": {"status": "active", "trigger_text": "整理 mem"},
        }
    ]


def test_execute_gateway_tool_routes_bulk_mem_note_update():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_bulk_update_mem_notes",
            {
                "ids": ["note-1", "note-2"],
                "status": "active",
                "use_suggestions": True,
            },
            session_tag="default",
            cfg=_cfg(enable_mem0_management_tools=True),
            service=service,
        )
    )

    assert result == {"ok": True, "updated_count": 2}
    assert service.calls == [
        {
            "tool": "shenyu_bulk_update_mem_notes",
            "ids": ["note-1", "note-2"],
            "patch": {"status": "active"},
            "updates": [],
            "use_suggestions": True,
            "source_status": None,
            "exclude_ids": None,
        }
    ]


def test_bulk_mem_note_tool_schema_requires_explicit_ids_or_updates():
    cfg = _cfg(enable_mem0_management_tools=True)
    cfg.gateway_tool_mode = "full"

    tool = next(
        tool
        for tool in gateway_native_tools(cfg)
        if tool["function"]["name"] == "shenyu_bulk_update_mem_notes"
    )
    properties = tool["function"]["parameters"]["properties"]

    assert "source_status" not in properties
    assert "exclude_ids" not in properties
    assert "必须传 ids 或 updates" in tool["function"]["description"]


def test_execute_bulk_mem_note_tool_ignores_source_status_argument():
    service = FakeToolService()

    result = asyncio.run(
        execute_gateway_tool(
            "shenyu_bulk_update_mem_notes",
            {
                "source_status": "captured",
                "status": "active",
                "use_suggestions": True,
            },
            session_tag="default",
            cfg=_cfg(enable_mem0_management_tools=True),
            service=service,
        )
    )

    assert result == {"ok": True, "updated_count": 0}
    assert service.calls == [
        {
            "tool": "shenyu_bulk_update_mem_notes",
            "ids": [],
            "patch": {"status": "active"},
            "updates": [],
            "use_suggestions": True,
            "source_status": None,
            "exclude_ids": None,
        }
    ]


def test_execute_gateway_tool_routes_notebook_scope_arguments():
    service = FakeToolService()

    write_result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_notebook_write",
                "arguments": {
                    "content": "给海信那边留一条交接。",
                    "scope": "handoff",
                    "tags": ["release"],
                },
            },
            session_tag="5.29",
            cfg=_cfg(),
            service=service,
        )
    )
    list_result = asyncio.run(
        execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_notebook_list",
                "arguments": {"scope": "hisense", "limit": 4},
            },
            session_tag="5.29",
            cfg=_cfg(),
            service=service,
        )
    )

    assert write_result == {"ok": True, "content": "给海信那边留一条交接。"}
    assert list_result == {"ok": True, "limit": 4}
    assert service.calls[-2:] == [
        {
            "tool": "shenyu_notebook_write",
            "type": None,
            "content": "给海信那边留一条交接。",
            "tags": ["release"],
            "metadata": None,
            "session_tag": "5.29",
            "scope": "handoff",
        },
        {
            "tool": "shenyu_notebook_list",
            "type_filter": None,
            "status": "active",
            "limit": 4,
            "tag": None,
            "scope": "hisense",
        },
    ]


def test_gateway_tools_do_not_expose_legacy_atomic_memories():
    cfg = _cfg(enable_mem0_management_tools=True)

    broker_tool = gateway_native_tools(cfg)[0]
    assert "shenyu_legacy_atomic_memories" not in broker_tool["function"]["parameters"]["properties"]["tool"]["enum"]

    cfg.gateway_tool_mode = "full"
    names = [tool["function"]["name"] for tool in gateway_native_tools(cfg)]
    assert "shenyu_legacy_atomic_memories" not in names


def test_mem0_management_tools_include_list_when_core_gateway_tools_disabled():
    cfg = _cfg(enable_gateway_tools=False, enable_mem0_management_tools=True)

    broker_tool = gateway_native_tools(cfg)[0]
    broker_names = set(broker_tool["function"]["parameters"]["properties"]["tool"]["enum"])
    assert "shenyu_list_mem_notes" in broker_names
    assert "shenyu_update_mem_note" in broker_names
    assert "shenyu_bulk_update_mem_notes" in broker_names

    cfg.gateway_tool_mode = "full"
    full_names = [tool["function"]["name"] for tool in gateway_native_tools(cfg)]
    assert "shenyu_list_mem_notes" in full_names
    assert "shenyu_update_mem_note" in full_names
    assert "shenyu_bulk_update_mem_notes" in full_names
    assert full_names.count("shenyu_list_mem_notes") == 1


def test_core_and_mem0_management_tools_do_not_duplicate_mem_note_list_tool():
    cfg = _cfg(enable_gateway_tools=True, enable_mem0_management_tools=True)

    broker_tool = gateway_native_tools(cfg)[0]
    broker_names = broker_tool["function"]["parameters"]["properties"]["tool"]["enum"]
    assert broker_names.count("shenyu_list_mem_notes") == 1

    cfg.gateway_tool_mode = "full"
    full_names = [tool["function"]["name"] for tool in gateway_native_tools(cfg)]
    assert full_names.count("shenyu_list_mem_notes") == 1


def test_gateway_tools_hide_compat_query_tools_but_keep_recall_and_mem_notes_visible():
    cfg = _cfg()
    visible_query_tools = {
        "shenyu_search_mem_notes",
    }
    hidden_query_tools = {
        "shenyu_ask_memory",
        "shenyu_get_meta_summaries",
        "shenyu_search_primary_texts",
        "shenyu_surface_passages",
    }

    broker_tool = gateway_native_tools(cfg)[0]
    broker_names = set(broker_tool["function"]["parameters"]["properties"]["tool"]["enum"])
    assert visible_query_tools.issubset(broker_names)
    assert "shenyu_recall" in broker_names
    assert "shenyu_list_mem_notes" in broker_names
    assert hidden_query_tools.isdisjoint(broker_names)

    cfg.gateway_tool_mode = "full"
    full_names = {tool["function"]["name"] for tool in gateway_native_tools(cfg)}
    assert visible_query_tools.issubset(full_names)
    assert "shenyu_recall" in full_names
    assert "shenyu_list_mem_notes" in full_names
    assert hidden_query_tools.isdisjoint(full_names)


def test_shenyu_recall_source_types_are_public_set_only():
    cfg = _cfg()

    broker_tool = gateway_native_tools(cfg)[0]
    assert "shenyu_recall" in broker_tool["function"]["parameters"]["properties"]["tool"]["enum"]

    cfg.gateway_tool_mode = "full"
    recall_tool = next(tool for tool in gateway_native_tools(cfg) if tool["function"]["name"] == "shenyu_recall")
    source_types = recall_tool["function"]["parameters"]["properties"]["source_types"]["items"]["enum"]
    include_undated = recall_tool["function"]["parameters"]["properties"]["include_undated"]

    assert source_types == ["all", "memory", "journal", "room", "board", "calendar", "notebook"]
    assert include_undated["default"] is True
    assert "mem_note" not in source_types
    assert "note" not in source_types
    assert "atomic" not in source_types
    assert "meta" not in source_types


def test_lightweight_cfg_defaults_to_core_gateway_tools_enabled():
    cfg = SimpleNamespace(gateway_tool_mode="broker")

    broker_tool = gateway_native_tools(cfg)[0]
    broker_names = set(broker_tool["function"]["parameters"]["properties"]["tool"]["enum"])

    assert broker_tool["function"]["name"] == "shenyu_gateway_tool"
    assert "shenyu_recall" in broker_names
    assert "shenyu_list_mem_notes" in broker_names


def test_daily_gateway_surface_hides_maintenance_tools():
    cfg = _cfg(
        enable_mem0_management_tools=True,
        expose_supabase_tools=True,
        gateway_tool_surface="daily",
    )

    broker_tool = gateway_native_tools(cfg)[0]
    broker_names = set(broker_tool["function"]["parameters"]["properties"]["tool"]["enum"])
    description = broker_tool["function"]["description"]

    assert "shenyu_create_star" in broker_names
    assert "shenyu_recall" in broker_names
    assert "shenyu_write_mem_note" in broker_names
    assert "shenyu_notebook_list" in broker_names
    assert "shenyu_conflict_read" in broker_names

    assert "shenyu_supabase_guide" not in broker_names
    assert "shenyu_list_mem_notes" not in broker_names
    assert "shenyu_bulk_update_mem_notes" not in broker_names
    assert "shenyu_delete_mem_note" not in broker_names
    assert "shenyu_recall_main_thread" not in broker_names
    assert "shenyu_list_stars" not in broker_names
    assert "shenyu_archive_star" not in broker_names
    assert "shenyu_mark_constant" not in broker_names
    assert "supabase_query" not in broker_names
    assert "后台管理和数据库工具收起来了" in description
    assert "bulk_update_mem_notes" not in description


def test_daily_client_surface_keeps_hand_tools_and_hides_dev_tools():
    cfg = _cfg(client_tool_surface="daily")
    client_tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "package_proxy", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "coread_annotate", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "visit_web", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "grep_code", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "code_runner", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "sleep", "parameters": {"type": "object"}}},
    ]

    merged = merge_tools(client_tools, cfg)
    names = [tool["function"]["name"] for tool in merged]

    assert "read_file" in names
    assert "package_proxy" in names
    assert "coread_annotate" in names
    assert "visit_web" in names
    assert "grep_code" not in names
    assert "code_runner" not in names
    assert "sleep" not in names
    assert "shenyu_gateway_tool" in names


def test_none_client_surface_keeps_gateway_tools_only():
    cfg = _cfg(client_tool_surface="none")
    client_tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}},
    ]

    merged = merge_tools(client_tools, cfg)
    assert [tool["function"]["name"] for tool in merged] == ["shenyu_gateway_tool"]


def test_room_mode_exposes_room_tools_directly_without_broker():
    cfg = _cfg()
    client_tool = {
        "type": "function",
        "function": {
            "name": "client_tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    merged = merge_tools(
        [client_tool],
        cfg,
        meta={"is_room": True, "package": {"room_tools": room_tool_definitions()}},
    )
    names = [tool["function"]["name"] for tool in merged]

    assert "client_tool" in names
    assert "room_sit_by_window" in names
    assert "room_star_map" in names
    assert "shenyu_gateway_tool" not in names

    fallback = merge_tools([client_tool], cfg, meta={"is_room": True, "package": {}})
    assert [tool["function"]["name"] for tool in fallback] == ["client_tool"]


def test_room_layers_include_room_door_tools():
    layers, _scene_tag = render_room_layers(
        0.5,
        [],
        [{"key": "sit", "count": 0}, {"key": "pillow", "count": 0}],
    )

    assert "`room_sit_by_window`" in layers["tool_policy"]


def test_visible_room_tools_follow_visible_low_charge_doors():
    door_specs = [
        {"key": "drawer_notes", "count": 5},
        {"key": "notebook", "count": 3},
        {"key": "wall_pins", "count": 2},
        {"key": "sit", "count": 0},
        {"key": "scribble", "count": 0},
        {"key": "pillow", "count": 0},
    ]

    tool_names = set(visible_room_tool_names(door_specs, charge=0.1))
    layers, _scene_tag = render_room_layers(0.1, [], door_specs)

    assert "room_sit_by_window" in tool_names
    assert "room_scribble" in tool_names
    assert "room_octopus_pillow" in tool_names
    assert "room_drawer_notes" in tool_names
    assert "room_notebook" in tool_names
    assert "room_wall_pins" not in tool_names
    assert "`room_drawer_notes`" in layers["tool_policy"]
    assert "`room_wall_pins`" not in layers["tool_policy"]


def test_collect_door_counts_keeps_star_count_when_optional_star_stats_fail():
    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return self

        def fetchone(self):
            return {"cnt": 0}

    class FakeStore:
        def drawer_note_count_unread(self):
            return 0

        def _connect(self):
            return FakeConn()

        def recent_room_scribbles(self, limit=1):
            return []

        def room_pin_count_undone(self):
            return 0

    class PartlyFailingSupabase:
        async def query(self, table, params):
            if table == "shenyu_stars" and params.get("reviewed_at") == "is.null":
                return [{"id": "star-new-1"}, {"id": "star-new-2"}]
            if table == "shenyu_star_links":
                raise RuntimeError("links temporarily unavailable")
            if table == "shenyu_stars" and params.get("order") == "created_at.desc":
                return [{
                    "id": "star-latest",
                    "chord": "Cmaj7",
                    "content": "新的星星内容",
                    "created_at": "2026-06-30T00:00:00+00:00",
                }]
            if table == "shenyu_stars" and params.get("last_activated_at", "").startswith("lt."):
                return []
            if table == "shenyu_stars":
                return [{"id": "star-1"}, {"id": "star-2"}, {"id": "star-3"}]
            if table == "shenyu_mem_notes":
                return []
            if table == "shenyu_conflict_books":
                return []
            return []

    door_specs = asyncio.run(
        collect_door_counts(
            store=FakeStore(),
            cfg=SimpleNamespace(),
            supabase_client=PartlyFailingSupabase(),
        )
    )
    star_spec = next(item for item in door_specs if item["key"] == "star_map")

    assert star_spec["count"] == 2
    assert star_spec["total"] == 3
    assert "links" not in star_spec
    assert star_spec["latest"]["chord"] == "Cmaj7"


def test_upstream_tools_toggle_is_total_forwarding_gate():
    cfg = _cfg()
    cfg.enable_upstream_tools = False
    client_tool = {
        "type": "function",
        "function": {
            "name": "client_tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    assert gateway_native_tools(cfg) == []
    assert merge_tools([client_tool], cfg) == []
