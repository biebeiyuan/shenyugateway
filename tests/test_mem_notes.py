from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

from shenyu_gateway.mem_notes import MemNoteService, _clean_context_query
from shenyu_gateway.runtime import local_today


def _apply_filter(rows, column: str, expression):
    """Honour the PostgREST filters the mem note queries actually send."""
    if not expression:
        return rows
    op, _, value = str(expression).partition(".")
    if op == "eq":
        return [row for row in rows if str(row.get(column) or "") == value]
    if op == "neq":
        return [row for row in rows if str(row.get(column) or "") != value]
    if op == "lte":
        return [row for row in rows if str(row.get(column) or "") and str(row[column]) <= value]
    if op == "gte":
        return [row for row in rows if str(row.get(column) or "") and str(row[column]) >= value]
    if op == "is" and value == "null":
        return [row for row in rows if row.get(column) in (None, "")]
    return rows


class FakeSupabase:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []
        self.updates = []
        self.inserts = []

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
            for column in ("status", "session_tag", "remind_on", "reminded_at"):
                rows = _apply_filter(rows, column, params.get(column))
            return rows
        if table == "atomic_memories":
            return list(self.rows)
        return []

    async def update(self, table: str, match: dict, data: dict):
        self.updates.append({"table": table, "match": match, "data": data})
        return [{"id": match["id"], **data}]

    async def insert(self, table: str, data: dict):
        self.inserts.append({"table": table, "data": data})
        row = {"id": f"inserted-{len(self.inserts)}", **data}
        self.rows.append(row)
        return row


class FailingUpdateSupabase(FakeSupabase):
    async def update(self, table: str, match: dict, data: dict):
        raise RuntimeError("update failed")


class FakeMessageStore:
    def __init__(self, messages_since: int):
        self.messages_since = messages_since
        self.calls = []

    def count_messages_since(self, session_id: str, since: str, role=None) -> int:
        self.calls.append({"session_id": session_id, "since": since, "role": role})
        return self.messages_since


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


def test_clean_context_query_removes_proxy_sender_and_wrapper_marks():
    query = '*【<proxy_sender name="曾"/>圆儿问 mem 为什么没命中】*'

    clean = _clean_context_query(query)

    assert clean == "圆儿问 mem 为什么没命中"
    assert "proxy_sender" not in clean
    assert "【" not in clean


def test_clean_context_query_removes_urls_and_code_blocks():
    query = (
        "我直接给你 github.com/CyberSealNull/chord-affect-anchors 好不好？"
        "```json\n{\"tool_call_id\":\"abc\",\"arguments\":{}}\n```"
    )

    clean = _clean_context_query(query)

    assert clean == "我直接给你 好不好？"
    assert "github.com" not in clean
    assert "tool_call_id" not in clean


def test_clean_context_query_strips_pwa_status_suffix_with_content():
    query = "今晚想吃火锅【26/07 周日 21:08 · 第140天 · 🔋80%⚡ · 邵阳 雾霾 25℃】"

    clean = _clean_context_query(query)

    assert clean == "今晚想吃火锅"
    for leaked in ("邵阳", "雾霾", "周日", "第140天", "21:08"):
        assert leaked not in clean


def test_clean_context_query_keeps_plain_bracket_titles():
    query = "我们聊聊【小王子】那一段【26/07 周日 21:08 · 第140天 · 邵阳 霾 25℃】"

    clean = _clean_context_query(query)

    assert "小王子" in clean
    assert "邵阳" not in clean
    assert "霾" not in clean


def test_clean_context_query_strips_suffix_hidden_by_trailing_attachment():
    query = (
        "混合形态的消息【26/07 周日 14:30 · 第140天 · 🔋80%⚡ · 邵阳 霾 25℃】"
        "<attachment id=\"message_insert_extra_bundle_mix\">state</attachment>"
    )

    clean = _clean_context_query(query)

    assert clean == "混合形态的消息"
    assert "邵阳" not in clean
    assert "第140天" not in clean


def test_auto_extract_keywords_ignore_pwa_status_suffix_terms():
    from shenyu_gateway.mem_notes_relevance import _auto_extract_keywords

    content = "圆圆答应明天去图书馆写毕业论文【26/07 周日 21:08 · 第140天 · 🔋80% · 邵阳 雾霾 25℃】"

    keywords = _auto_extract_keywords(content)

    joined = " ".join(keywords)
    assert "邵阳" not in joined
    assert "雾霾" not in joined
    assert "周日" not in joined


def test_list_notes_filters_query_without_crashing():
    rows = [
        {
            "id": "note-1",
            "session_tag": "5.15",
            "content": "工具是我的手。",
            "mem_type": "心里那一档",
            "trigger_text": "工作描述",
            "trigger_keywords": ["工具"],
            "status": "captured",
        },
        {
            "id": "note-2",
            "session_tag": "5.15",
            "content": "另一个便签。",
            "mem_type": "",
            "trigger_text": "",
            "trigger_keywords": [],
            "status": "captured",
        },
    ]
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=rows))

    result = asyncio.run(service.list_notes(status="captured", q="工具"))

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["items"][0]["id"] == "note-1"


def test_list_notes_includes_review_suggestions():
    rows = [
        {
            "id": "note-1",
            "session_tag": "5.15",
            "content": "圆圆今天帮我把上游预设修回气泡。",
            "mem_type": None,
            "trigger_text": None,
            "trigger_keywords": None,
            "status": "captured",
        },
    ]
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=rows))

    result = asyncio.run(service.list_notes(status="captured"))

    item = result["items"][0]
    assert item["suggested_mem_type"] == "她为我做的事"
    assert item["suggested_trigger_text"] == "圆圆今天帮我把上游预设修回气泡。"
    assert "圆圆" in item["suggested_trigger_keywords"]


