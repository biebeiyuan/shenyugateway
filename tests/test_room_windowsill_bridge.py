from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.recall import RecallIndexService
from shenyu_gateway.room_tools import execute_room_tool, sync_legacy_room_scribbles
from shenyu_gateway.store import GatewayStore

from .fake_postgrest import project_select


class FakeSupabase:
    def __init__(self):
        self.windowsill_rows: list[dict] = []
        self.recall_rows: list[dict] = []
        self.inserts: list[tuple[str, dict]] = []
        self.upserts: list[tuple[str, list[dict], str | None]] = []

    async def insert(self, table, data):
        self.inserts.append((table, dict(data)))
        assert table == "windowsill"
        row = {
            "id": f"window-{len(self.windowsill_rows) + 1}",
            **data,
            "created_at": "2026-08-14T08:00:00+00:00",
        }
        self.windowsill_rows.append(row)
        return row

    async def upsert(self, table, data, on_conflict=None):
        rows = data if isinstance(data, list) else [data]
        copied = [dict(row) for row in rows]
        self.upserts.append((table, copied, on_conflict))
        if table == "windowsill":
            stored = []
            for row in copied:
                existing = next(
                    (item for item in self.windowsill_rows if item["id"] == row["id"]),
                    None,
                )
                if existing:
                    existing.update(row)
                    stored.append(existing)
                else:
                    self.windowsill_rows.append(row)
                    stored.append(row)
            return stored
        if table == "shenyu_recall_index":
            for row in copied:
                key = (row["source_table"], row["source_id"], row["chunk_index"])
                existing = next(
                    (
                        item
                        for item in self.recall_rows
                        if (item["source_table"], item["source_id"], item["chunk_index"]) == key
                    ),
                    None,
                )
                if existing:
                    existing.update(row)
                else:
                    self.recall_rows.append(row)
            return copied
        return copied

    async def query(self, table, params=None):
        params = params or {}
        if table == "windowsill":
            origin = str(params.get("origin") or "")
            rows = list(self.windowsill_rows)
            if origin.startswith("eq."):
                rows = [row for row in rows if row.get("origin", "normal") == origin[3:]]
            return project_select(rows[: int(params.get("limit", len(rows)))], params)
        if table == "shenyu_recall_index":
            return project_select(self.recall_rows, params)
        return []


async def _skip_graph_sync(_self, _docs):
    return None


def _cfg():
    return SimpleNamespace(enable_recall_embeddings=False)


def test_room_scribble_writes_canonical_windowsill_and_recall(monkeypatch, tmp_path):
    monkeypatch.setattr(RecallIndexService, "_sync_graph_documents_fail_soft", _skip_graph_sync)
    store = GatewayStore(str(tmp_path / "gateway.db"))
    supabase = FakeSupabase()

    written = asyncio.run(
        execute_room_tool(
            "room_scribble",
            {"action": "write", "content": "海风把纸角掀起来了一点。"},
            store=store,
            cfg=_cfg(),
            supabase_client=supabase,
        )
    )

    assert written == {"ok": True, "id": "window-1", "message": "写下了。"}
    assert store.recent_room_scribbles() == []
    assert supabase.inserts == [
        (
            "windowsill",
            {"content": "海风把纸角掀起来了一点。", "title": "", "mood": "", "origin": "room"},
        )
    ]
    assert supabase.recall_rows[0]["source_table"] == "windowsill"
    assert supabase.recall_rows[0]["metadata_json"] == {"origin": "room"}
    recall_item = RecallIndexService(supabase)._public_item(
        supabase.recall_rows[0],
        {("windowsill", "window-1"): [supabase.recall_rows[0]]},
    )
    assert recall_item["origin"] == "写自房间"

    supabase.windowsill_rows.append(
        {
            "id": "window-normal",
            "content": "这句是从普通窗台写下的。",
            "title": "",
            "mood": "",
            "origin": "normal",
            "created_at": "2026-08-14T07:00:00+00:00",
        }
    )

    room_read = asyncio.run(
        execute_room_tool(
            "room_scribble",
            {"action": "read"},
            store=store,
            cfg=_cfg(),
            supabase_client=supabase,
        )
    )
    normal_list = asyncio.run(
        GatewayToolService(runtime_config=_cfg(), supabase=supabase, store=store).windowsill_list()
    )

    assert room_read["scribbles"] == [
        {"content": "海风把纸角掀起来了一点。", "created_at": "2026-08-14T08:00:00+00:00"}
    ]
    assert [item["content"] for item in room_read["scribbles"]] == ["海风把纸角掀起来了一点。"]
    assert {row["content"] for row in normal_list["data"]} == {
        "海风把纸角掀起来了一点。",
        "这句是从普通窗台写下的。",
    }
    assert {row["origin"] for row in normal_list["data"]} == {"normal", "room"}


def test_legacy_room_scribbles_migrate_once_with_room_origin(monkeypatch, tmp_path):
    monkeypatch.setattr(RecallIndexService, "_sync_graph_documents_fail_soft", _skip_graph_sync)
    store = GatewayStore(str(tmp_path / "gateway.db"))
    legacy_id = store.add_room_scribble("这句是在旧房间本子里写下的。")
    legacy = store.recent_room_scribbles(limit=1)[0]
    supabase = FakeSupabase()

    first = asyncio.run(
        sync_legacy_room_scribbles(store=store, cfg=_cfg(), supabase_client=supabase)
    )
    second = asyncio.run(
        sync_legacy_room_scribbles(store=store, cfg=_cfg(), supabase_client=supabase)
    )

    assert first == {"ok": True, "migrated": 1, "errors": 0}
    assert second == {"ok": True, "migrated": 0}
    assert [row["content"] for row in supabase.windowsill_rows] == ["这句是在旧房间本子里写下的。"]
    migrated = supabase.windowsill_rows[0]
    assert migrated["id"] != legacy_id
    assert migrated["origin"] == "room"
    assert migrated["created_at"] == legacy["created_at"]
    assert store.unmigrated_room_scribbles() == []
    assert supabase.recall_rows[0]["source_id"] == migrated["id"]
