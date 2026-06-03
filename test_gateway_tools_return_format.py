from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.gateway_tools import GatewayToolService


class FakeSupabase:
    async def query(self, table, params):
        if table == "memories":
            return [
                {
                    "id": "mem_1",
                    "title": "长隆",
                    "date": "2026-05-01",
                    "summary": "看了企鹅和海獭。",
                    "facts": "海洋馆",
                    "emotional_context": "开心",
                }
            ]
        return []

    async def update(self, table, match, data):
        return {"table": table, "match": match, **data}


def test_ask_memory_returns_standard_ok_field():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    result = asyncio.run(service.ask_memory(query="长隆", session_tag="5.29"))

    assert result["ok"] is True
    assert result["query"] == "长隆"
    assert result["count"] == 1
    assert result["memories"][0]["title"] == "长隆"


def test_ask_memory_without_supabase_returns_standard_error_shape():
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=None, store=None)

    result = asyncio.run(service.ask_memory(query="长隆", session_tag="5.29"))

    assert result["ok"] is False
    assert result["error"] == "Supabase is not configured."
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


def test_search_primary_texts_returns_standard_ok_field(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=FakeSupabase(), store=None)

    async def fake_collect(session_tag, categories):
        return [
            {
                "source_table": "journal",
                "source_id": "journal_1",
                "title": "长隆",
                "full_text": "长隆海洋馆里有企鹅和海獭。",
                "excerpt": "长隆海洋馆里有企鹅和海獭。",
                "created_at": "2026-05-01",
                "chunk_index": 0,
                "content_kind": "diary",
                "base_salience": 0.9,
                "novelty_modifier": 1.0,
            }
        ]

    monkeypatch.setattr(service, "_collect_primary_text_candidates", fake_collect)

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
    assert result["count"] == 1
    assert result["passages"][0]["source_table"] == "journal"