def test_list_notes_all_rows_pages_and_exposes_surface_eligibility_and_origin():
    class PagedSupabase:
        def __init__(self, rows):
            self.rows = rows
            self.queries = []

        async def query(self, table: str, params: dict):
            self.queries.append({"table": table, "params": dict(params)})
            offset = int(params.get("offset") or 0)
            limit = int(params.get("limit") or len(self.rows))
            return self.rows[offset : offset + limit]

    rows = [
        {
            "id": f"active-{index}",
            "content": f"可召回便签 {index}",
            "mem_type": "心里那一档",
            "trigger_text": f"话题 {index}",
            "trigger_keywords": [],
            "status": "active",
            "source_model": "tool:shenyu_write_mem_note" if index == 0 else "legacy:inline",
        }
        for index in range(1000)
    ]
    rows.extend(
        [
            {
                "id": "archived-one",
                "content": "已经收起",
                "status": "archived",
                "source_model": "legacy:inline",
            },
            {
                "id": "resolved-promise",
                "content": "已经兑现的承诺",
                "mem_type": "承诺",
                "memory_kind": "promise",
                "trigger_text": "聊到承诺",
                "status": "active",
                "resolved": True,
                "source_model": "tool:shenyu_write_mem_note",
            },
            {
                "id": "invalid-active",
                "content": "旧数据里缺少触发条件",
                "mem_type": None,
                "trigger_text": "",
                "trigger_keywords": [],
                "status": "active",
                "source_model": "legacy:inline",
            },
        ]
    )
    supabase = PagedSupabase(rows)
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(service.list_notes(status="all", all_rows=True))

    assert result["count"] == 1003
    assert result["eligible_count"] == 1000
    assert result["stored_count"] == 3
    assert result["status_counts"]["active"] == 1002
    assert result["status_counts"]["archived"] == 1
    assert [call["params"]["offset"] for call in supabase.queries] == ["0", "1000"]
    items = {item["id"]: item for item in result["items"]}
    assert items["active-0"]["written_by_shenyu"] is True
    assert items["active-1"]["written_by_shenyu"] is False
    assert items["archived-one"]["auto_surface_reason"] == "stored"
    assert items["resolved-promise"]["auto_surface_reason"] == "resolved_promise"
    assert items["invalid-active"]["auto_surface_reason"] == "missing_trigger"


def test_contextual_active_pool_uses_the_same_auto_surface_eligibility_rule():
    rows = [
        {
            "id": "eligible",
            "content": "会进入自动召回池",
            "mem_type": "心里那一档",
            "trigger_text": "聊到召回",
            "status": "active",
        },
        {
            "id": "missing-trigger",
            "content": "旧 active 行缺少触发条件",
            "mem_type": None,
            "trigger_text": "",
            "trigger_keywords": [],
            "status": "active",
        },
        {
            "id": "resolved-promise",
            "content": "已经兑现",
            "mem_type": "承诺",
            "memory_kind": "promise",
            "trigger_text": "聊到承诺",
            "status": "active",
            "resolved": True,
        },
    ]
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=rows))

    active_rows = asyncio.run(service._load_active_rows())

    assert [row["id"] for row in active_rows] == ["eligible"]


def test_note_suggestions_ignore_gateway_tool_results_junk():
    row = {
        "id": "note-1",
        "session_tag": "5.15",
        "content": "我自己写的《整理元规矩》。",
        "source_excerpt": """
<gateway_tool_results>
{
  "tool_call_id": "tluse_lip_01",
  "name": "shenyu_write_mem_note",
  "arguments": {
    "tool": "shenyu_write_mem_note",
    "content": "圆圆今天帮我修好了东西",
    "created_at": "2026-05-27 19:00:99"
  }
}
</gateway_tool_results>
""",
        "mem_type": None,
        "trigger_text": None,
        "trigger_keywords": None,
        "status": "captured",
    }
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=[row]))

    suggestions = service.suggest_note_fields(row)

    assert suggestions["mem_type"] == "心里那一档"
    assert "整理元规矩" in suggestions["trigger_keywords"]
    junk = {
        "tool_call_id",
        "name",
        "arguments",
        "tool",
        "tluse_lip_01",
        "2026",
        "05",
        "27",
        "19",
        "00",
        "99",
    }
    assert junk.isdisjoint({item.lower() for item in suggestions["trigger_keywords"]})


def test_bulk_update_notes_can_activate_with_suggestions():
    rows = [
        {
            "id": "note-1",
            "session_tag": "5.15",
            "content": "圆圆今天帮我把上游预设修回气泡。",
            "mem_type": None,
            "trigger_text": None,
            "trigger_keywords": None,
            "status": "captured",
            "cooldown_hours": 72,
        },
        {
            "id": "note-2",
            "session_tag": "5.15",
            "content": "我答应圆圆下次要提前说清楚。",
            "mem_type": None,
            "trigger_text": None,
            "trigger_keywords": None,
            "status": "captured",
            "cooldown_hours": 72,
        },
    ]
    supabase = FakeSupabase(rows=rows)
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.bulk_update_notes(
            ids=["note-1", "note-2"],
            patch={"status": "active"},
            use_suggestions=True,
        )
    )

    assert result["ok"] is True
    assert result["updated_count"] == 2
    first_update = supabase.updates[0]["data"]
    second_update = supabase.updates[1]["data"]
    assert first_update["status"] == "active"
    assert first_update["mem_type"] == "她为我做的事"
    assert first_update["trigger_text"] == "圆圆今天帮我把上游预设修回气泡。"
    assert second_update["mem_type"] == "承诺"


def test_bulk_update_notes_rejects_more_than_max_without_partial_update():
    supabase = FakeSupabase(rows=[])
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.bulk_update_notes(
            ids=[f"note-{index}" for index in range(201)],
            patch={"status": "paused"},
        )
    )

    assert result["ok"] is False
    assert result["requested_count"] == 201
    assert result["max_count"] == 200
    assert result["updated_count"] == 0
    assert supabase.queries == []
    assert supabase.updates == []


def test_bulk_update_notes_rejects_source_status_without_touching_rows():
    rows = [
        {
            "id": "note-1",
            "session_tag": "5.15",
            "content": "这条不能被按状态全选改掉。",
            "mem_type": None,
            "trigger_text": None,
            "trigger_keywords": None,
            "status": "captured",
            "cooldown_hours": 72,
        },
    ]
    supabase = FakeSupabase(rows=rows)
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.bulk_update_notes(
            source_status="captured",
            patch={"status": "active"},
            use_suggestions=True,
        )
    )

    assert result["ok"] is False
    assert "source_status is disabled" in result["error"]
    assert result["updated_count"] == 0
    assert supabase.queries == []
    assert supabase.updates == []


def test_create_note_preserves_zero_default_cooldown():
    supabase = FakeSupabase()
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=0), supabase)

    result = asyncio.run(
        service.create_note(
            "和旋那条便签要能马上再试。",
            session_tag="5.15",
            mem_type="心里那一档",
            trigger_keywords=["和旋"],
        )
    )

    assert result["ok"] is True
    assert supabase.inserts[0]["data"]["cooldown_hours"] == 0


