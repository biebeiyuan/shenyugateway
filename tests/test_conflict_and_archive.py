from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime
from pathlib import Path

from shenyu_gateway.archive_routes import ArchiveRouteDeps, build_archive_router
from shenyu_gateway.chat_archive import ChatArchiveService, derive_thread
from scripts.backfill_chat_archive import _candidate_rows
from shenyu_gateway.conflict_books import ConflictBookService, render_conflict_shelf
from shenyu_gateway.store import GatewayStore


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.queries: list[tuple[str, dict]] = []
        self._next_id = 0

    def _table(self, name: str) -> list[dict]:
        return self.tables.setdefault(name, [])

    def _gen_id(self) -> str:
        self._next_id += 1
        return f"fake-{self._next_id}"

    def _filter_compare(self, row: dict, key: str, op: str, raw_value: str) -> bool:
        value = row.get(key)
        if key == "event_at" and value:
            left = datetime.fromisoformat(str(value))
            right = datetime.fromisoformat(raw_value)
            return left >= right if op == "gte" else left < right
        text = str(value or "")
        return text >= raw_value if op == "gte" else text < raw_value

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
        self.queries.append((table, dict(params)))
        rows = list(self._table(table))
        and_clause = str(params.get("and") or "")
        for key, value in params.items():
            if key in {"select", "order", "limit", "offset", "and"}:
                continue
            if isinstance(value, str) and value.startswith("eq."):
                rows = [r for r in rows if str(r.get(key)) == value[3:]]
            elif isinstance(value, str) and value == "is.null":
                rows = [r for r in rows if r.get(key) is None]
            elif isinstance(value, str) and value.startswith("gte."):
                rows = [r for r in rows if self._filter_compare(r, key, "gte", value[4:])]
            elif isinstance(value, str) and value.startswith("lt."):
                rows = [r for r in rows if self._filter_compare(r, key, "lt", value[3:])]
        if and_clause.startswith("(event_at.lt.") and and_clause.endswith(")"):
            before = and_clause[len("(event_at.lt.") : -1]
            rows = [r for r in rows if self._filter_compare(r, "event_at", "lt", before)]
        order = str(params.get("order") or "").split(",", 1)[0]
        if order:
            field, _, direction = order.partition(".")
            rows.sort(key=lambda r: str(r.get(field) or ""), reverse=direction == "desc")
        offset = int(params.get("offset") or 0)
        limit = params.get("limit")
        if limit is not None:
            rows = rows[offset : offset + int(limit)]
        elif offset:
            rows = rows[offset:]
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
    chat_archive_seen_retention = 10000


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

        listed = await service.list_books()
        assert listed["ok"], listed
        assert listed["books"][0]["title"] == "改了标题"
        assert supabase.queries[-1][1]["select"].split(",")[0] == "title"

        # shelf renders titles only, never text
        shelf = render_conflict_shelf([read["book"]])
        assert "改了标题" in shelf
        assert "原文冻结内容" not in shelf
        assert "翻过 1 次" in shelf

    asyncio.run(run())


def test_conflict_book_can_read_and_annotate_by_exact_title():
    async def run():
        supabase = FakeSupabase()
        service = ConflictBookService(supabase)

        first = await service.create_book(title="唯一书名", original_text="第一份原文")
        assert first["ok"], first
        read = await service.read_book(title="唯一书名")
        assert read["ok"], read
        assert read["book"]["original_text"] == "第一份原文"
        assert supabase.tables["shenyu_conflict_reads"][0]["book_id"] == first["book"]["id"]

        note = await service.annotate_book(title="唯一书名", content="按书名落了一笔")
        assert note["ok"], note
        assert supabase.tables["shenyu_conflict_annotations"][0]["book_id"] == first["book"]["id"]

        duplicate = await service.create_book(title="唯一书名", original_text="第二份原文")
        assert duplicate["ok"], duplicate
        ambiguous = await service.read_book(title="唯一书名")
        assert ambiguous == {"ok": False, "error": "title is ambiguous; use a unique title or book_id"}

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


