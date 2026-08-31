from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from shenyu_gateway.gateway_tools import GatewayToolService

from .fake_postgrest import project_select


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
            return project_select(self.rows, params)
        return []

    async def update(self, table, match, data):
        return {"table": table, "match": match, **data}


class ChatSupabase:
    def __init__(self, content):
        self.content = content

    async def query(self, table, params):
        if table == "shenyu_chat_archive":
            return project_select([{
                "id": "chat-1",
                "session_tag": "old",
                "thread": "old",
                "role": "assistant",
                "content": self.content,
                "event_at": "2026-05-01T00:00:00+00:00",
                "archived_at": "2026-05-01T00:00:00+00:00",
            }], params)
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
    assert all(
        "score" not in item and "matched_by" not in item and "recall_match" not in item
        for item in result["items"]
    )
    # Admin preview keeps include_trace; the resident-facing tool path must not
    # request it, so recall_match never reaches the model.
    assert recall_kwargs.get("include_trace", False) is False


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


def test_star_tool_results_stay_clean(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=None, store=None)

    class FakeStars:
        async def list_stars(self, **kwargs):
            return {
                "ok": True,
                "count": 1,
                "items": [
                    {
                        "id": "star-1",
                        "content": "原文",
                        "chord": "Am",
                        "chord_sequence": ["Am"],
                        "status": "active",
                        "is_constant": False,
                        "created_at": "2026-07-01T00:00:00+00:00",
                        "updated_at": "2026-07-02T00:00:00+00:00",
                        "session_tag": "7.1",
                        "scenes": ["daily"],
                        "activation_count": 3,
                        "last_activated_at": "2026-07-03",
                        "source_model": "m",
                        "source_session_id": "s",
                        "source_excerpt": "e",
                        "chord_root": "A",
                        "chord_quality": "m",
                    }
                ],
            }

        async def search_stars(self, **kwargs):
            return {
                "ok": True,
                "count": 1,
                "run_id": "run-1",
                "items": [
                    {
                        "id": "star-1",
                        "content": "原文",
                        "chord": "Am",
                        "created_at": "2026-07-01T00:00:00+00:00",
                        "candidate_id": "cand-1",
                        "score": 0.83,
                        "scores": {"rrf_score": 0.5},
                        "keyword_hits": ["原文"],
                        "direct_reference_kind": "none",
                    }
                ],
            }

    monkeypatch.setattr(service, "_stars", lambda: FakeStars())

    listing = asyncio.run(service.list_stars())
    assert listing["items"][0] == {
        "id": "star-1",
        "content": "原文",
        "chord": "Am",
        "created_at": "2026-07-01T00:00:00+00:00",
        # status="active" 是他刚才自己筛的值，chord_sequence 只有一个和弦时就是
        # chord 本身——两个都是把他已经知道的事说回给他。updated_at 只在真的
        # 改过（不同一天）时才带，而这颗改过，所以留下了。
        "updated_at": "2026-07-02T00:00:00+00:00",
    }

    search = asyncio.run(service.search_stars(query="原文"))
    assert search["run_id"] == "run-1"
    item = search["items"][0]
    assert item["candidate_id"] == "cand-1"
    assert "score" not in item and "scores" not in item
    assert "keyword_hits" not in item and "direct_reference_kind" not in item


def test_review_gives_him_numbers_not_internal_ids():
    """他手上该有的是「1.2」，不是 run_id。

    run_id 是"第几次召回"的内部账本，他不会想引用它，而以前 star_feedback 要
    他从 review 返回里拎出这个字符串再填回去——那是让他替系统记账。
    """
    from shenyu_gateway.gateway_tools import GatewayToolService

    class FakeStars:
        async def review(self, **kwargs):
            def star(sid, content, created):
                return {
                    "id": sid,
                    "content": content,
                    "chord": "Am",
                    "chord_sequence": ["Am"],
                    "status": "active",
                    "is_constant": False,
                    "created_at": created,
                    "updated_at": created,
                    "score": 0.83,
                    "scores": {"content": 0.7},
                    "activation_count": 4,
                }

            return {
                "ok": True,
                "count": 1,
                "remaining_unreviewed": 7,
                "items": [
                    {
                        "star": star("star-1", "她把伞递过来的时候手是湿的", "2026-08-25T02:00:00+00:00"),
                        "run_id": "run-abc",
                        "candidates": [
                            {**star("star-2", "下雨天她总是走在外侧", "2025-03-11T02:00:00+00:00"), "candidate_id": "cand-1"},
                            {**star("star-3", "我记得那把伞的颜色", "2026-08-20T02:00:00+00:00"), "candidate_id": "cand-2"},
                        ],
                    }
                ],
            }

    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=None, store=None)
    service._stars = lambda: FakeStars()
    out = asyncio.run(service.star_review())

    entry = out["items"][0]
    assert entry["编号"] == "1"
    assert [c["编号"] for c in entry["candidates"]] == ["1.1", "1.2"]
    # run_id 一个字都不给他。
    assert "run_id" not in entry
    assert "run_id" not in json.dumps(out, ensure_ascii=False)
    # 排序内部照旧留在服务层。
    assert all("score" not in c and "scores" not in c for c in entry["candidates"])