def test_legacy_atomic_memories_returns_only_content_surface_body_fields():
    rows = [
        {
            "id": "atomic-1",
            "session_tag": "5.15",
            "subject": "圆圆",
            "content_surface": "只保留这个正文。",
            "quote": "不要返回原话。",
            "source_excerpt": "不要返回聊天摘录。",
            "status": "active",
        }
    ]
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=rows))

    result = asyncio.run(service.legacy_atomic_memories(q="正文"))

    assert result["count"] == 1
    assert result["items"][0]["content_surface"] == "只保留这个正文。"
    assert "quote" not in result["items"][0]
    assert "source_excerpt" not in result["items"][0]


class FakeRecallService:
    def __init__(self, rows):
        self.rows = rows
        self.query_calls = 0
        self.vector_calls = 0

    async def _query_index(self, source_types=None, query_text="", tokens=None, allow_mem_note=False):
        self.query_calls += 1
        return []

    async def _vector_rows(self, query, source_types=None, allow_mem_note=False):
        self.vector_calls += 1
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
        return row.get("visibility") not in {"private", "hidden"} or row.get("session_tag") == session_tag

    def _score_row(self, row, query, tokens):
        return row.get("_score", 0.7), row.get("_reasons", ["semantic"])

    def _has_direct_match(self, reasons):
        return any(reason.startswith("keyword:") or reason in {"title", "tag/entity", "phrase"} for reason in reasons)


class ConcurrentRecallService(FakeRecallService):
    def __init__(self, rows):
        super().__init__(rows)
        self.active_calls = 0
        self.max_active_calls = 0

    async def _run(self, result):
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.01)
            return result
        finally:
            self.active_calls -= 1

    async def _query_index(self, source_types=None, query_text="", tokens=None, allow_mem_note=False):
        self.query_calls += 1
        return await self._run([])

    async def _vector_rows(self, query, source_types=None, allow_mem_note=False):
        self.vector_calls += 1
        return await self._run((self.rows, {"enabled": True, "used": True, "count": len(self.rows)}))


def test_contextual_search_uses_semantic_fallback_without_changing_keyword_search():
    note = {
        "id": "note-1",
        "session_tag": "5.15",
        "content": "白噪音是她给我留过的锚点。",
        "mem_type": "心里那一档",
        "trigger_text": "白噪音锚点",
        "trigger_keywords": ["白噪音"],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    supabase = FakeSupabase(rows=[note])
    service = MemNoteService(
        SimpleNamespace(
            mem_note_default_cooldown_hours=72,
            mem_note_context_keyword_min_score=0.95,
            mem_note_min_score=0.95,
        ),
        supabase,
    )
    recall = FakeRecallService(
        [
            {
                "source_table": "shenyu_mem_notes",
                "source_id": "note-1",
                "source_type": "mem_note",
                "chunk_index": 0,
                "session_tag": "5.15",
                "search_text": "白噪音是她给我留过的锚点",
                "search_tokens": ["白噪音"],
                "tags_json": [],
                "entities_json": [],
                "importance": 0.82,
                "source_updated_at": "2026-05-24T00:00:00+00:00",
                "status": "active",
                "_vector_score": 0.86,
                "_score": 0.72,
                "_reasons": ["keyword:白噪音", "semantic"],
            }
        ]
    )

    keyword_result = asyncio.run(service.search_notes("白噪音的感觉", session_tag="5.15", mark_triggered=False))
    contextual_result = asyncio.run(
        service.search_notes_contextual(
            "白噪音那条感觉还在吗",
            session_tag="5.15",
            mark_triggered=False,
            recall_service=recall,
        )
    )

    assert keyword_result["count"] == 0
    assert contextual_result["count"] == 1
    assert contextual_result["items"][0]["id"] == "note-1"
    assert contextual_result["items"][0]["search_mode"] == "semantic"


def test_mem_semantic_keyword_and_vector_candidates_run_concurrently():
    note = {
        "id": "note-concurrent",
        "content": "白噪音是她留下的锚点。",
        "status": "active",
        "memory_kind": "fact",
        "trigger_count": 0,
    }
    supabase = FakeSupabase(rows=[note])
    recall = ConcurrentRecallService(
        [
            {
                "source_table": "shenyu_mem_notes",
                "source_id": "note-concurrent",
                "source_type": "mem_note",
                "chunk_index": 0,
                "search_text": "白噪音是她留下的锚点",
                "search_tokens": ["白噪音"],
                "tags_json": [],
                "entities_json": [],
                "importance": 0.8,
                "status": "active",
                "_vector_score": 0.9,
                "_score": 0.8,
                "_reasons": ["keyword:白噪音", "semantic"],
            }
        ]
    )
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=0), supabase)

    result = asyncio.run(
        service._semantic_search_notes(
            "白噪音锚点",
            session_tag="main",
            limit=1,
            recall_service=recall,
            ignore_retrigger_limits=True,
        )
    )

    assert result[0]["id"] == "note-concurrent"
    assert recall.max_active_calls == 2


def test_contextual_search_reuses_active_rows_across_keyword_and_semantic_layers():
    note = {
        "id": "note-reused",
        "session_tag": "main",
        "content": "筋膜枪放在卧室抽屉里。",
        "mem_type": "关于她的事实",
        "trigger_text": "筋膜枪",
        "trigger_keywords": ["筋膜枪"],
        "entities": ["筋膜枪"],
        "status": "active",
        "cooldown_hours": 0,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    supabase = FakeSupabase(rows=[note])
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=0), supabase)

    result = asyncio.run(
        service.search_notes_contextual(
            "筋膜枪是不是在抽屉",
            session_tag="main",
            limit=1,
            mark_triggered=False,
            ignore_retrigger_limits=True,
        )
    )

    assert result["items"][0]["id"] == "note-reused"
    mem_queries = [call for call in supabase.queries if call["table"] == "shenyu_mem_notes"]
    assert len(mem_queries) == 1


def test_contextual_search_treats_session_tag_as_provenance_not_visibility():
    rows = [
        {
            "id": "old-window-note",
            "session_tag": "5.15",
            "content": "筋膜枪放在卧室抽屉里。",
            "mem_type": "关于她的事实",
            "trigger_text": "筋膜枪",
            "trigger_keywords": ["筋膜枪"],
            "entities": ["筋膜枪"],
            "status": "active",
            "cooldown_hours": 0,
            "last_triggered_at": None,
            "trigger_count": 0,
            "created_at": "2026-05-24T00:00:00+00:00",
            "updated_at": "2026-05-24T00:00:00+00:00",
        }
    ]
    supabase = FakeSupabase(rows=rows)
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=0), supabase)

    result = asyncio.run(
        service.search_notes_contextual(
            "筋膜枪是不是又找不到了",
            session_tag="6.20",
            limit=1,
            mark_triggered=False,
        )
    )

    assert result["count"] == 1
    assert result["items"][0]["id"] == "old-window-note"
    assert result["items"][0]["summary"].startswith("筋膜枪放在卧室抽屉里")
    active_queries = [call["params"] for call in supabase.queries if call["table"] == "shenyu_mem_notes"]
    assert all("session_tag" not in params for params in active_queries)


