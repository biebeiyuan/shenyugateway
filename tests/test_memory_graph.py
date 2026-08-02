import asyncio
from types import SimpleNamespace
from shenyu_gateway.memory_graph import (
    ALIAS_TABLE,
    ENTITY_TABLE,
    MENTION_TABLE,
    RECALL_INDEX_TABLE,
    RELATION_TABLE,
    MemoryGraphService,
    alias_matches_text,
    normalize_alias,
)
from shenyu_gateway.recall import RecallIndexService


class GraphSupabase:
    def __init__(self, tables=None):
        self.tables = {name: [dict(row) for row in rows] for name, rows in (tables or {}).items()}
        self._next_id = 1

    def _matches(self, row, params):
        controls = {"select", "order", "limit", "offset"}
        for key, condition in (params or {}).items():
            if key in controls:
                continue
            value = row.get(key)
            text = str(condition)
            if text.startswith("ilike.*") and text.endswith("*"):
                needle = text[len("ilike.*") : -1].lower()
                if needle not in str(value or "").lower():
                    return False
            elif text.startswith("eq."):
                expected = text[3:]
                if expected in {"true", "false"}:
                    if bool(value) is not (expected == "true"):
                        return False
                elif str(value) != expected:
                    return False
            elif text.startswith("in.("):
                values = [item.strip().strip('"') for item in text[4:-1].split(",") if item.strip()]
                if str(value) not in values:
                    return False
            elif text == "is.null":
                if value is not None:
                    return False
            elif str(value) != text:
                return False
        return True

    async def query(self, table, params=None):
        rows = [dict(row) for row in self.tables.get(table, []) if self._matches(row, params or {})]
        offset = int((params or {}).get("offset", 0))
        limit = int((params or {}).get("limit", len(rows) or 1000))
        return rows[offset : offset + limit]

    async def insert(self, table, data):
        row = dict(data)
        row.setdefault("id", f"row-{self._next_id}")
        self._next_id += 1
        self.tables.setdefault(table, []).append(row)
        return dict(row)

    async def update(self, table, match, data):
        rows = []
        for row in self.tables.get(table, []):
            if self._matches(row, match):
                row.update(data)
                rows.append(dict(row))
        return rows

    async def delete(self, table, match):
        deleted = []
        kept = []
        for row in self.tables.get(table, []):
            if self._matches(row, match):
                deleted.append(dict(row))
            else:
                kept.append(row)
        self.tables[table] = kept
        return deleted


def entity(entity_id, name):
    return {"id": entity_id, "canonical_name": name, "entity_type": "person", "status": "active"}


def alias(alias_id, entity_id, value):
    return {
        "id": alias_id,
        "entity_id": entity_id,
        "alias": value,
        "normalized_alias": normalize_alias(value),
        "status": "confirmed",
    }


def test_alias_matching_uses_phrase_and_ascii_token_boundaries():
    assert alias_matches_text("老周", "周一和周末没空，但老周周三来") is True
    assert alias_matches_text("老周", "周一和周末没空") is False
    assert alias_matches_text("lx", "我和LX一起听歌") is True
    assert alias_matches_text("lx", "flux 的变化") is False
    assert alias_matches_text("周", "周一") is False


def test_ambiguous_confirmed_alias_does_not_auto_link():
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("person-a", "老周 A"), entity("person-b", "老周 B")],
        ALIAS_TABLE: [alias("a1", "person-a", "老周"), alias("a2", "person-b", "老周")],
        MENTION_TABLE: [],
    })
    service = MemoryGraphService(supabase)

    result = asyncio.run(service.sync_source_alias_mentions(
        source_table="journal",
        source_type="journal",
        source_id="j-1",
        text="今天和老周吃饭。",
    ))

    assert result == {"ok": True, "matched": 0, "linked": 0, "removed": 0}
    assert supabase.tables[MENTION_TABLE] == []


