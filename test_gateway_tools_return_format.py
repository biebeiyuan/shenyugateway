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


def test_ask_memory_returns_standard_ok_field():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    result = asyncio.run(service.ask_memory(query="长隆", session_tag="5.29"))

    assert result["ok"] is True
    assert result["query"] == "长隆"
    assert result["count"] == 1
    assert result["memories"][0]["title"] == "长隆"
    assert result["memories"][0]["source_type"] == "memory"
    assert result["memories"][0]["source_table"] == "memories"
    assert "source_id" not in result["memories"][0]
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