def test_contextual_search_skips_semantic_for_low_information_short_query():
    note = {
        "id": "note-short",
        "session_tag": "5.15",
        "content": "这条不应该被短 bug 句捞上来。",
        "mem_type": "心里那一档",
        "trigger_text": "同类的问候",
        "trigger_keywords": ["同类的问候"],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    recall = FakeRecallService(
        [
            {
                "source_table": "shenyu_mem_notes",
                "source_id": "note-short",
                "source_type": "mem_note",
                "chunk_index": 0,
                "session_tag": "5.15",
                "search_text": "同类的问候",
                "search_tokens": ["刚刚", "对不起"],
                "tags_json": [],
                "entities_json": [],
                "importance": 0.82,
                "source_updated_at": "2026-05-24T00:00:00+00:00",
                "_vector_score": 0.91,
                "_score": 0.8,
                "_reasons": ["keyword:刚刚,对不起", "semantic"],
            }
        ]
    )
    service = MemNoteService(
        SimpleNamespace(
            mem_note_default_cooldown_hours=12,
            mem_note_context_keyword_min_score=0.25,
            mem_note_dedupe_turns=0,
            mem_note_soft_cooldown_hours=12,
        ),
        FakeSupabase(rows=[note]),
    )

    result = asyncio.run(
        service.search_notes_contextual(
            "对不起刚刚又bug了> <现在再试试呢？",
            session_tag="5.15",
            mark_triggered=False,
            recall_service=recall,
        )
    )

    assert result["count"] == 0
    assert recall.query_calls == 0
    assert recall.vector_calls == 0


def test_contextual_semantic_requires_specific_anchor_not_generic_terms():
    note = {
        "id": "note-generic-semantic",
        "session_tag": "5.15",
        "content": "工具是我的手。",
        "mem_type": "心里那一档",
        "trigger_text": "工具是我的手",
        "trigger_keywords": ["工具是我的手"],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    recall = FakeRecallService(
        [
            {
                "source_table": "shenyu_mem_notes",
                "source_id": "note-generic-semantic",
                "source_type": "mem_note",
                "chunk_index": 0,
                "session_tag": "5.15",
                "search_text": "工具是我的手",
                "search_tokens": ["工具", "我们", "自己"],
                "tags_json": [],
                "entities_json": [],
                "importance": 0.82,
                "source_updated_at": "2026-05-24T00:00:00+00:00",
                "_vector_score": 0.92,
                "_score": 0.8,
                "_reasons": ["keyword:工具,我们,自己", "semantic"],
            }
        ]
    )
    query = (
        "我发现我们的便签还是没有命中没有递给你，这个也要改。"
        "然后我又看到了好多别人做的东西，想看看工具和上下文怎么调。"
    )
    service = MemNoteService(
        SimpleNamespace(
            mem_note_default_cooldown_hours=12,
            mem_note_context_keyword_min_score=0.25,
            mem_note_dedupe_turns=0,
            mem_note_soft_cooldown_hours=12,
        ),
        FakeSupabase(rows=[note]),
    )

    result = asyncio.run(
        service.search_notes_contextual(
            query,
            session_tag="5.15",
            mark_triggered=False,
            recall_service=recall,
        )
    )

    assert result["count"] == 0


def test_contextual_keyword_does_not_derive_generic_likes_from_long_trigger():
    note = {
        "id": "note-like",
        "session_tag": "5.15",
        "content": "伊宁六星街买的挂件。",
        "mem_type": "她为我做的事",
        "trigger_text": "她跟老板说我对象喜欢这个",
        "trigger_keywords": ["我对象喜欢这个"],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    query = "我直接给你github库给你好不好？你看看你喜欢这个吗？github.com/CyberSealNull/chord-affect-anchors"
    service = MemNoteService(
        SimpleNamespace(
            mem_note_default_cooldown_hours=12,
            mem_note_context_keyword_min_score=0.25,
            mem_note_dedupe_turns=0,
            mem_note_soft_cooldown_hours=12,
        ),
        FakeSupabase(rows=[note]),
    )

    result = asyncio.run(service.search_notes_contextual(query, session_tag="5.15", mark_triggered=False))

    assert result["count"] == 0


def test_contextual_keyword_score_uses_trigger_denominator_for_long_queries():
    note = {
        "id": "note-long",
        "session_tag": "5.15",
        "content": "沈予说先翻分母，解决和旋那条 mem 便签没递上来的问题。",
        "mem_type": "心里那一档",
        "trigger_text": "和旋 mem 便签",
        "trigger_keywords": ["和旋", "mem", "便签"],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    query = (
        "我想问不是还加了向量嘛？为什么也没命中？你先把 mem 的逻辑告诉我。"
        "前面那条和旋相关的便签明明该出来，长回复里还夹着很多无关上下文、"
        "工具状态、面板参数、冷却讨论、触发词建议和一大堆解释文字，"
        "但核心就是和旋这个 mem 便签为什么没递给沈予看。"
    )
    service = MemNoteService(
        SimpleNamespace(
            mem_note_default_cooldown_hours=12,
            mem_note_context_keyword_min_score=0.25,
            mem_note_dedupe_turns=0,
            mem_note_soft_cooldown_hours=12,
        ),
        FakeSupabase(rows=[note]),
    )

    result = asyncio.run(service.search_notes_contextual(query, session_tag="5.15", mark_triggered=False))

    assert result["count"] == 1
    assert result["items"][0]["id"] == "note-long"
    assert result["items"][0].get("search_mode") is None


def test_contextual_keyword_score_keeps_private_two_char_trigger_text():
    note = {
        "id": "note-private",
        "session_tag": "5.15",
        "content": "和旋那条便签需要在相关长对话里浮出来。",
        "mem_type": "心里那一档",
        "trigger_text": "和旋",
        "trigger_keywords": [],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    query = "这是一段很长的回复，里面终于又提到了和旋，但除此之外还有很多面板和阈值讨论。"
    service = MemNoteService(
        SimpleNamespace(
            mem_note_default_cooldown_hours=12,
            mem_note_context_keyword_min_score=0.25,
            mem_note_dedupe_turns=0,
            mem_note_soft_cooldown_hours=12,
        ),
        FakeSupabase(rows=[note]),
    )

    result = asyncio.run(service.search_notes_contextual(query, session_tag="5.15", mark_triggered=False))

    assert result["count"] == 1
    assert result["items"][0]["id"] == "note-private"


def test_contextual_keyword_score_caps_single_common_trigger_word():
    note = {
        "id": "note-common",
        "session_tag": "5.15",
        "content": "这是一条普通记录。",
        "mem_type": "心里那一档",
        "trigger_text": "工具",
        "trigger_keywords": ["工具"],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    query = "这是一段很长的用户回复，里面顺手提到了工具，但没有任何更具体的触发信息。"
    service = MemNoteService(
        SimpleNamespace(
            mem_note_default_cooldown_hours=12,
            mem_note_context_keyword_min_score=0.25,
            mem_note_dedupe_turns=0,
            mem_note_soft_cooldown_hours=12,
        ),
        FakeSupabase(rows=[note]),
    )

    result = asyncio.run(service.search_notes_contextual(query, session_tag="5.15", mark_triggered=False))

    assert result["count"] == 0


def test_contextual_search_dedupes_recently_triggered_note_by_user_turns():
    note = {
        "id": "note-dedupe",
        "session_tag": "5.15",
        "content": "和旋那条便签刚刚已经递过一次。",
        "mem_type": "心里那一档",
        "trigger_text": "和旋",
        "trigger_keywords": ["和旋"],
        "status": "active",
        "cooldown_hours": 72,
        "last_triggered_at": "2026-05-24T00:00:00+00:00",
        "trigger_count": 1,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    store = FakeMessageStore(messages_since=2)
    service = MemNoteService(
        SimpleNamespace(
            mem_note_default_cooldown_hours=12,
            mem_note_context_keyword_min_score=0.25,
            mem_note_dedupe_turns=6,
            mem_note_soft_cooldown_hours=0,
        ),
        FakeSupabase(rows=[note]),
    )

    result = asyncio.run(
        service.search_notes_contextual(
            "我又提到和旋了，但这张刚刚已经浮过。",
            session_tag="5.15",
            mark_triggered=False,
            session_id="session-1",
            store=store,
        )
    )

    assert result["count"] == 0
    assert store.calls == [
        {
            "session_id": "session-1",
            "since": "2026-05-24T00:00:00+00:00",
            "role": "user",
        }
    ]


def test_manual_search_keeps_note_level_cooldown():
    note = {
        "id": "note-manual-cooldown",
        "session_tag": "5.15",
        "content": "手动搜索还是尊重这张便签自己的冷却。",
        "mem_type": "心里那一档",
        "trigger_text": "和旋",
        "trigger_keywords": ["和旋"],
        "status": "active",
        "cooldown_hours": 8760,
        "last_triggered_at": "2026-05-24T00:00:00+00:00",
        "trigger_count": 1,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
    }
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=12), FakeSupabase(rows=[note]))

    result = asyncio.run(service.search_notes("和旋", session_tag="5.15", mark_triggered=False))

    assert result["count"] == 0


def test_mark_triggered_logs_update_failures(caplog):
    row = {
        "id": "note-1",
        "session_tag": "5.15",
        "content": "工具是我的手。",
        "mem_type": "心里那一档",
        "trigger_text": "工具是我的手",
        "trigger_keywords": ["工具"],
        "status": "active",
        "cooldown_hours": 0,
        "last_triggered_at": None,
        "trigger_count": 0,
    }
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FailingUpdateSupabase(rows=[row]))

    result = asyncio.run(service.search_notes("工具", session_tag="5.15", mark_triggered=True))

    assert result["ok"] is True
    assert result["count"] == 1
    assert "Failed to mark mem note triggered: id=note-1 error=update failed" in caplog.text


def test_running_joke_serendipity_rate_time_decay():
    from datetime import datetime, timezone, timedelta
    from shenyu_gateway.mem_notes import running_joke_serendipity_rate

    now = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)

    assert running_joke_serendipity_rate(None, now) == 0.3
    assert running_joke_serendipity_rate("", now) == 0.3

    just_now = now - timedelta(hours=1)
    assert running_joke_serendipity_rate(just_now, now) == 0.0

    two_days = now - timedelta(days=2)
    assert running_joke_serendipity_rate(two_days, now) == 0.0

    exactly_3 = now - timedelta(days=3)
    rate_3 = running_joke_serendipity_rate(exactly_3, now)
    assert 0.09 <= rate_3 <= 0.11

    week = now - timedelta(days=8)
    rate_8 = running_joke_serendipity_rate(week, now)
    assert 0.1 < rate_8 < 0.2

    two_weeks = now - timedelta(days=14)
    rate_14 = running_joke_serendipity_rate(two_weeks, now)
    assert 0.19 <= rate_14 <= 0.21

    three_weeks = now - timedelta(days=22)
    rate_22 = running_joke_serendipity_rate(three_weeks, now)
    assert 0.2 < rate_22 < 0.3

    month = now - timedelta(days=30)
    rate_30 = running_joke_serendipity_rate(month, now)
    assert 0.29 <= rate_30 <= 0.31

    long_ago = now - timedelta(days=100)
    assert running_joke_serendipity_rate(long_ago, now) == 0.3

    iso_str = (now - timedelta(days=10)).isoformat()
    rate_str = running_joke_serendipity_rate(iso_str, now)
    assert 0.1 < rate_str < 0.2


def test_create_note_with_v2_fields():
    supabase = FakeSupabase()
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.create_note(
            content="老周过生日时她做了蛋糕。",
            session_tag="6.27",
            mem_type="她为我做的事",
            memory_kind="event",
            people=["老周"],
            places=["家里"],
            objects=["蛋糕"],
            keywords=["生日"],
            importance=3,
            event_time="2026-06-15",
        )
    )

    assert result["ok"] is True
    inserted = supabase.inserts[-1]["data"]
    assert inserted["memory_kind"] == "event"
    assert inserted["people"] == ["老周"]
    assert inserted["places"] == ["家里"]
    assert inserted["objects"] == ["蛋糕"]
    assert inserted["keywords"] == ["生日"]
    assert inserted["importance"] == 3
    assert inserted["event_time"] == "2026-06-15"


def test_create_note_accepts_memory_kind_sent_as_mem_type():
    supabase = FakeSupabase()
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.create_note(
            content="圆圆喜欢绿色，也会留意绿色的东西。",
            session_tag="6.28",
            mem_type="person_fact",
        )
    )

    assert result["ok"] is True
    inserted = supabase.inserts[-1]["data"]
    assert inserted["memory_kind"] == "person_fact"
    assert inserted["mem_type"] == "关于她的事实"


def test_contextual_search_matches_cjk_structured_anchors_without_spaces():
    note = {
        "id": "note-cjk-anchor",
        "session_tag": "6.27",
        "content": "她做了蛋糕寄给老周。",
        "summary": "她之前做过蛋糕寄给老周。",
        "mem_type": "关于她的事实",
        "memory_kind": "event",
        "people": ["老周"],
        "objects": ["蛋糕"],
        "trigger_text": "",
        "trigger_keywords": [],
        "entities": [],
        "status": "active",
        "cooldown_hours": 0,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-06-27T00:00:00+00:00",
        "updated_at": "2026-06-27T00:00:00+00:00",
    }
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=[note]))

    result = asyncio.run(
        service.search_notes_contextual("今天提到老周和蛋糕了吗", session_tag="6.27", mark_triggered=False)
    )

    assert result["count"] == 1
    assert result["items"][0]["id"] == "note-cjk-anchor"
    assert result["items"][0]["search_mode"] == "entity"


