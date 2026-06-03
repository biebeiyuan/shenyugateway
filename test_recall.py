from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from shenyu_gateway.recall import (
    EMBEDDING_TEXT_MAX_CHARS,
    RECALL_CHUNK_MAX_CHARS,
    RecallDocument,
    RecallIndexService,
    build_embedding_text,
    recall_terms,
    split_recall_chunks,
    _recency_score,
)


class FakeSupabase:
    def __init__(self, rows, vector_rows=None):
        self.rows = rows
        self.vector_rows = vector_rows or []
        self.rpc_calls = []
        self.updates = []
        self.upserts = []

    async def query(self, table, params=None):
        assert table == "shenyu_recall_index"
        return self.rows

    async def update(self, table, match, data):
        self.updates.append((table, match, data))
        return []

    async def upsert(self, table, data, on_conflict=None):
        if isinstance(data, list):
            self.upserts.extend(data)
        else:
            self.upserts.append(data)
        return data

    async def rpc(self, fn, params=None):
        self.rpc_calls.append((fn, params or {}))
        if fn == "search_shenyu_recall_index":
            return self.rows
        return self.vector_rows


class FakeEmbeddingClient:
    def __init__(self, vector=None, error=None):
        self.enabled = True
        self.model = "test-embedding"
        self.vector = vector if vector is not None else [0.1] * 1024
        self.error = error

    async def embed(self, text):
        if self.error:
            return None, self.error
        return self.vector, None


class SlowEmbeddingClient(FakeEmbeddingClient):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def embed(self, text):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.vector, None


class BrokenSupabase:
    async def query(self, table, params=None):
        raise RuntimeError("relation shenyu_recall_index does not exist")

    async def update(self, table, match, data):
        raise RuntimeError("relation shenyu_recall_index does not exist")


