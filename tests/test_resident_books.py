from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from shenyu_gateway.resident_books import ResidentBooksService


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
        order = str(params.get("order") or "")
        if order:
            field, _, direction = order.partition(".")
            rows.sort(key=lambda row: str(row.get(field) or ""), reverse=direction == "desc")
        if params.get("limit") is not None:
            rows = rows[: int(params["limit"])]
        return rows

    async def update(self, table: str, match, data: dict) -> list[dict]:
        updated = []
        for row in self._table(table):
            if all(str(row.get(key)) == str(value) for key, value in (match or {}).items()):
                row.update(data)
                updated.append(row)
        return updated


def test_shelf_includes_home_snapshot_living_books_and_origin_books():
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
        result = await ResidentBooksService(supabase, root=ROOT).shelf()
        assert result["ok"]
        assert result["home"]["live"]["commit"]
        assert {book["kind"] for book in result["books"]} == {"living", "origin"}
        assert any(book.get("slug") == "identity" for book in result["books"])
        assert any(book.get("title") == "旧书" for book in result["books"])

    asyncio.run(run())


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


def test_living_annotation_and_origin_alias_use_separate_rules():
    async def run():
        supabase = FakeSupabase()
        service = ResidentBooksService(supabase, root=ROOT)
        await service.write(book="home", content="家现在有一层活文档。")
        note = await service.annotate(book="home", content="这条由圆圆补充。", actor="圆圆")
        assert note["ok"]
        current = await service.read(book="家现在")
        assert current["book"]["annotations"][0]["actor"] == "圆圆"

        origin = await service.annotate(book="来历书", title="不存在", content="批注")
        assert not origin["ok"]

    asyncio.run(run())


def test_shelf_keeps_origin_books_when_living_table_is_temporarily_unavailable():
    class OriginOnlySupabase(FakeSupabase):
        async def query(self, table: str, params=None):
            if table == "shenyu_books":
                raise RuntimeError("relation shenyu_books does not exist")
            return await super().query(table, params)

    async def run():
        supabase = OriginOnlySupabase()
        await supabase.insert("shenyu_conflict_books", {"title": "旧书", "status": "open", "deleted_at": None})
        result = await ResidentBooksService(supabase, root=ROOT).shelf()
        assert result["ok"]
        assert any(book.get("title") == "旧书" for book in result["books"])
        assert any("Living books are unavailable" in warning for warning in result["warnings"])

    asyncio.run(run())