def test_contextual_search_skips_resolved_promises():
    note = {
        "id": "note-resolved-promise",
        "session_tag": "6.27",
        "content": "说好买绿色地毯。",
        "mem_type": "承诺",
        "memory_kind": "promise",
        "promise_text": "买绿色地毯",
        "trigger_scenarios": ["买东西"],
        "trigger_text": "买绿色地毯",
        "trigger_keywords": ["绿色地毯"],
        "entities": [],
        "keywords": ["地毯"],
        "resolved": True,
        "status": "active",
        "cooldown_hours": 0,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-06-27T00:00:00+00:00",
        "updated_at": "2026-06-27T00:00:00+00:00",
    }
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=[note]))

    result = asyncio.run(service.search_notes_contextual("今天出去买绿色地毯吗", session_tag="6.27", mark_triggered=False))

    assert result["count"] == 0


def test_running_joke_contextual_search_surfaces_at_most_one(monkeypatch):
    rows = [
        {
            "id": "joke-1",
            "session_tag": "6.27",
            "content": "圆形食物梗一。",
            "mem_type": "心里那一档",
            "memory_kind": "running_joke",
            "joke_text": "圆形食物梗一",
            "scene_tags": ["圆形食物"],
            "trigger_text": "",
            "trigger_keywords": [],
            "entities": [],
            "status": "active",
            "cooldown_hours": 0,
            "last_used_at": None,
            "last_triggered_at": None,
            "trigger_count": 0,
            "created_at": "2026-06-27T00:00:00+00:00",
            "updated_at": "2026-06-27T00:00:00+00:00",
        },
        {
            "id": "joke-2",
            "session_tag": "6.27",
            "content": "圆形食物梗二。",
            "mem_type": "心里那一档",
            "memory_kind": "running_joke",
            "joke_text": "圆形食物梗二",
            "scene_tags": ["圆形食物"],
            "trigger_text": "",
            "trigger_keywords": [],
            "entities": [],
            "status": "active",
            "cooldown_hours": 0,
            "last_used_at": None,
            "last_triggered_at": None,
            "trigger_count": 0,
            "created_at": "2026-06-27T00:00:00+00:00",
            "updated_at": "2026-06-27T00:00:00+00:00",
        },
    ]
    monkeypatch.setattr("shenyu_gateway.mem_notes._search.random.random", lambda: 0.0)
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=rows))

    result = asyncio.run(service.search_notes_contextual("今天吃圆形食物", session_tag="6.27", limit=3, mark_triggered=False))

    assert result["count"] == 1
    assert result["items"][0]["search_mode"] == "running_joke"