def test_split_recall_chunks_keeps_embedding_sized_chunks():
    text = "第一段。" * 1200

    chunks = split_recall_chunks(text)

    assert chunks
    assert all(len(chunk) <= RECALL_CHUNK_MAX_CHARS for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text


def test_build_embedding_text_keeps_title_and_limits_length():
    body = "长隆海洋馆海獭企鹅" * 500

    embedding_text = build_embedding_text("长隆", ["海獭", "企鹅"], body)

    assert len(embedding_text) <= EMBEDDING_TEXT_MAX_CHARS
    assert "标题：长隆" in embedding_text
    assert "标签：海獭 企鹅" in embedding_text
    assert "正文：" in embedding_text


def test_recall_terms_adds_cjk_bigrams_for_short_words():
    terms = recall_terms("中文分词")

    assert "中文分词" in terms
    assert "中文" in terms
    assert "分词" in terms
    assert "文分" in terms


def test_recency_score_uses_slow_step_decay():
    now = datetime.now(timezone.utc)

    assert _recency_score(now - timedelta(days=3)) == 1.0
    assert _recency_score(now - timedelta(days=20)) == 0.75
    assert _recency_score(now - timedelta(days=90)) == 0.55
    assert _recency_score(now - timedelta(days=250)) == 0.4
    assert _recency_score(now - timedelta(days=500)) == 0.3


def test_recall_ranks_keyword_title_and_tag_hits():
    rows = [
        {
            "source_table": "journal",
            "source_id": "1",
            "source_type": "journal",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "普通日记",
            "excerpt": "今天吃饭睡觉。",
            "body": "今天吃饭睡觉。",
            "search_text": "普通日记 今天吃饭睡觉",
            "search_tokens": ["普通", "日记", "今天", "吃饭", "睡觉"],
            "tags_json": ["diary"],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.6,
            "status": "active",
            "visibility": None,
        },
        {
            "source_table": "memories",
            "source_id": "2",
            "source_type": "memory",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "长隆海洋馆",
            "excerpt": "她想看海獭，也提到了企鹅。",
            "body": "她想看海獭，也提到了企鹅。完整匹配 chunk 会给模型，不用 embedding_text。",
            "embedding_text": "标题：长隆\n\n正文：被裁剪的 embedding 输入文本",
            "search_text": "长隆海洋馆 她想看海獭，也提到了企鹅。",
            "search_tokens": ["长隆", "海洋", "洋馆", "海獭", "企鹅"],
            "tags_json": ["海獭"],
            "entities_json": ["长隆"],
            "event_date": "2026-05-21T00:00:00+00:00",
            "importance": 0.8,
            "status": "active",
            "visibility": None,
        },
    ]
    supabase = FakeSupabase(rows)
    service = RecallIndexService(supabase)

    result = asyncio.run(service.recall("长隆 海獭", session_tag="5.15", auto_sync=False))

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["items"][0] == {
        "content": "她想看海獭，也提到了企鹅。完整匹配 chunk 会给模型，不用 embedding_text。",
        "title": "长隆海洋馆",
        "source_type": "memory",
        "source_table": "memories",
        "event_date": "2026-05-21T00:00:00+00:00",
    }
    assert result["items"][0]["title"] == "长隆海洋馆"
    assert "embedding_text" not in result["items"][0]
    assert "excerpt" not in result["items"][0]
    assert "source_id" not in result["items"][0]
    assert "score" not in result["items"][0]
    assert supabase.rpc_calls[0][0] == "search_shenyu_recall_index"
    assert supabase.rpc_calls[0][1]["query_tokens"] == ["长隆", "海獭"]
    assert supabase.rpc_calls[0][1]["match_count"] == 160


def test_recall_public_item_includes_title_only_for_journal():
    rows = [
        {
            "source_table": "journal",
            "source_id": "1",
            "source_type": "journal",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "长隆日记",
            "body": "今天写到了长隆和海獭。",
            "excerpt": "今天写到了长隆和海獭。",
            "search_text": "长隆日记 今天写到了长隆和海獭",
            "search_tokens": ["长隆", "日记", "海獭"],
            "tags_json": ["diary"],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.6,
            "status": "active",
            "visibility": None,
        },
    ]
    service = RecallIndexService(FakeSupabase(rows))

    result = asyncio.run(service.recall("长隆 海獭", session_tag="5.15", auto_sync=False))

    assert result["items"] == [
        {
            "content": "今天写到了长隆和海獭。",
            "title": "长隆日记",
            "source_type": "journal",
            "source_table": "journal",
            "event_date": "2026-05-20T00:00:00+00:00",
        }
    ]


def test_recall_public_item_includes_any_source_title_and_full_source_chunks():
    rows = [
        {
            "source_table": "room",
            "source_id": "room-1",
            "source_type": "room",
            "chunk_index": 1,
            "session_tag": "5.15",
            "title": "海洋馆房间",
            "body": "第二段写海獭。",
            "excerpt": "第二段写海獭。",
            "search_text": "第二段写海獭",
            "search_tokens": ["第二", "海獭"],
            "tags_json": [],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.8,
            "status": "open",
            "visibility": "self",
        },
        {
            "source_table": "room",
            "source_id": "room-1",
            "source_type": "room",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "海洋馆房间",
            "body": "第一段写长隆。",
            "excerpt": "第一段写长隆。",
            "search_text": "第一段写长隆",
            "search_tokens": ["第一", "长隆"],
            "tags_json": [],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.8,
            "status": "open",
            "visibility": "self",
        },
    ]
    service = RecallIndexService(FakeSupabase(rows))

    result = asyncio.run(service.recall("海獭", session_tag="5.15", auto_sync=False))

    assert result["items"] == [
        {
            "content": "第一段写长隆。\n\n第二段写海獭。",
            "title": "海洋馆房间",
            "source_type": "room",
            "source_table": "room",
            "event_date": "2026-05-20T00:00:00+00:00",
        }
    ]


def test_recall_falls_back_to_keyword_when_embedding_fails():
    rows = [
        {
            "source_table": "journal",
            "source_id": "1",
            "source_type": "journal",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "长隆日记",
            "body": "今天写到了长隆和海獭。",
            "excerpt": "今天写到了长隆和海獭。",
            "search_text": "长隆日记 今天写到了长隆和海獭",
            "search_tokens": ["长隆", "日记", "海獭"],
            "tags_json": [],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.6,
            "status": "active",
            "visibility": None,
        },
    ]
    supabase = FakeSupabase(rows)
    service = RecallIndexService(supabase, embedding_client=FakeEmbeddingClient(error="quota exceeded"))

    result = asyncio.run(service.recall("长隆 海獭", session_tag="5.15", auto_sync=False))

    assert result == {
        "ok": True,
        "count": 1,
        "items": [
            {
                "content": "今天写到了长隆和海獭。",
                "title": "长隆日记",
                "source_type": "journal",
                "source_table": "journal",
                "event_date": "2026-05-20T00:00:00+00:00",
            }
        ],
    }
    assert [call[0] for call in supabase.rpc_calls] == ["search_shenyu_recall_index"]


def test_recall_returns_vector_only_candidate_when_keywords_miss():
    vector_row = {
        "source_table": "room",
        "source_id": "room-1",
        "source_type": "room",
        "chunk_index": 0,
        "session_tag": "5.15",
        "title": "海洋馆房间",
        "body": "这里没有表面关键词，但语义向量召回了这一段。",
        "excerpt": "这里没有表面关键词。",
        "search_text": "完全不同的文字",
        "search_tokens": ["完全", "不同"],
        "tags_json": [],
        "entities_json": [],
        "event_date": "2026-05-20T00:00:00+00:00",
        "importance": 0.6,
        "status": "open",
        "visibility": "self",
        "vector_score": 0.83,
    }
    supabase = FakeSupabase([], vector_rows=[vector_row])
    service = RecallIndexService(supabase, embedding_client=FakeEmbeddingClient())

    result = asyncio.run(service.recall("想看动物", session_tag="5.15", auto_sync=False))

    assert result == {
        "ok": True,
        "count": 1,
        "items": [
            {
                "content": "这里没有表面关键词，但语义向量召回了这一段。",
                "title": "海洋馆房间",
                "source_type": "room",
                "source_table": "room",
                "event_date": "2026-05-20T00:00:00+00:00",
            }
        ],
    }
    match_call = next(call for call in supabase.rpc_calls if call[0] == "match_shenyu_recall_index")
    assert isinstance(match_call[1]["query_embedding"], str)
    assert match_call[1]["query_embedding"].startswith("[")


def test_recall_merges_keyword_and_vector_chunks_for_same_source():
    keyword_row = {
        "source_table": "room",
        "source_id": "room-1",
        "source_type": "room",
        "chunk_index": 0,
        "session_tag": "5.15",
        "title": "混合召回房间",
        "body": "第一段写长隆关键词。",
        "excerpt": "第一段写长隆关键词。",
        "search_text": "第一段写长隆关键词",
        "search_tokens": ["长隆"],
        "tags_json": [],
        "entities_json": [],
        "event_date": "2026-05-20T00:00:00+00:00",
        "importance": 0.6,
        "status": "open",
        "visibility": "self",
    }
    vector_row = {
        **keyword_row,
        "chunk_index": 1,
        "body": "第二段是语义向量命中的海洋馆细节。",
        "excerpt": "第二段是语义向量命中的海洋馆细节。",
        "search_text": "第二段是语义向量命中的海洋馆细节",
        "search_tokens": ["海洋馆"],
        "vector_score": 0.9,
    }
    supabase = FakeSupabase([keyword_row], vector_rows=[vector_row])
    service = RecallIndexService(supabase, embedding_client=FakeEmbeddingClient())

    result = asyncio.run(service.recall("长隆", session_tag="5.15", auto_sync=False))

    assert result["count"] == 1
    assert result["items"][0]["content"] == "第一段写长隆关键词。\n\n第二段是语义向量命中的海洋馆细节。"


def test_upsert_documents_resets_embedding_only_when_content_changes():
    doc = RecallDocument(
        source_table="journal",
        source_id="1",
        source_type="journal",
        chunk_index=0,
        session_tag="5.15",
        title="长隆日记",
        body="新的正文",
        excerpt="新的正文",
        search_text="长隆日记 新的正文",
        search_tokens=["长隆", "日记"],
        embedding_text="标题：长隆日记\n\n正文：新的正文",
        tags_json=[],
        entities_json=[],
        metadata_json={},
        event_date="2026-05-20T00:00:00+00:00",
        source_created_at="2026-05-20T00:00:00+00:00",
        source_updated_at="2026-05-20T00:00:00+00:00",
        status="active",
        visibility=None,
        importance=0.6,
        content_hash="new-hash",
    )
    changed = FakeSupabase([{"source_id": "1", "chunk_index": 0, "content_hash": "old-hash"}])
    unchanged = FakeSupabase([{"source_id": "1", "chunk_index": 0, "content_hash": "new-hash"}])

    asyncio.run(RecallIndexService(changed)._upsert_documents([doc]))
    asyncio.run(RecallIndexService(unchanged)._upsert_documents([doc]))

    assert changed.upserts[0]["embedding_status"] == "pending"
    assert changed.upserts[0]["embedding"] is None
    assert "embedding" not in unchanged.upserts[0]
    assert "embedding_status" not in unchanged.upserts[0]


def test_mark_stale_source_deleted_only_after_live_docs_are_known():
    supabase = FakeSupabase(
        [
            {"source_id": "keep", "chunk_index": 0, "content_hash": "same"},
            {"source_id": "stale", "chunk_index": 0, "content_hash": "old"},
        ]
    )
    doc = RecallDocument(
        source_table="journal",
        source_id="keep",
        source_type="journal",
        chunk_index=0,
        session_tag="5.15",
        title="保留",
        body="正文",
        excerpt="正文",
        search_text="保留 正文",
        search_tokens=["保留"],
        embedding_text="标题：保留\n\n正文：正文",
        tags_json=[],
        entities_json=[],
        metadata_json={},
        event_date=None,
        source_created_at=None,
        source_updated_at=None,
        status="active",
        visibility=None,
        importance=0.6,
        content_hash="same",
    )
    service = RecallIndexService(supabase)

    asyncio.run(service._upsert_documents([doc]))
    asyncio.run(service._mark_stale_source_deleted("journal", [doc]))

    assert supabase.upserts[0]["source_id"] == "keep"
    assert supabase.updates == [
        (
            "shenyu_recall_index",
            {"source_table": "journal", "source_id": "stale", "chunk_index": 0},
            {"deleted_at": supabase.updates[0][2]["deleted_at"]},
        )
    ]


def test_embed_pending_returns_running_status_for_concurrent_call():
    async def run_case():
        row = {
            "id": "recall-1",
            "embedding_text": "标题：长隆\n\n正文：海獭企鹅",
            "embedding_status": "pending",
        }
        supabase = FakeSupabase([row])
        embedding_client = SlowEmbeddingClient()
        service = RecallIndexService(supabase, embedding_client=embedding_client)

        first_task = asyncio.create_task(service.embed_pending(limit=5))
        await embedding_client.started.wait()
        second_result = await service.embed_pending(limit=5)
        embedding_client.release.set()
        first_result = await first_task

        return supabase, embedding_client, first_result, second_result

    supabase, embedding_client, first_result, second_result = asyncio.run(run_case())

    assert first_result["ok"] is True
    assert first_result["embedded"] == 1
    assert second_result == {
        "ok": False,
        "enabled": True,
        "seen": 0,
        "embedded": 0,
        "failed": 0,
        "already_running": True,
        "error": "Embedding worker is already running.",
    }
    assert embedding_client.calls == 1
    assert len(supabase.updates) == 1


def test_recall_date_filter_can_exclude_undated_rows():
    rows = [
        {
            "source_table": "memories",
            "source_id": "undated",
            "source_type": "memory",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "旧迁移记忆",
            "body": "长隆旧记忆，没有日期。",
            "excerpt": "长隆旧记忆，没有日期。",
            "search_text": "旧迁移记忆 长隆旧记忆 没有日期",
            "search_tokens": ["长隆", "旧记"],
            "tags_json": [],
            "entities_json": [],
            "event_date": None,
            "source_updated_at": None,
            "importance": 0.6,
            "status": "active",
            "visibility": None,
        },
        {
            "source_table": "journal",
            "source_id": "dated",
            "source_type": "journal",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "长隆日记",
            "body": "长隆有日期。",
            "excerpt": "长隆有日期。",
            "search_text": "长隆日记 长隆有日期",
            "search_tokens": ["长隆"],
            "tags_json": [],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.6,
            "status": "active",
            "visibility": None,
        },
    ]
    service = RecallIndexService(FakeSupabase(rows))

    default_result = asyncio.run(
        service.recall("长隆", session_tag="5.15", date_from="2026-05-01", auto_sync=False)
    )
    strict_result = asyncio.run(
        service.recall(
            "长隆",
            session_tag="5.15",
            date_from="2026-05-01",
            include_undated=False,
            auto_sync=False,
        )
    )

    assert default_result["count"] == 2
    assert [item["source_table"] for item in strict_result["items"]] == ["journal"]


def test_recall_returns_clear_error_when_index_table_is_missing():
    service = RecallIndexService(BrokenSupabase())

    result = asyncio.run(service.recall("长隆 海獭", auto_sync=False))

    assert result["ok"] is False
    assert result["count"] == 0
    assert "recall index table is not ready" in result["error"]


def test_recall_source_type_filter_hides_atomic_meta_and_public_mem_note():
    service = RecallIndexService(FakeSupabase([]))

    assert service._source_type_filter(None) == ["memory", "journal", "room", "board", "calendar", "notebook"]
    assert service._source_type_filter(["mem_note"]) == []
    assert service._source_type_filter(["note"]) == []
    assert service._source_type_filter(["mem_note"], allow_mem_note=True) == ["mem_note", "note"]
    assert service._source_type_filter(["note"], allow_mem_note=True) == ["mem_note", "note"]
    assert service._source_type_filter(["atomic", "meta", "memory"]) == ["memory"]
    assert service._source_type_filter(["atomic", "meta"]) == []
    assert service._adapter_names() == [
        "journal",
        "room",
        "message_board",
        "memories",
        "calendar_pages",
        "shenyu_mem_notes",
        "shenyu_notebook",
    ]
    assert service._adapter_names(["atomic", "meta", "mem_note"]) == ["shenyu_mem_notes"]
    assert service._adapter_names(["atomic", "meta"]) == []


def test_recall_default_filters_out_mem_note_and_atomic_rows_from_rpc():
    rows = [
        {
            "source_table": "shenyu_mem_notes",
            "source_id": "note-1",
            "source_type": "mem_note",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "mem",
            "body": "mem note 不该由公开 recall 返回。",
            "excerpt": "mem note 不该由公开 recall 返回。",
            "search_text": "长隆 mem note",
            "search_tokens": ["长隆"],
            "tags_json": [],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.8,
            "status": "active",
            "visibility": None,
        },
        {
            "source_table": "atomic_memories",
            "source_id": "atomic-1",
            "source_type": "atomic",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "atomic",
            "body": "atomic 不该由公开 recall 返回。",
            "excerpt": "atomic 不该由公开 recall 返回。",
            "search_text": "长隆 atomic",
            "search_tokens": ["长隆"],
            "tags_json": [],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.8,
            "status": "active",
            "visibility": None,
        },
        {
            "source_table": "memories",
            "source_id": "memory-1",
            "source_type": "memory",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "memory",
            "body": "公开 recall 保留 memory 正文。",
            "excerpt": "公开 recall 保留 memory 正文。",
            "search_text": "长隆 memory",
            "search_tokens": ["长隆"],
            "tags_json": [],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.8,
            "status": "active",
            "visibility": None,
        },
    ]
    supabase = FakeSupabase(rows)
    service = RecallIndexService(supabase)

    result = asyncio.run(service.recall("长隆", session_tag="5.15", auto_sync=False))

    assert [item["source_table"] for item in result["items"]] == ["memories"]
    assert supabase.rpc_calls[0][1]["source_types"] == ["memory", "journal", "room", "board", "calendar", "notebook"]


def test_recall_rejects_removed_source_types_without_widening_to_all():
    rows = [
        {
            "source_table": "memories",
            "source_id": "1",
            "source_type": "memory",
            "chunk_index": 0,
            "session_tag": "5.15",
            "title": "长隆海洋馆",
            "body": "今天写到了长隆和海獭。",
            "excerpt": "今天写到了长隆和海獭。",
            "search_text": "长隆海洋馆 今天写到了长隆和海獭",
            "search_tokens": ["长隆", "海獭"],
            "tags_json": [],
            "entities_json": [],
            "event_date": "2026-05-20T00:00:00+00:00",
            "importance": 0.6,
            "status": "active",
            "visibility": None,
        },
    ]
    supabase = FakeSupabase(rows)
    service = RecallIndexService(supabase)

    result = asyncio.run(service.recall("长隆", source_types=["atomic", "meta"], session_tag="5.15", auto_sync=False))

    assert result == {"ok": True, "count": 0, "items": []}
    assert supabase.rpc_calls == []
