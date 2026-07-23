from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.gateway_tools import GatewayToolService


class FakeSupabase:
    def __init__(self):
        self.rows = [
            {
                "source_table": "memories",
                "source_id": "mem_1",
                "source_type": "memory",
                "chunk_index": 0,
                "session_tag": "5.29",
                "title": "长隆",
                "body": "看了企鹅和海獭。\n\n海洋馆\n\n开心",
                "excerpt": "看了企鹅和海獭。",
                "search_text": "长隆 看了企鹅和海獭 海洋馆 开心",
                "search_tokens": ["长隆", "企鹅", "海獭", "海洋馆", "开心"],
                "tags_json": [],
                "entities_json": [],
                "event_date": "2026-05-01",
                "importance": 0.8,
                "status": "active",
                "visibility": None,
            },
            {
                "source_table": "journal",
                "source_id": "journal_1",
                "source_type": "journal",
                "chunk_index": 0,
                "session_tag": "5.29",
                "title": "长隆",
                "body": "长隆海洋馆里有企鹅和海獭。",
                "excerpt": "长隆海洋馆里有企鹅和海獭。",
                "search_text": "长隆 长隆海洋馆里有企鹅和海獭",
                "search_tokens": ["长隆", "海洋馆", "企鹅", "海獭"],
                "tags_json": [],
                "entities_json": [],
                "metadata_json": {"category": "diary"},
                "event_date": "2026-05-01",
                "importance": 0.8,
                "status": "active",
                "visibility": None,
            },
            {
                "source_table": "journal",
                "source_id": "journal_2",
                "source_type": "journal",
                "chunk_index": 0,
                "session_tag": "5.29",
                "title": "信件",
                "body": "信件关键词，只应该在 letter 分类里出现。",
                "excerpt": "信件关键词，只应该在 letter 分类里出现。",
                "search_text": "信件 信件关键词 letter",
                "search_tokens": ["信件", "关键词", "letter"],
                "tags_json": ["letter"],
                "entities_json": [],
                "metadata_json": {"category": "letter"},
                "event_date": "2026-05-02",
                "importance": 0.8,
                "status": "active",
                "visibility": None,
            },
        ]

    async def rpc(self, fn, params=None):
        if fn == "search_shenyu_recall_index":
            return self.rows
        return []

    async def query(self, table, params):
        if table == "shenyu_recall_index":
            return self.rows
        return []

    async def update(self, table, match, data):
        return {"table": table, "match": match, **data}


class FailingSupabase:
    async def query(self, table, params):
        raise RuntimeError("query failed")


class ChatSupabase:
    def __init__(self, content):
        self.content = content

    async def query(self, table, params):
        if table == "shenyu_chat_archive":
            return [{
                "id": "chat-1",
                "session_tag": "old",
                "thread": "old",
                "role": "assistant",
                "content": self.content,
                "event_at": "2026-05-01T00:00:00+00:00",
                "archived_at": "2026-05-01T00:00:00+00:00",
            }]
        return []


class HeartbeatStore:
    def __init__(self, content):
        self.content = content

    def read_heartbeats(self, *args, **kwargs):
        return [{"id": "heartbeat-1", "content": self.content, "created_at": "2026-05-01T00:00:00+00:00"}]


def test_verbatim_recall_returns_the_full_archived_message():
    content = "原话。" * 300
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=ChatSupabase(content), store=None)

    result = asyncio.run(service.recall("原话", mode="verbatim"))

    assert result["items"][0]["content"] == content
    assert result["items"][0]["has_more"] is False


def test_live_heartbeat_recall_returns_full_content():
    content = "心跳。" * 300
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=None, store=HeartbeatStore(content))

    result = asyncio.run(service._recall_live_heartbeats("心跳", limit=1))

    assert result["items"][0]["content"] == content
    assert result["items"][0]["has_more"] is False


def test_ask_memory_returns_standard_ok_field():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    result = asyncio.run(service.ask_memory(query="长隆", session_tag="5.29"))

    assert result["ok"] is True
    assert result["query"] == "长隆"
    assert result["count"] == 1
    assert result["memories"][0]["title"] == "长隆"
    assert result["memories"][0]["source_type"] == "memory"
    assert result["memories"][0]["source_table"] == "memories"
    assert result["memories"][0]["source_id"] == "mem_1"
    assert result["source"] == "shenyu_recall"


def test_ask_memory_without_supabase_returns_standard_error_shape():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=None, store=None)

    result = asyncio.run(service.ask_memory(query="长隆", session_tag="5.29"))

    assert result["ok"] is False
    assert result["error"] == "Supabase is not configured."
    assert result["query"] == "长隆"
    assert result["count"] == 0
    assert result["memories"] == []


def test_ask_memory_query_error_returns_standard_error_shape():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FailingSupabase(), store=None)

    result = asyncio.run(service.ask_memory(query="长隆", session_tag="5.29"))

    assert result["ok"] is False
    assert "query failed" in result["error"]
    assert result["query"] == "长隆"
    assert result["count"] == 0
    assert result["memories"] == []