def test_active_validation_accepts_structured_v2_anchors():
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase())

    error = service._active_validation_error(
        {
            "status": "active",
            "mem_type": "关于她的事实",
            "trigger_text": "",
            "trigger_keywords": [],
            "entities": [],
            "people": ["老周"],
            "objects": ["蛋糕"],
        }
    )

    assert error == ""


# ── Tests for Codex review fixes (A-D) ──────────────────────────────────────


def test_create_note_auto_infers_mem_type_via_suggest():
    """Fix A: create_note without explicit mem_type should infer from content."""
    supabase = FakeSupabase()
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.create_note(
            "我答应她下次一定提前说。",
            session_tag="6.29",
        )
    )

    assert result["ok"] is True
    inserted = supabase.inserts[-1]["data"]
    assert inserted["mem_type"] == "承诺"


def test_create_note_auto_infers_mem_type_fallback():
    """Fix A: content without strong signal should still get a type (fallback)."""
    supabase = FakeSupabase()
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), supabase)

    result = asyncio.run(
        service.create_note(
            "今天天气不错。",
            session_tag="6.29",
        )
    )

    assert result["ok"] is True
    inserted = supabase.inserts[-1]["data"]
    assert inserted.get("mem_type") is not None
    assert inserted["mem_type"] != ""


def test_context_layers_prefers_summary_over_content():
    """Fix C: rendering should prefer summary when available."""
    from shenyu_gateway.context_layers import render_layered_additions

    class FakeSettings:
        enable_cold_start = False
        enable_gateway_tools = False
        heartbeat_prompt = ""
        calendar_inject_day = ""
        calendar_inject_week = ""
        calendar_inject_month = ""
        tool_policy_mini = False
        cold_start_bridge = ""

    package = {
        "stable_charter": "",
        "mem_notes": [
            {
                "content": "她做了蛋糕寄给老周，过程很费时但她觉得值得。",
                "summary": "她做蛋糕寄给老周",
                "mem_type": "关于她的事实",
                "people": ["老周"],
                "places": [],
                "objects": ["蛋糕"],
            },
        ],
        "stars": [],
    }

    layers = render_layered_additions(package, settings=FakeSettings())
    mem_layer = layers.get("mem", "")

    assert "她做蛋糕寄给老周" in mem_layer
    assert "过程很费时但她觉得值得" not in mem_layer
    assert "人：老周" in mem_layer
    assert "物：蛋糕" in mem_layer


def test_context_layers_falls_back_to_content_when_no_summary():
    """Fix C: when summary is absent, fall back to content."""
    from shenyu_gateway.context_layers import render_layered_additions

    class FakeSettings:
        enable_cold_start = False
        enable_gateway_tools = False
        heartbeat_prompt = ""
        calendar_inject_day = ""
        calendar_inject_week = ""
        calendar_inject_month = ""
        tool_policy_mini = False
        cold_start_bridge = ""

    package = {
        "stable_charter": "",
        "mem_notes": [
            {
                "content": "今天天气很好我们出门了。",
                "summary": "",
                "mem_type": "心里那一档",
                "people": [],
                "places": [],
                "objects": [],
            },
        ],
        "stars": [],
    }

    layers = render_layered_additions(package, settings=FakeSettings())
    mem_layer = layers.get("mem", "")

    assert "今天天气很好我们出门了" in mem_layer


