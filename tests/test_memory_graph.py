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
            if text.startswith("eq."):
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