def test_surface_passages_returns_standard_ok_field(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    async def fake_collect(session_tag, categories):
        return [
            {
                "source_table": "room",
                "source_id": "room_1",
                "title": "海洋馆",
                "full_text": "长隆海洋馆里有企鹅和海獭。",
                "excerpt": "长隆海洋馆里有企鹅和海獭。",
                "created_at": "2026-05-01",
                "chunk_index": 0,
                "content_kind": "room",
                "base_salience": 0.9,
                "novelty_modifier": 1.0,
            }
        ]

    monkeypatch.setattr(service, "_collect_primary_text_candidates", fake_collect)
    monkeypatch.setattr("shenyu_gateway.gateway_tools.random.random", lambda: 0.0)

    result = asyncio.run(service.surface_passages(query="长隆 海獭", session_tag="5.29", limit=3))

    assert result["ok"] is True
    assert result["query"] == "长隆 海獭"
    assert result["count"] == 1
    assert result["passages"][0]["source_table"] == "room"


def test_search_primary_texts_returns_standard_ok_field():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    result = asyncio.run(
        service.search_primary_texts(
            query="长隆 海獭",
            categories=["journal"],
            session_tag="5.29",
            limit=5,
        )
    )

    assert result["ok"] is True
    assert result["query"] == "长隆 海獭"
    assert result["categories"] == ["annotation", "diary", "letter", "life_tick", "lock", "paper"]
    assert result["source"] == "shenyu_recall"
    assert result["source_types"] == ["journal"]
    assert result["count"] == 1
    assert result["passages"][0]["source_table"] == "journal"
    assert result["passages"][0]["full_text"] == "长隆海洋馆里有企鹅和海獭。"
    assert result["passages"][0]["content_kind"] == "diary"


def test_recall_federation_keeps_internal_scores_out_of_tool_output(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)
    recall_kwargs = {}

    class FakeRecallIndex:
        async def recall(self, **kwargs):
            recall_kwargs.update(kwargs)
            return {
                "ok": True,
                "count": 3,
                "items": [
                    {
                        "content": f"片段 {index}",
                        "source_id": f"journal-{index}",
                        "source_type": "journal",
                        "source_table": "journal",
                        "content_kind": "diary",
                        "event_date": "2026-07-10",
                        "has_more": True,
                    }
                    for index in range(3)
                ],
            }

    class FakeStars:
        async def search_recall(self, *args, **kwargs):
            return {"ok": True, "items": [{"id": "star-1", "content": "一颗相关的星", "score": 0.7}]}

    class FakeMemNotes:
        async def search_notes_contextual(self, *args, **kwargs):
            return {"ok": True, "items": []}

    async def fake_heartbeats(*args, **kwargs):
        return {
            "ok": True,
            "items": [
                {
                    "content": "一条更相关的心跳",
                    "source_id": "hb-1",
                    "source_type": "heartbeat",
                    "source_table": "heartbeat_entries",
                    "content_kind": "heartbeat",
                    "event_date": "2026-07-10",
                    "has_more": False,
                    "_recall_score": 0.9,
                }
            ],
        }

    monkeypatch.setattr(service, "_recall_index", lambda: FakeRecallIndex())
    monkeypatch.setattr(service, "_stars", lambda: FakeStars())
    monkeypatch.setattr(service, "_mem_notes", lambda: FakeMemNotes())
    monkeypatch.setattr(service, "_recall_live_heartbeats", fake_heartbeats)

    result = asyncio.run(service.recall("那次害怕打开自己", limit=4))

    assert result["count"] == 4
    assert [item["source_type"] for item in result["items"]] == ["journal", "journal", "journal", "heartbeat"]
    assert all("score" not in item and "matched_by" not in item for item in result["items"])
    assert recall_kwargs["include_trace"] is True


def test_exact_recall_does_not_add_a_weak_companion(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    class FakeRecallIndex:
        async def recall(self, **kwargs):
            return {
                "ok": True,
                "items": [
                    {
                        "content": "原件片段",
                        "source_id": "journal-original",
                        "source_type": "journal",
                        "source_table": "journal",
                    }
                ],
            }

    class EmptyLane:
        async def search_recall(self, *args, **kwargs):
            return {"ok": True, "items": []}

        async def search_notes_contextual(self, *args, **kwargs):
            return {"ok": True, "items": []}

    async def weak_heartbeat(*args, **kwargs):
        return {
            "ok": True,
            "items": [
                {
                    "content": "只有一点点相关",
                    "source_id": "hb-weak",
                    "source_type": "heartbeat",
                    "source_table": "heartbeat_entries",
                    "_recall_score": 0.5,
                }
            ],
        }

    monkeypatch.setattr(service, "_recall_index", lambda: FakeRecallIndex())
    monkeypatch.setattr(service, "_stars", lambda: EmptyLane())
    monkeypatch.setattr(service, "_mem_notes", lambda: EmptyLane())
    monkeypatch.setattr(service, "_recall_live_heartbeats", weak_heartbeat)

    result = asyncio.run(service.recall("《玻璃瓶》", mode="exact", limit=4))

    assert result["count"] == 1
    assert result["items"][0]["source_id"] == "journal-original"


def test_recall_deduplicates_live_and_archived_heartbeat_by_original_id(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    class FakeRecallIndex:
        async def recall(self, **kwargs):
            return {
                "ok": True,
                "items": [
                    {
                        "content": "已经归档的心跳",
                        "source_id": "hb-same",
                        "source_type": "heartbeat",
                        "source_table": "shenyu_heartbeat_archive",
                    }
                ],
            }

    class EmptyLane:
        async def search_recall(self, *args, **kwargs):
            return {"ok": True, "items": []}

        async def search_notes_contextual(self, *args, **kwargs):
            return {"ok": True, "items": []}

    async def same_live_heartbeat(*args, **kwargs):
        return {
            "ok": True,
            "items": [
                {
                    "content": "仍在 live 池的同一条心跳",
                    "source_id": "hb-same",
                    "source_type": "heartbeat",
                    "source_table": "heartbeat_entries",
                    "_recall_score": 0.9,
                }
            ],
        }

    monkeypatch.setattr(service, "_recall_index", lambda: FakeRecallIndex())
    monkeypatch.setattr(service, "_stars", lambda: EmptyLane())
    monkeypatch.setattr(service, "_mem_notes", lambda: EmptyLane())
    monkeypatch.setattr(service, "_recall_live_heartbeats", same_live_heartbeat)

    result = asyncio.run(service.recall("以前写过的心跳", limit=4))

    assert result["count"] == 1
    assert result["items"][0]["source_id"] == "hb-same"


def test_mem_note_write_indexes_new_active_row_immediately(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)
    indexed = []

    class FakeMemNotes:
        async def create_note(self, **kwargs):
            return {
                "ok": True,
                "note": {
                    "id": "note-new",
                    "content": kwargs["content"],
                    "status": "active",
                    "created_at": "2026-07-10",
                    "updated_at": "2026-07-10",
                },
            }

    class FakeRecallIndex:
        async def index_mem_note_row(self, row):
            indexed.append(row)
            return {"ok": True, "indexed": 1}

        async def mark_source_row_deleted(self, source_table, source_id):
            return None

    monkeypatch.setattr(service, "_mem_notes", lambda: FakeMemNotes())
    monkeypatch.setattr(service, "_recall_index", lambda: FakeRecallIndex())

    result = asyncio.run(service.write_mem_note("刚写下的一条便签"))

    assert result["ok"] is True
    assert [row["id"] for row in indexed] == ["note-new"]


def test_bulk_mem_note_update_reindexes_updated_rows_immediately(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)
    indexed = []

    class FakeMemNotes:
        async def bulk_update_notes(self, **kwargs):
            return {
                "ok": True,
                "updated_count": 2,
                "updated_ids": ["note-a", "note-b"],
                "failures": [],
            }

        async def get_notes_by_ids(self, note_ids):
            assert note_ids == ["note-a", "note-b"]
            return {
                note_id: {"id": note_id, "content": f"updated {note_id}", "status": "active"}
                for note_id in note_ids
            }

    class FakeRecallIndex:
        async def index_mem_note_row(self, row):
            indexed.append(row)
            return {"ok": True, "indexed": 1}

    monkeypatch.setattr(service, "_mem_notes", lambda: FakeMemNotes())
    monkeypatch.setattr(service, "_recall_index", lambda: FakeRecallIndex())

    result = asyncio.run(
        service.bulk_update_mem_notes(ids=["note-a", "note-b"], patch={"status": "active"})
    )

    assert result["ok"] is True
    assert [row["id"] for row in indexed] == ["note-a", "note-b"]


def test_bulk_mem_note_reindex_failure_does_not_block_other_updates(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)
    indexed = []

    class FakeMemNotes:
        async def bulk_update_notes(self, **kwargs):
            return {"ok": True, "updated_ids": ["note-a", "note-b"]}

        async def get_notes_by_ids(self, note_ids):
            return {
                note_id: {"id": note_id, "content": note_id, "status": "active"}
                for note_id in note_ids
            }

    class PartlyFailingRecallIndex:
        async def index_mem_note_row(self, row):
            if row["id"] == "note-a":
                raise RuntimeError("temporary index failure")
            indexed.append(row["id"])

    monkeypatch.setattr(service, "_mem_notes", lambda: FakeMemNotes())
    monkeypatch.setattr(service, "_recall_index", lambda: PartlyFailingRecallIndex())

    result = asyncio.run(service.bulk_update_mem_notes(ids=["note-a", "note-b"], patch={}))

    assert result["ok"] is True
    assert indexed == ["note-b"]


def test_search_primary_texts_keeps_journal_category_filter_after_recall_delegate():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    result = asyncio.run(
        service.search_primary_texts(
            query="信件关键词",
            categories=["letter"],
            session_tag="5.29",
            limit=5,
        )
    )

    assert result["ok"] is True
    assert result["categories"] == ["letter"]
    assert result["source_types"] == ["journal"]
    assert result["count"] == 1
    assert result["passages"][0]["title"] == "信件"
    assert result["passages"][0]["content_kind"] == "letter"