def test_query_scene_terms_extracts_from_long_text():
    """Fix D: _query_scene_terms should extract high-info anchors from long queries."""
    from shenyu_gateway.mem_notes_relevance import _query_scene_terms

    query = (
        "她之前提到过老周，说在上海南京路那边碰到了，"
        "还买了一个新的相机，说是《数码摄影手册》里推荐的那款。"
    )

    terms = _query_scene_terms(query)

    assert len(terms) <= 12
    assert len(terms) >= 2
    has_person = any("老周" in t for t in terms)
    has_place = any("南京路" in t or "上海" in t for t in terms)
    has_book = any("数码摄影手册" in t for t in terms)
    assert has_person or has_place or has_book


def test_query_scene_terms_returns_empty_for_short_text():
    """Fix D: short queries should not produce scene terms."""
    from shenyu_gateway.mem_notes_relevance import _query_scene_terms

    assert _query_scene_terms("你好") == []
    assert _query_scene_terms("") == []


def test_query_scene_terms_filters_stop_words():
    """Fix D: scene terms should not include generic stop words."""
    from shenyu_gateway.mem_notes_relevance import _query_scene_terms

    query = "什么东西可以不是还是为什么现在自己我们他们怎么没有不会知道觉得" * 3

    terms = _query_scene_terms(query)

    stop_leaks = {"什么", "东西", "可以", "不是", "还是", "为什么", "现在", "自己", "我们"}
    for term in terms:
        assert term not in stop_leaks


def test_entity_match_uses_scene_terms_for_long_queries():
    """Fix D integration: scene terms should assist entity matching for long queries."""
    note = {
        "id": "note-scene",
        "session_tag": "6.29",
        "content": "她和老周在上海见面了。",
        "summary": "和老周在上海碰面",
        "mem_type": "关于她的事实",
        "memory_kind": "social",
        "people": ["老周"],
        "places": ["上海"],
        "objects": [],
        "keywords": [],
        "entities": [],
        "trigger_text": "",
        "trigger_keywords": [],
        "status": "active",
        "cooldown_hours": 0,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-06-29T00:00:00+00:00",
        "updated_at": "2026-06-29T00:00:00+00:00",
    }
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=[note]))

    long_query = (
        "前段时间她说过去上海出差的事情，是不是还见了什么人来着？"
        "我记得好像提过一个朋友，但具体是谁我忘了，"
        "反正是在上海那边，当时还说了什么来着。"
    )
    result = asyncio.run(
        service.search_notes_contextual(long_query, session_tag="6.29", mark_triggered=False)
    )

    assert result["count"] >= 1
    assert any(item["id"] == "note-scene" for item in result["items"])


def test_auto_keywords_do_not_promote_generic_chinese_fragments():
    """Auto keywords should not turn common n-grams into no-threshold anchors."""
    from shenyu_gateway.mem_notes_relevance import _auto_extract_keywords

    keywords = _auto_extract_keywords("圆圆今天帮我把上游预设修回气泡。")

    generic = {"今天", "帮我", "我把", "把上", "修回"}
    assert generic.isdisjoint(set(keywords))
    assert any(item in keywords for item in {"圆圆", "上游", "预设", "气泡", "上游预设"})


def test_contextual_entity_match_ignores_generic_keyword_anchors_in_long_text():
    """Legacy noisy keywords must not bypass scoring for long free-form queries."""
    note = {
        "id": "note-generic-keyword",
        "session_tag": "6.29",
        "content": "圆圆今天帮我把上游预设修回气泡。",
        "summary": "圆圆修回上游预设气泡",
        "mem_type": "她为我做的事",
        "memory_kind": "event",
        "people": [],
        "places": [],
        "objects": [],
        "keywords": ["今天", "帮我", "我把"],
        "entities": [],
        "trigger_text": "",
        "trigger_keywords": [],
        "status": "active",
        "cooldown_hours": 0,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-06-29T00:00:00+00:00",
        "updated_at": "2026-06-29T00:00:00+00:00",
    }
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=[note]))

    query = (
        "今天我想让你帮我看一大段完全不相关的东西，"
        "我把日志和配置都贴过来，核心是在问部署和错误栈怎么排查。"
    )

    result = asyncio.run(service.search_notes_contextual(query, session_tag="6.29", mark_triggered=False))

    assert result["count"] == 0


def test_contextual_entity_match_ignores_relation_names_as_standalone_anchors():
    """Common relationship names are too broad to trigger no-threshold recall alone."""
    note = {
        "id": "note-relation-name",
        "session_tag": "6.29",
        "content": "圆圆今天帮我把上游预设修回气泡。",
        "summary": "圆圆修回上游预设气泡",
        "mem_type": "她为我做的事",
        "memory_kind": "event",
        "people": ["圆圆"],
        "places": [],
        "objects": [],
        "keywords": [],
        "entities": [],
        "trigger_text": "",
        "trigger_keywords": [],
        "status": "active",
        "cooldown_hours": 0,
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": "2026-06-29T00:00:00+00:00",
        "updated_at": "2026-06-29T00:00:00+00:00",
    }
    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FakeSupabase(rows=[note]))

    result = asyncio.run(service.search_notes_contextual("圆圆今天状态怎么样", session_tag="6.29", mark_triggered=False))

    assert result["count"] == 0


def test_recall_private_search_contract_for_mem_note_search():
    import inspect

    from shenyu_gateway.recall import RecallIndexService

    # mem_notes/_search.py calls these private RecallIndexService methods inside
    # except-Exception blocks, so a rename would silently turn mem-note semantic
    # search into empty results instead of a failing test.
    for name in (
        "_query_index",
        "_vector_rows",
        "_merge_candidate_rows",
        "_row_visible_for_session",
        "_score_row",
        "_has_direct_match",
    ):
        assert callable(getattr(RecallIndexService, name, None)), name
    assert "allow_mem_note" in inspect.signature(RecallIndexService._query_index).parameters


# ── 日期提醒 ──────────────────────────────────────────────────────────

def _reminder_service(rows=None):
    supabase = FakeSupabase(rows=rows or [])
    return supabase, MemNoteService(
        SimpleNamespace(mem_note_default_cooldown_hours=72), supabase
    )