def test_exact_alias_sync_preserves_manual_mentions_and_removes_stale_automatic_links():
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("person-a", "老周"), entity("person-b", "老妹")],
        ALIAS_TABLE: [alias("a1", "person-a", "老周"), alias("a2", "person-b", "老妹")],
        MENTION_TABLE: [{
            "id": "manual-1",
            "entity_id": "person-b",
            "source_table": "journal",
            "source_type": "journal",
            "source_id": "j-1",
            "status": "confirmed",
            "origin": "manual",
        }],
    })
    service = MemoryGraphService(supabase)

    first = asyncio.run(service.sync_source_alias_mentions(
        source_table="journal",
        source_type="journal",
        source_id="j-1",
        text="今天见到了老周。",
    ))
    second = asyncio.run(service.sync_source_alias_mentions(
        source_table="journal",
        source_type="journal",
        source_id="j-1",
        text="今天没有写任何名字。",
    ))

    assert first["matched"] == 1
    assert first["linked"] == 1
    assert second["removed"] == 1
    assert [(row["entity_id"], row["origin"]) for row in supabase.tables[MENTION_TABLE]] == [
        ("person-b", "manual")
    ]


def test_graph_document_sync_does_not_treat_structured_index_fields_as_original_text():
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("person-a", "老周")],
        ALIAS_TABLE: [alias("a1", "person-a", "老周")],
        MENTION_TABLE: [],
    })
    document = SimpleNamespace(
        source_table="journal",
        source_type="journal",
        source_id="j-1",
        title="周一随笔",
        body="今天没有提到任何人。",
        tags_json=["老周"],
        entities_json=["老周"],
        content_hash="content-hash",
    )

    result = asyncio.run(MemoryGraphService(supabase).sync_recall_documents([document]))

    assert result["ok"] is True
    assert result["mentions"] == 0
    assert supabase.tables[MENTION_TABLE] == []


def test_graph_recall_returns_direct_sources_before_one_hop_related_sources():
    direct_row = {
        "source_table": "journal",
        "source_type": "journal",
        "source_id": "j-1",
        "chunk_index": 0,
        "deleted_at": None,
        "body": "老周的原件",
    }
    related_row = {
        "source_table": "shenyu_notebook",
        "source_type": "notebook",
        "source_id": "n-1",
        "chunk_index": 0,
        "deleted_at": None,
        "body": "老妹的原件",
    }
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("person-a", "老周"), entity("person-b", "老妹")],
        ALIAS_TABLE: [alias("a1", "person-a", "老周"), alias("a2", "person-b", "老妹")],
        MENTION_TABLE: [
            {
                "id": "m1", "entity_id": "person-a", "source_table": "journal",
                "source_type": "journal", "source_id": "j-1", "status": "confirmed",
            },
            {
                "id": "m2", "entity_id": "person-b", "source_table": "shenyu_notebook",
                "source_type": "notebook", "source_id": "n-1", "status": "confirmed",
            },
        ],
        RELATION_TABLE: [{
            "id": "r1",
            "source_entity_id": "person-a",
            "target_entity_id": "person-b",
            "relation_type": "朋友",
            "status": "confirmed",
            "valid_to": None,
        }],
        RECALL_INDEX_TABLE: [direct_row, related_row],
    })

    rows = asyncio.run(MemoryGraphService(supabase).recall_rows("想起老周"))
    rows_by_id = {row["source_id"]: row for row in rows}

    assert rows_by_id["j-1"]["_graph_reason"] == "direct"
    assert rows_by_id["j-1"]["_graph_score"] == 1.0
    assert rows_by_id["n-1"]["_graph_reason"] == "related"
    assert rows_by_id["n-1"]["_graph_score"] < rows_by_id["j-1"]["_graph_score"]