def test_chat_archive_uses_client_attachment_time():
    async def run():
        supabase = FakeSupabase()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(str(Path(tmp) / "test.db"))
            service = ChatArchiveService(store, supabase, Cfg())

            window = [
                {
                    "role": "user",
                    "content": '你好 <attachment id="message_insert_extra_bundle_1" filename="Time:21:08 15/2026/5" type="text/plain">ignored</attachment>',
                },
                {"role": "assistant", "content": "我在。"},
            ]
            result = await service.archive_window(
                session_tag="5.15", client_name="operit", messages=window, is_hisense=False
            )
            assert result["archived"] == 2, result
            rows = supabase.tables["shenyu_chat_archive"]
            assert rows[0]["event_at"] == "2026-05-15T13:08:00+00:00"
            assert rows[1]["event_at"] == "2026-05-15T13:08:00+00:00"
            assert "<attachment" not in rows[0]["content"]

    asyncio.run(run())


def test_chat_archive_backfill_uses_client_attachment_time():
    rows = _candidate_rows(
        tag="5.15",
        client_name="operit",
        messages=[
            {
                "role": "user",
                "content": '你好 <attachment id="message_insert_extra_bundle_1" filename="Time:21:08 15/2026/5" type="text/plain">ignored</attachment>',
            },
            {"role": "assistant", "content": "我在。"},
        ],
        created_at="2026-06-14T10:00:00+00:00",
        is_hisense=False,
        existing=set(),
    )
    assert [row["event_at"] for row in rows] == [
        "2026-05-15T13:08:00+00:00",
        "2026-05-15T13:08:00+00:00",
    ]


def test_chat_archive_skips_numbered_transcript_messages():
    async def run():
        supabase = FakeSupabase()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(str(Path(tmp) / "test.db"))
            service = ChatArchiveService(store, supabase, Cfg())

            window = [
                {"role": "user", "content": "#1: 予予🥺你看到了吗"},
                {"role": "assistant", "content": "#2: 看到了。"},
            ]
            result = await service.archive_window(
                session_tag="5.15", client_name="operit", messages=window, is_hisense=False
            )
            assert result["archived"] == 0, result
            assert supabase.tables.get("shenyu_chat_archive", []) == []

    asyncio.run(run())


def test_derive_thread():
    assert derive_thread("default", False) == "main"
    assert derive_thread("", False) == "main"
    assert derive_thread("tech", False) == "tech"
    assert derive_thread("anything", True) == "hisense"


def test_archive_routes_page_threads_and_days():
    async def run():
        supabase = FakeSupabase()
        for idx in range(1205):
            await supabase.insert(
                "shenyu_chat_archive",
                {
                    "thread": "5.15",
                    "event_at": "2026-06-14T00:00:00+00:00",
                    "deleted_at": None,
                },
            )
        router = build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda: supabase))
        endpoints = {route.path: route.endpoint for route in router.routes}
        threads = await endpoints["/api/archive/threads"]()
        days = await endpoints["/api/archive/days"](thread="5.15", month="2026-06")
        assert threads["threads"] == [{"thread": "5.15", "count": 1205}]
        assert days["days"] == [{"date": "2026-06-14", "count": 1205}]

    asyncio.run(run())


def test_archive_routes_use_cst_day_boundaries():
    async def run():
        supabase = FakeSupabase()
        rows = [
            ("before", "2026-06-13T15:59:59+00:00"),
            ("inside-early", "2026-06-13T16:00:00+00:00"),
            ("inside-late", "2026-06-14T15:59:59+00:00"),
            ("after", "2026-06-14T16:00:00+00:00"),
        ]
        for content, event_at in rows:
            await supabase.insert(
                "shenyu_chat_archive",
                {
                    "thread": "main",
                    "session_tag": "default",
                    "role": "user",
                    "content": content,
                    "event_at": event_at,
                    "deleted_at": None,
                },
            )
        router = build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda: supabase))
        endpoints = {route.path: route.endpoint for route in router.routes}

        days = await endpoints["/api/archive/days"](thread="main", month="2026-06")
        messages = await endpoints["/api/archive/messages"](thread="main", date="2026-06-14")

        assert days["days"] == [
            {"date": "2026-06-13", "count": 1},
            {"date": "2026-06-14", "count": 2},
            {"date": "2026-06-15", "count": 1},
        ]
        assert [row["content"] for row in messages["messages"]] == ["inside-early", "inside-late"]

    asyncio.run(run())


if __name__ == "__main__":
    test_conflict_book_invariants()
    test_chat_archive_dedup()
    test_chat_archive_uses_client_attachment_time()
    test_chat_archive_backfill_uses_client_attachment_time()
    test_chat_archive_skips_numbered_transcript_messages()
    test_derive_thread()
    test_archive_routes_page_threads_and_days()
    test_archive_routes_use_cst_day_boundaries()
    print("ALL_OK")