def test_review_says_how_long_ago_each_star_landed():
    """时间差本身就是 review 的内容：一年半前那颗和上周那颗，"像是有关系"的
    意味完全不同。"""
    from shenyu_gateway.gateway_tools._stars import _star_seen_ago
    from shenyu_gateway.runtime import local_today
    from datetime import timedelta

    today = local_today()

    def ago(days):
        return _star_seen_ago({"created_at": (today - timedelta(days=days)).isoformat()})

    assert ago(1) == "昨天"
    assert ago(7) == "一周前"
    # 一个月内走房间和便签共用的那套说法；更久说月数年数——human_time_ago
    # 四周以上退回天数，而「538天前」对一年半这种跨度没有感觉。
    assert ago(65) == "2个月前"
    assert ago(538) == "1年5个月前"
    assert "天前" not in ago(538)


def test_a_star_that_is_ordinary_says_nothing_about_it():
    """回声：绝大多数星星都是 active、都不是恒星、都没改过。"""
    from shenyu_gateway.gateway_tools._stars import _clean_star

    plain = _clean_star(
        {
            "id": "s-1",
            "content": "正文",
            "chord": "Am",
            "chord_sequence": ["Am"],
            "status": "active",
            "is_constant": False,
            "created_at": "2026-07-01T02:00:00+00:00",
            "updated_at": "2026-07-01T09:00:00+00:00",
        }
    )
    assert plain == {"id": "s-1", "content": "正文", "chord": "Am", "created_at": "2026-07-01T02:00:00+00:00"}

    # 不普通的地方才说：收起来的、恒星的、真改过的。
    special = _clean_star(
        {
            "id": "s-2",
            "content": "正文",
            "chord": "Am",
            "chord_sequence": ["Am", "F"],
            "status": "archived",
            "is_constant": True,
            "created_at": "2026-07-01T02:00:00+00:00",
            "updated_at": "2026-08-20T02:00:00+00:00",
        }
    )
    assert special["status"] == "archived"
    assert special["is_constant"] is True
    assert special["chord_sequence"] == ["Am", "F"]
    assert special["updated_at"] == "2026-08-20T02:00:00+00:00"


def test_mem_note_listing_strips_internal_bookkeeping(monkeypatch):
    service = GatewayToolService(runtime_config=SimpleNamespace(), supabase=None, store=None)

    class FakeMemNotes:
        async def list_notes(self, **kwargs):
            return {
                "ok": True,
                "status": "active",
                "count": 1,
                "status_counts": {"active": 1},
                "eligible_count": 1,
                "stored_count": 1,
                "items": [
                    {
                        "id": "note-1",
                        "content": "圆圆睡前要热水",
                        "summary": "热水",
                        "mem_type": "habit",
                        "status": "active",
                        "created_at": "2026-07-01T00:00:00+00:00",
                        "heat": 3,
                        "importance": 0.7,
                        "confidence": 0.9,
                        "promotion_score": 0.4,
                        "mention_count": 2,
                        "trigger_count": 5,
                        "cooldown_hours": 72,
                        "last_triggered_at": "2026-07-20",
                        "suggested_mem_type": "habit",
                        "auto_surface_eligible": True,
                        "written_by_shenyu": True,
                        "source_model": "m",
                    }
                ],
            }

    monkeypatch.setattr(service, "_mem_notes", lambda: FakeMemNotes())

    result = asyncio.run(service.list_mem_notes())

    assert result == {
        "ok": True,
        "count": 1,
        "status": "active",
        "items": [
            {
                "id": "note-1",
                "content": "圆圆睡前要热水",
                "summary": "热水",
                "mem_type": "habit",
                "status": "active",
                "created_at": "2026-07-01T00:00:00+00:00",
            }
        ],
    }