def test_read_only_recall_trace_explains_direct_and_confirmed_relation_paths():
    direct_row = {
        "source_table": "journal",
        "source_type": "journal",
        "source_id": "j-1",
        "chunk_index": 0,
        "deleted_at": None,
        "title": "和老周见面",
        "body": "今天和老周吃饭，聊了很久。",
        "search_text": "和老周见面 今天和老周吃饭，聊了很久。",
        "search_tokens": ["老周", "吃饭"],
        "tags_json": [],
        "entities_json": [],
        "metadata_json": {},
    }
    related_row = {
        "source_table": "shenyu_notebook",
        "source_type": "notebook",
        "source_id": "n-1",
        "chunk_index": 0,
        "deleted_at": None,
        "title": "老妹的书单",
        "body": "老妹最近想读这本书。",
        "search_text": "老妹的书单 老妹最近想读这本书。",
        "search_tokens": ["老妹", "书"],
        "tags_json": [],
        "entities_json": [],
        "metadata_json": {},
    }
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("person-a", "老周"), entity("person-b", "老妹")],
        ALIAS_TABLE: [alias("a1", "person-a", "老周"), alias("a2", "person-b", "老妹")],
        MENTION_TABLE: [
            {
                "id": "m1", "entity_id": "person-a", "source_table": "journal",
                "source_type": "journal", "source_id": "j-1", "status": "confirmed",
            },
            {
                "id": "m2", "entity_id": "person-b", "source_table": "shenyu_notebook",
                "source_type": "notebook", "source_id": "n-1", "status": "confirmed",
            },
        ],
        RELATION_TABLE: [{
            "id": "r1",
            "source_entity_id": "person-a",
            "target_entity_id": "person-b",
            "relation_type": "闺蜜",
            "status": "confirmed",
            "valid_to": None,
        }],
        RECALL_INDEX_TABLE: [direct_row, related_row],
    })

    result = asyncio.run(
        RecallIndexService(supabase).recall("想起老周", limit=2, auto_sync=False, include_trace=True)
    )

    items = {item["source_id"]: item for item in result["items"]}
    assert items["j-1"]["content"] == "今天和老周吃饭，聊了很久。"
    assert items["j-1"]["recall_match"] == {
        "group": "direct",
        "label": "直达：已确认锚点「老周」",
        "anchor": {"id": "person-a", "name": "老周", "type": "person"},
    }
    assert items["n-1"]["recall_match"]["group"] == "related"
    assert items["n-1"]["recall_match"]["label"] == "关联：老周 - 闺蜜 - 老妹"
    assert items["n-1"]["recall_match"]["path"] == {
        "from": {"id": "person-a", "name": "老周", "type": "person"},
        "relation_type": "闺蜜",
        "to": {"id": "person-b", "name": "老妹", "type": "person"},
    }


def test_create_entity_persists_canonical_name_as_primary_alias():
    supabase = GraphSupabase({ENTITY_TABLE: [], ALIAS_TABLE: []})

    result = asyncio.run(MemoryGraphService(supabase).create_entity(
        entity_type="person",
        canonical_name="李心",
        aliases=["lx", "LX"],
    ))

    assert result["ok"] is True
    aliases = supabase.tables[ALIAS_TABLE]
    assert [row["alias"] for row in aliases] == ["李心", "lx"]
    assert aliases[0]["is_primary"] is True


def test_renaming_entity_keeps_old_name_as_alias_and_promotes_new_name():
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("person-a", "小李")],
        ALIAS_TABLE: [{**alias("a1", "person-a", "小李"), "is_primary": True}],
    })

    result = asyncio.run(MemoryGraphService(supabase).update_entity(
        "person-a",
        {"canonical_name": "李心"},
    ))

    assert result["ok"] is True
    aliases = supabase.tables[ALIAS_TABLE]
    assert {(row["alias"], row["is_primary"]) for row in aliases} == {
        ("小李", False),
        ("李心", True),
    }


def test_update_alias_confirms_suggested_alias_and_validates_status():
    supabase = GraphSupabase({
        ALIAS_TABLE: [{**alias("a1", "person-a", "周周"), "status": "suggested", "confidence": 0.5}],
    })
    service = MemoryGraphService(supabase)

    bad = asyncio.run(service.update_alias("a1", {"status": "nonsense"}))
    missing = asyncio.run(service.update_alias("nope", {"status": "confirmed"}))
    result = asyncio.run(service.update_alias("a1", {"status": "confirmed"}))

    assert bad["ok"] is False
    assert missing["ok"] is False
    assert result["ok"] is True
    row = supabase.tables[ALIAS_TABLE][0]
    assert row["status"] == "confirmed"
    assert row["confidence"] == 1.0


def test_name_candidates_come_from_mem_note_fields_and_skip_existing_aliases():
    supabase = GraphSupabase({
        ALIAS_TABLE: [alias("a1", "person-a", "老周")],
        "shenyu_mem_notes": [
            {"status": "active", "people": ["老周", "阿茉"], "places": ["蛋糕店"], "objects": []},
            {"status": "captured", "people": ["阿茉"], "places": [], "objects": ["风铃"]},
            {"status": "archived", "people": ["旧名字"], "places": [], "objects": []},
        ],
    })

    result = asyncio.run(MemoryGraphService(supabase).name_candidates(limit=10))

    assert result["ok"] is True
    ranked = {(item["name"], item["kind"]): item["count"] for item in result["candidates"]}
    assert ranked[("阿茉", "person")] == 2
    assert ranked[("蛋糕店", "place")] == 1
    assert ranked[("风铃", "object")] == 1
    names = {item["name"] for item in result["candidates"]}
    assert "老周" not in names
    assert "旧名字" not in names


