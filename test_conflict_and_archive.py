from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from shenyu_gateway.chat_archive import ChatArchiveService, derive_thread
from shenyu_gateway.conflict_books import ConflictBookService, render_conflict_shelf
from shenyu_gateway.store import GatewayStore


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self._next_id = 0

    def _table(self, name: str) -> list[dict]:
        return self.tables.setdefault(name, [])

    def _gen_id(self) -> str:
        self._next_id += 1
        return f"fake-{self._next_id}"

    async def insert(self, table: str, data: dict) -> dict:
        row = dict(data)
        row.setdefault("id", self._gen_id())
        row.setdefault("created_at", "2026-06-13T00:00:00+00:00")
        self._table(table).append(row)
        return row

    async def insert_many(self, table: str, rows: list[dict]) -> list:
        return [await self.insert(table, row) for row in rows]

    async def query(self, table: str, params=None) -> list:
        params = params or {}
        rows = list(self._table(table))
        for key, value in params.items():
            if key in {"select", "order", "limit", "and"}:
                continue
            if isinstance(value, str) and value.startswith("eq."):
                rows = [r for r in rows if str(r.get(key)) == value[3:]]
            elif isinstance(value, str) and value == "is.null":
                rows = [r for r in rows if r.get(key) is None]
        return rows

    async def update(self, table: str, match, data: dict) -> list:
        rows = self._table(table)
        updated = []
        for row in rows:
            ok = True
            for key, value in (match or {}).items():
                if isinstance(value, str) and value.startswith("eq."):
                    ok = ok and str(row.get(key)) == value[3:]
                elif isinstance(value, str) and value == "is.null":
                    ok = ok and row.get(key) is None
                elif isinstance(value, str) and value.startswith("in.("):
                    ok = ok and str(row.get(key)) in value[4:-1].split(",")
                else:
                    ok = ok and str(row.get(key)) == str(value)
            if ok:
                row.update(data)
                updated.append(row)
        return updated


class Cfg:
    enable_chat_archive = True


def test_conflict_book_invariants():
    async def run():
        supabase = FakeSupabase()
        service = ConflictBookService(supabase)

        created = await service.create_book(title="第一次掰扯", original_text="原文冻结内容")
        assert created["ok"], created
        book_id = created["book"]["id"]

        # original_text must be silently dropped from updates
        patched = await service.update_book(book_id, {"title": "改了标题", "original_text": "篡改！"})
        assert patched["ok"], patched
        stored = supabase.tables["shenyu_conflict_books"][0]
        assert stored["original_text"] == "原文冻结内容"
        assert stored["title"] == "改了标题"

        # a patch with only original_text must be rejected outright
        rejected = await service.update_book(book_id, {"original_text": "再次篡改"})
        assert not rejected["ok"]

        # annotation appends; service has no update/delete methods for annotations
        note = await service.annotate_book(book_id, "半年后的我看这段，其实她当时是对的")
        assert note["ok"], note
        assert not hasattr(service, "update_annotation")
        assert not hasattr(service, "delete_annotation")

        # reading logs a read and bumps read_count
        before = int(stored.get("read_count") or 0)
        read = await service.read_book(book_id)
        assert read["ok"], read
        assert read["book"]["read_count"] == before + 1
        assert len(supabase.tables["shenyu_conflict_reads"]) == 1
        assert read["book"]["annotations"][0]["content"].startswith("半年后")

        # shelf renders titles only, never text
        shelf = render_conflict_shelf([read["book"]])
        assert "改了标题" in shelf
        assert "原文冻结内容" not in shelf
        assert "翻过 1 次" in shelf

    asyncio.run(run())


def test_chat_archive_dedup():
    async def run():
        supabase = FakeSupabase()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(str(Path(tmp) / "test.db"))
            service = ChatArchiveService(store, supabase, Cfg())

            window1 = [
                {"role": "user", "content": "今天有点累"},
                {"role": "assistant", "content": "那就早点休息，我陪着你"},
            ]
            result1 = await service.archive_window(
                session_tag="default", client_name="operit", messages=window1, is_hisense=False
            )
            assert result1["archived"] == 2, result1

            # same window resent (sliding window) plus one new message
            window2 = window1 + [{"role": "user", "content": "嗯，晚安"}]
            result2 = await service.archive_window(
                session_tag="default", client_name="operit", messages=window2, is_hisense=False
            )
            assert result2["archived"] == 1, result2

            # third resend archives nothing
            result3 = await service.archive_window(
                session_tag="default", client_name="operit", messages=window2, is_hisense=False
            )
            assert result3["archived"] == 0, result3

            rows = supabase.tables["shenyu_chat_archive"]
            assert len(rows) == 3
            assert all(row["thread"] == "main" for row in rows)

    asyncio.run(run())


def test_derive_thread():
    assert derive_thread("default", False) == "main"
    assert derive_thread("", False) == "main"
    assert derive_thread("tech", False) == "tech"
    assert derive_thread("anything", True) == "hisense"


if __name__ == "__main__":
    test_conflict_book_invariants()
    test_chat_archive_dedup()
    test_derive_thread()
    print("ALL_OK")
