from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.resident_books import ResidentBooksService, render_bookshelf_overview

from .fake_postgrest import apply_order, project_select


ROOT = Path(__file__).resolve().parent.parent


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.counter = 0

    def _table(self, name: str) -> list[dict]:
        return self.tables.setdefault(name, [])

    def _id(self) -> str:
        self.counter += 1
        return f"fake-{self.counter}"

    async def insert(self, table: str, data: dict) -> dict:
        row = dict(data)
        row.setdefault("id", self._id())
        row.setdefault("created_at", "2026-07-19T12:00:00+00:00")
        row.setdefault("updated_at", row["created_at"])
        self._table(table).append(row)
        return row

    async def query(self, table: str, params=None) -> list[dict]:
        params = params or {}
        rows = list(self._table(table))
        for key, value in params.items():
            if key in {"select", "order", "limit", "offset"}:
                continue
            if isinstance(value, str) and value.startswith("eq."):
                rows = [row for row in rows if str(row.get(key)) == value[3:]]
        rows = apply_order(rows, params)
        if params.get("limit") is not None:
            rows = rows[: int(params["limit"])]
        return project_select(rows, params)

    async def update(self, table: str, match, data: dict) -> list[dict]:
        updated = []
        for row in self._table(table):
            if all(str(row.get(key)) == str(value) for key, value in (match or {}).items()):
                row.update(data)
                updated.append(row)
        return updated


def test_overview_includes_generated_home_identity_and_origin_books():
    async def run():
        supabase = FakeSupabase()
        await supabase.insert(
            "shenyu_books",
            {
                "slug": "identity",
                "title": "我是谁",
                "kind": "living",
                "status": "active",
                "body": "我还在写。",
                "revision": 2,
                "updated_by": "沈予",
            },
        )
        await supabase.insert(
            "shenyu_conflict_books",
            {
                "title": "旧书",
                "status": "open",
                "read_count": 0,
                "deleted_at": None,
            },
        )
        result = await ResidentBooksService(supabase, root=ROOT).overview()
        assert result["ok"]
        assert result["home"]["current_week"]
        assert result["identity"]["slug"] == "identity"
        assert result["identity"]["revision"] == 2
        assert result["origin_books"][0]["title"] == "旧书"
        rendered = render_bookshelf_overview(result)
        assert "## 书架一览" in rendered
        assert "- 家现在：本周" in rendered
        assert "- 我是谁：第 2 版，最后由沈予修改" in rendered
        assert "- 来历书：1 本——《旧书》" in rendered

    asyncio.run(run())


def test_books_tool_lists_clean_shelf_locators_and_guides_origin_read():
    async def run():
        supabase = FakeSupabase()
        await supabase.insert(
            "shenyu_books",
            {
                "slug": "identity",
                "title": "我是谁",
                "kind": "living",
                "status": "active",
                "body": "这段正文不能出现在 list 里。",
                "revision": 3,
                "updated_by": "沈予",
            },
        )
        origin = await supabase.insert(
            "shenyu_conflict_books",
            {
                "title": "第一眼其实是嫌弃",
                "original_text": "这段冻结原文也不能出现在 list 里。",
                "status": "open",
                "read_count": 2,
                "deleted_at": None,
            },
        )
        service = GatewayToolService(runtime_config=None, supabase=supabase, store=None)
        listed = await service.books(action="list")
        missing_locator = await service.books(action="read", book="origin")
        return listed, missing_locator, origin

    listed, missing_locator, origin = asyncio.run(run())

    assert listed["ok"] is True
    assert listed["count"] == 3
    assert listed["home"]["book"] == "home"
    assert listed["identity"] == {
        "book": "identity",
        "title": "我是谁",
        "kind": "living",
        "revision": 3,
        "status": "active",
        "updated_at": "2026-07-19T12:00:00+00:00",
        "updated_by": "沈予",
    }
    assert listed["origin_books"] == [
        {
            "book": "origin",
            "book_id": origin["id"],
            "title": "第一眼其实是嫌弃",
            "kind": "origin",
            "status": "open",
            "read_count": 2,
            "last_read_at": None,
            "created_at": "2026-07-19T12:00:00+00:00",
        }
    ]
    assert "body" not in listed["identity"]
    assert "original_text" not in listed["origin_books"][0]
    assert missing_locator["error_kind"] == "validation"
    assert "action=list" in missing_locator["error"]
    assert "book_id" in missing_locator["error"]


def test_living_book_write_keeps_revision_and_rejects_stale_write():
    async def run():
        supabase = FakeSupabase()
        service = ResidentBooksService(supabase, root=ROOT)
        first = await service.write(book="identity", content="第一版", summary="建立自述", actor="圆圆")
        assert first["ok"]
        assert first["book"]["revision"] == 1
        second = await service.write(
            book="identity",
            content="第二版",
            expected_revision=1,
            summary="补充自述",
            actor="沈予",
        )
        assert second["ok"]
        assert second["book"]["revision"] == 2
        stale = await service.write(book="identity", content="旧写入", expected_revision=1)
        assert stale["error_kind"] == "conflict"
        history = await service.read(book="identity", view="history")
        assert [row["revision"] for row in history["revisions"]] == [2, 1]
        assert history["book"]["body"] == "第二版"

    asyncio.run(run())


def test_home_is_generated_read_only_and_keeps_append_only_annotations():
    async def run():
        supabase = FakeSupabase()
        service = ResidentBooksService(supabase, root=ROOT)
        rejected = await service.write(book="home", content="不应该出现的手写家况")
        assert rejected["error_kind"] == "read_only"
        note = await service.annotate(book="home", content="这条由圆圆补充。", actor="圆圆")
        assert note["ok"]
        current = await service.read(book="家现在")
        assert current["kind"] == "snapshot"
        assert current["snapshot"]["live"]["commit"]
        assert "body" not in current["book"]
        assert "revision" not in current["book"]
        assert current["book"]["annotations"][0]["actor"] == "圆圆"

        origin = await service.annotate(book="来历书", title="不存在", content="批注")
        assert not origin["ok"]

    asyncio.run(run())


def test_overview_keeps_origin_books_when_identity_table_is_temporarily_unavailable():
    class OriginOnlySupabase(FakeSupabase):
        async def query(self, table: str, params=None):
            if table == "shenyu_books":
                raise RuntimeError("relation shenyu_books does not exist")
            return await super().query(table, params)

    async def run():
        supabase = OriginOnlySupabase()
        await supabase.insert("shenyu_conflict_books", {"title": "旧书", "status": "open", "deleted_at": None})
        result = await ResidentBooksService(supabase, root=ROOT).overview()
        assert result["ok"]
        assert result["origin_books"][0]["title"] == "旧书"
        assert any("Identity book is unavailable" in warning for warning in result["warnings"])

    asyncio.run(run())


def test_home_snapshot_still_reads_without_supabase():
    async def run():
        result = await ResidentBooksService(None, root=ROOT).read(book="home")
        assert result["ok"]
        assert result["kind"] == "snapshot"
        assert result["snapshot"]["components"]
        assert result["book"]["annotations"] == []

    asyncio.run(run())