def test_snapshot_reports_last_mentioned_and_recent_activity():
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("e1", "老周"), entity("e2", "阿元")],
        ALIAS_TABLE: [],
        MENTION_TABLE: [
            {
                "id": "m1",
                "entity_id": "e1",
                "source_table": "journal",
                "source_type": "journal",
                "source_id": "j-1",
                "status": "confirmed",
                # Bookkeeping: the link was re-touched in July...
                "created_at": "2026-07-20T08:00:00+00:00",
                "updated_at": "2026-07-30T08:00:00+00:00",
            },
            {
                "id": "m2",
                "entity_id": "e1",
                "source_table": "windowsill",
                "source_type": "windowsill",
                "source_id": "w-1",
                "status": "confirmed",
                "created_at": "2026-07-28T08:00:00+00:00",
            },
        ],
        RELATION_TABLE: [
            {
                "id": "r1",
                "source_entity_id": "e1",
                "target_entity_id": "e2",
                "relation_type": "认得",
                "status": "confirmed",
                "created_at": "2026-07-25T08:00:00+00:00",
                "updated_at": "2026-07-30T08:00:00+00:00",
            },
        ],
        RECALL_INDEX_TABLE: [
            {
                "source_table": "journal",
                "source_id": "j-1",
                "chunk_index": 0,
                # ...but the original diary actually happened in March.
                "event_date": "2026-03-14T00:00:00+00:00",
                "deleted_at": None,
            },
        ],
    })

    result = asyncio.run(MemoryGraphService(supabase).snapshot())

    by_id = {item["id"]: item for item in result["entities"]}
    # July bookkeeping updated_at must not fake warmth: the diary counts as March.
    assert by_id["e1"]["last_mentioned_at"] == "2026-07-28T08:00:00+00:00"
    assert by_id["e2"]["last_mentioned_at"] is None
    recent = result["recent"]
    assert [item["kind"] for item in recent] == ["mention", "relation", "mention"]
    assert recent[0]["entity_name"] == "老周"
    assert recent[0]["source_type"] == "windowsill"
    journal_item = next(item for item in recent if item.get("source_id") == "j-1")
    assert journal_item["at"] == "2026-03-14T00:00:00+00:00"
    relation_item = next(item for item in recent if item["kind"] == "relation")
    assert relation_item["source_name"] == "老周"
    assert relation_item["target_name"] == "阿元"
    assert relation_item["relation_type"] == "认得"


def test_entity_mentions_hydrates_originals_by_event_day():
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("e1", "老周")],
        ALIAS_TABLE: [],
        MENTION_TABLE: [
            {
                "id": "m1",
                "entity_id": "e1",
                "source_table": "journal",
                "source_type": "journal",
                "source_id": "j-1",
                "status": "confirmed",
                "origin": "exact_alias",
                "created_at": "2026-07-20T08:00:00+00:00",
            },
            {
                "id": "m2",
                "entity_id": "e1",
                "source_table": "windowsill",
                "source_type": "windowsill",
                "source_id": "w-1",
                "status": "confirmed",
                "origin": "manual",
                "created_at": "2026-07-28T08:00:00+00:00",
            },
        ],
        RECALL_INDEX_TABLE: [
            {
                "source_table": "journal",
                "source_id": "j-1",
                "chunk_index": 1,
                "title": "三月的信",
                "body": "后来一起去喝了茶。",
                "excerpt": "后来一起去喝了茶。",
                "event_date": "2026-03-14T00:00:00+00:00",
                "deleted_at": None,
            },
            {
                "source_table": "journal",
                "source_id": "j-1",
                "chunk_index": 0,
                "title": "三月的信",
                "body": "那天和老周聊了很久。",
                "excerpt": "那天和老周聊了很久。",
                "event_date": "2026-03-14T00:00:00+00:00",
                "deleted_at": None,
            },
        ],
    })

    result = asyncio.run(MemoryGraphService(supabase).entity_mentions("e1"))

    assert result["ok"] is True
    items = result["items"]
    assert [item["source_id"] for item in items] == ["w-1", "j-1"]
    journal_item = items[1]
    assert journal_item["title"] == "三月的信"
    assert journal_item["excerpt"] == "那天和老周聊了很久。"
    # Full original is hydrated from every chunk, in chunk order.
    assert journal_item["content"] == "那天和老周聊了很久。\n\n后来一起去喝了茶。"
    assert journal_item["content_complete"] is True
    assert journal_item["event_date"] == "2026-03-14T00:00:00+00:00"
    assert journal_item["origin"] == "exact_alias"
    fallback_item = items[0]
    assert fallback_item["event_date"] == "2026-07-28T08:00:00+00:00"
    # A mention whose source is missing from the recall index is marked
    # incomplete instead of pretending an empty text is the whole original.
    assert fallback_item["content"] == ""
    assert fallback_item["content_complete"] is False