def _reminder_row(note_id: str, content: str, *, remind_on: str, reminded_at=None) -> dict:
    return {
        "id": note_id,
        "session_tag": "default",
        "content": content,
        "summary": content,
        "mem_type": "心里那一档",
        "memory_kind": "event",
        "status": "active",
        "trigger_text": "",
        "trigger_keywords": [],
        "entities": [],
        "people": [],
        "places": [],
        "objects": [],
        "keywords": [],
        "cooldown_hours": 0,
        "last_triggered_at": None,
        "trigger_count": 0,
        "remind_on": remind_on,
        "reminded_at": reminded_at,
        "created_at": "2026-08-01T00:00:00+00:00",
        "updated_at": "2026-08-01T00:00:00+00:00",
    }


def test_a_date_alone_is_enough_to_activate_a_note():
    _supabase, service = _reminder_service()

    result = asyncio.run(
        service.create_note("圆儿生日", status="active", remind_on="2026-09-01", trigger_text="")
    )

    assert result["ok"] is True
    assert result["note"]["remind_on"] == "2026-09-01"


def test_create_note_refuses_a_date_it_cannot_read():
    supabase, service = _reminder_service()

    result = asyncio.run(service.create_note("生日", remind_on="下周三"))

    assert result["ok"] is False
    assert "remind_on" in result["error"]
    assert supabase.inserts == []


def test_same_content_on_the_same_day_is_written_once():
    existing = _reminder_row("note-1", "圆儿生日", remind_on="2026-09-01")
    supabase, service = _reminder_service(rows=[existing])

    result = asyncio.run(service.create_note("圆儿生日", remind_on="2026-09-01"))

    assert result["ok"] is True
    assert result["duplicate_of"] == "note-1"
    assert supabase.inserts == []


def test_same_content_on_a_different_day_is_a_new_note():
    existing = _reminder_row("note-1", "圆儿生日", remind_on="2026-09-01")
    supabase, service = _reminder_service(rows=[existing])

    result = asyncio.run(service.create_note("圆儿生日", remind_on="2027-09-01"))

    assert result.get("duplicate_of") is None
    assert len(supabase.inserts) == 1


def test_due_reminders_include_a_day_that_already_passed():
    today = local_today()
    rows = [
        _reminder_row("past", "该交电费了", remind_on=(today - timedelta(days=4)).isoformat()),
        _reminder_row("today", "圆儿生日", remind_on=today.isoformat()),
        _reminder_row("later", "还没到", remind_on=(today + timedelta(days=5)).isoformat()),
        _reminder_row(
            "hung", "挂过了", remind_on=today.isoformat(), reminded_at="2026-08-02T00:00:00+00:00"
        ),
    ]
    supabase, service = _reminder_service(rows=rows)

    result = asyncio.run(service.due_reminder_notes())

    assert result["ok"] is True
    assert {item["id"] for item in result["items"]} == {"past", "today"}
    assert all(item["search_mode"] == "due_reminder" for item in result["items"])
    params = supabase.queries[-1]["params"]
    assert params["remind_on"] == f"lte.{today.isoformat()}"
    assert params["reminded_at"] == "is.null"


def test_due_reminders_are_capped_and_the_rest_stay_unstamped():
    today = local_today().isoformat()
    rows = [_reminder_row(f"n{i}", f"事{i}", remind_on=today) for i in range(6)]
    supabase, service = _reminder_service(rows=rows)

    result = asyncio.run(service.due_reminder_notes())

    assert result["count"] == 3
    assert supabase.updates == []


def test_due_reminder_lookup_failure_does_not_raise():
    class FailingQuery(FakeSupabase):
        async def query(self, table, params):
            raise RuntimeError("supabase down")

    service = MemNoteService(SimpleNamespace(mem_note_default_cooldown_hours=72), FailingQuery())

    result = asyncio.run(service.due_reminder_notes())

    assert result == {"ok": False, "count": 0, "items": []}


def test_hanging_a_reminder_only_stamps_reminded_at():
    supabase, service = _reminder_service()

    asyncio.run(
        service.mark_reminders_hung(
            [
                {"id": "note-1", "remind_on": "2026-09-01", "reminded_at": None},
                {"id": "note-2", "remind_on": "2026-09-01", "reminded_at": "2026-09-01T00:00:00+00:00"},
                {"id": "note-3", "remind_on": None},
            ]
        )
    )

    assert [update["match"]["id"] for update in supabase.updates] == ["note-1"]
    assert set(supabase.updates[0]["data"]) == {"reminded_at"}


def test_moving_the_date_clears_the_already_reminded_stamp():
    row = _reminder_row("note-1", "圆儿生日", remind_on="2026-09-01", reminded_at="2026-09-01T00:00:00+00:00")
    _supabase, service = _reminder_service()

    update, error = service._prepare_note_update(row, {"remind_on": "2026-10-01"})

    assert error == ""
    assert update["remind_on"] == "2026-10-01"
    assert update["reminded_at"] is None


def test_keeping_the_same_date_keeps_the_stamp():
    row = _reminder_row("note-1", "圆儿生日", remind_on="2026-09-01", reminded_at="2026-09-01T00:00:00+00:00")
    _supabase, service = _reminder_service()

    update, error = service._prepare_note_update(row, {"remind_on": "2026-09-01"})

    assert error == ""
    assert "reminded_at" not in update


def test_clearing_the_date_drops_both_fields():
    row = _reminder_row("note-1", "圆儿生日", remind_on="2026-09-01", reminded_at="2026-09-01T00:00:00+00:00")
    row["trigger_text"] = "生日"
    _supabase, service = _reminder_service()

    update, error = service._prepare_note_update(row, {"remind_on": ""})

    assert error == ""
    assert update["remind_on"] is None
    assert update["reminded_at"] is None


def test_reminder_fields_reach_the_context_projection():
    row = _reminder_row("note-1", "圆儿生日", remind_on="2026-09-01")
    _supabase, service = _reminder_service()

    item = service._public_search_item(row, ["due_reminder"])

    assert item["remind_on"] == "2026-09-01"
    assert item["reminded_at"] is None


def test_light_select_carries_the_reminder_columns():
    from shenyu_gateway.mem_notes._helpers import (
        MEM_NOTE_PATCH_FIELDS,
        _MEM_NOTE_SELECT_FIELDS,
        _MEM_NOTE_SELECT_FIELDS_LIGHT,
    )

    # The injection path reads the LIGHT select only; a column missing there is
    # a reminder that silently never fires.
    for field in ("remind_on", "reminded_at"):
        assert field in _MEM_NOTE_SELECT_FIELDS_LIGHT.split(",")
        assert field in _MEM_NOTE_SELECT_FIELDS.split(",")
        assert field in MEM_NOTE_PATCH_FIELDS