def test_name_candidates_links_co_occurring_names_to_their_anchors():
    supabase = GraphSupabase({
        ENTITY_TABLE: [entity("e1", "老周")],
        ALIAS_TABLE: [alias("a1", "e1", "老周")],
        "shenyu_mem_notes": [
            {"status": "active", "people": ["老周", "圆儿"], "places": [], "objects": []},
            {"status": "active", "people": ["圆儿", "牛奶"], "places": [], "objects": []},
        ],
    })

    result = asyncio.run(MemoryGraphService(supabase).name_candidates(limit=10))

    assert result["ok"] is True
    counts = {item["name"]: item["count"] for item in result["candidates"]}
    assert counts["圆儿"] == 2
    assert counts["牛奶"] == 1
    links = {item["name"]: item for item in result["links"]}
    assert links["圆儿"]["entity_id"] == "e1"
    assert links["圆儿"]["shared"] == 1
    assert "牛奶" not in links


def test_candidate_mentions_returns_notes_carrying_the_name():
    supabase = GraphSupabase({
        "shenyu_mem_notes": [
            {
                "id": "n1",
                "content": "圆儿今天带了牛奶来。",
                "mem_type": "关于她的事实",
                "people": ["圆儿", "牛奶"],
                "places": [],
                "objects": [],
                "status": "active",
                "updated_at": "2026-07-28T08:00:00+00:00",
            },
            {
                "id": "n2",
                "content": "和老周散步。",
                "mem_type": "她为我做的事",
                "people": ["老周"],
                "places": [],
                "objects": [],
                "status": "active",
                "updated_at": "2026-07-20T08:00:00+00:00",
            },
        ],
        RECALL_INDEX_TABLE: [
            {
                "source_table": "journal",
                "source_id": "j-1",
                "source_type": "journal",
                "chunk_index": 0,
                "title": "三月的信",
                "body": "圆儿那天也在。她笑了一下午。",
                "excerpt": "圆儿那天也在。",
                "search_text": "三月的信 圆儿那天也在",
                "event_date": "2026-03-14T00:00:00+00:00",
                "deleted_at": None,
            },
            {
                "source_table": "mem_notes",
                "source_id": "n1",
                "source_type": "mem_note",
                "chunk_index": 0,
                "title": "",
                "excerpt": "圆儿今天带了牛奶来。",
                "search_text": "圆儿今天带了牛奶来",
                "event_date": "2026-07-28T08:00:00+00:00",
                "deleted_at": None,
            },
        ],
    })

    result = asyncio.run(MemoryGraphService(supabase).candidate_mentions("圆儿"))

    assert result["ok"] is True
    assert [item["id"] for item in result["items"]] == ["n1"]
    item = result["items"][0]
    assert item["mem_type"] == "关于她的事实"
    assert item["kind"] == "人物"
    assert "牛奶" in item["content"]
    # Cross-source text evidence covers other originals, while the mem note
    # already shown as structured evidence is not duplicated.
    assert [hit["source_id"] for hit in result["text_hits"]] == ["j-1"]
    assert result["text_hits"][0]["title"] == "三月的信"
    # Text hits are hydrated with the complete original for the reading overlay.
    assert result["text_hits"][0]["content"] == "圆儿那天也在。她笑了一下午。"
    assert result["text_hits"][0]["content_complete"] is True
    empty = asyncio.run(MemoryGraphService(supabase).candidate_mentions("不存在的人"))
    assert empty["items"] == []
    assert empty["text_hits"] == []
