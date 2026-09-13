from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime
from pathlib import Path

from shenyu_gateway.archive_routes import (
    ArchiveRouteDeps,
    ResidentBookAnnotation,
    ResidentBookWrite,
    build_archive_router,
)
from shenyu_gateway.chat_archive import ChatArchiveService, derive_thread
from scripts.backfill_chat_archive import _candidate_rows
from shenyu_gateway.conflict_books import ConflictBookService, render_conflict_shelf
from shenyu_gateway.store import GatewayStore

from .fake_postgrest import apply_order, project_select


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
            # raw_value might have been URL-decoded (+ became space), fix it
            raw_value = raw_value.replace(" ", "+")

            # For event_at comparison, convert to datetime objects for proper timezone-aware comparison
            from datetime import datetime, timezone as tz
            try:
                left = datetime.fromisoformat(str(value))
                right = datetime.fromisoformat(raw_value)
            except ValueError:
                # Fallback to string comparison with normalization if parsing fails
                def normalize(ts_str):
                    if '+' in ts_str:
                        return ts_str.split('+')[0]
                    if ts_str.endswith('Z'):
                        return ts_str[:-1]
                    return ts_str
                left_normalized = normalize(str(value))
                right_normalized = normalize(raw_value)
                if op == "gte":
                    return left_normalized >= right_normalized
                if op == "lte":
                    return left_normalized <= right_normalized
                if op == "gt":
                    return left_normalized > right_normalized
                return left_normalized < right_normalized

            # Ensure both are offset-aware for comparison
            if left.tzinfo is None:
                left = left.replace(tzinfo=tz.utc)
            if right.tzinfo is None:
                right = right.replace(tzinfo=tz.utc)

            if op == "gte":
                return left >= right
            if op == "lte":
                return left <= right
            if op == "gt":
                return left > right
            return left < right

        text = str(value or "")
        if op == "gte":
            return text >= raw_value
        if op == "lte":
            return text <= raw_value
        if op == "gt":
            return text > raw_value
        return text < raw_value

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
            elif isinstance(value, str) and value.startswith("lte."):
                rows = [r for r in rows if self._filter_compare(r, key, "lte", value[4:])]
            elif isinstance(value, str) and value.startswith("gt."):
                rows = [r for r in rows if self._filter_compare(r, key, "gt", value[3:])]
            elif isinstance(value, str) and value.startswith("lt."):
                rows = [r for r in rows if self._filter_compare(r, key, "lt", value[3:])]
            elif isinstance(value, str) and value.startswith("ilike."):
                pattern = value[6:]
                # Handle quoted patterns: ilike."*needle*" -> extract content inside quotes
                if pattern.startswith('"') and pattern.endswith('"'):
                    pattern = pattern[1:-1]
                    # Unescape doubled quotes
                    pattern = pattern.replace('""', '"')
                # Strip wildcards and escaped wildcards for matching
                needle = pattern.strip("*").replace("\\*", "*")
                rows = [r for r in rows if needle.lower() in str(r.get(key) or "").lower()]
        if and_clause.startswith("(event_at.lt.") and and_clause.endswith(")"):
            before = and_clause[len("(event_at.lt.") : -1]
            rows = [r for r in rows if self._filter_compare(r, "event_at", "lt", before)]
        rows = apply_order(rows, params)
        offset = int(params.get("offset") or 0)
        limit = params.get("limit")
        if limit is not None:
            rows = rows[offset : offset + int(limit)]
        elif offset:
            rows = rows[offset:]
        return project_select(rows, params)

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
        listed_fields = supabase.queries[-1][1]["select"].split(",")
        assert listed_fields[:2] == ["id", "title"]
        assert "original_text" not in listed_fields

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
                session_tag="default", client_name="operit", messages=window1
            )
            assert result1["archived"] == 2, result1

            # same window resent (sliding window) plus one new message
            window2 = window1 + [{"role": "user", "content": "嗯，晚安"}]
            result2 = await service.archive_window(
                session_tag="default", client_name="operit", messages=window2
            )
            assert result2["archived"] == 1, result2

            # third resend archives nothing
            result3 = await service.archive_window(
                session_tag="default", client_name="operit", messages=window2
            )
            assert result3["archived"] == 0, result3

            rows = supabase.tables["shenyu_chat_archive"]
            assert len(rows) == 3
            assert all(row["thread"] == "main" for row in rows)

    asyncio.run(run())


def test_chat_archive_keeps_assistant_body_but_drops_private_echo():
    async def run():
        supabase = FakeSupabase()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(str(Path(tmp) / "test.db"))
            service = ChatArchiveService(store, supabase, Cfg())
            result = await service.archive_window(
                session_tag="default",
                client_name="shenyu-pwa",
                messages=[
                    {"role": "user", "content": "你还好吗"},
                    {"role": "assistant", "content": "[回响]有一点怕。[/回响]我在。"},
                ],
            )

            assert result["archived"] == 2
            rows = supabase.tables["shenyu_chat_archive"]
            assert rows[-1]["content"] == "我在。"
            assert "有一点怕" not in rows[-1]["content"]

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
                session_tag="5.15", client_name="operit", messages=window
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
                session_tag="5.15", client_name="operit", messages=window
            )
            assert result["archived"] == 0, result
            assert supabase.tables.get("shenyu_chat_archive", []) == []

    asyncio.run(run())


def test_chat_archive_strips_pwa_status_suffix_from_content():
    async def run():
        supabase = FakeSupabase()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(str(Path(tmp) / "test.db"))
            service = ChatArchiveService(store, supabase, Cfg())

            window = [
                {
                    "role": "user",
                    "content": "予予晚安【26/07 周日 23:40 · 第140天 · 🔋64% · 邵阳 多云 24℃】",
                },
                {"role": "assistant", "content": "晚安，圆圆。"},
            ]
            result = await service.archive_window(
                session_tag="5.15", client_name="shenyu-pwa", messages=window
            )
            assert result["archived"] == 2, result
            rows = supabase.tables["shenyu_chat_archive"]
            assert rows[0]["content"] == "予予晚安"
            assert "邵阳" not in rows[0]["content"]
            assert rows[1]["content"] == "晚安，圆圆。"

    asyncio.run(run())


def test_chat_archive_uses_pwa_suffix_time_and_replay_order():
    async def run():
        supabase = FakeSupabase()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(str(Path(tmp) / "test.db"))
            service = ChatArchiveService(store, supabase, Cfg())

            # 第140天 = 2026-03-09 + 139 天 = 2026-07-26（北京时间）
            window = [
                {"role": "user", "content": "在看星星【26/07 周日 22:24 · 第140天 · 🔋52%】"},
                {"role": "assistant", "content": "西274°，是大角星。"},
                {"role": "assistant", "content": "认对了。"},
                {"role": "user", "content": "予予晚安【26/07 周日 23:53 · 第140天 · 🔋84%⚡】"},
            ]
            result = await service.archive_window(
                session_tag="pwa-abc123", client_name="shenyu-pwa", messages=window
            )
            assert result["archived"] == 4, result
            rows = supabase.tables["shenyu_chat_archive"]
            # 用户消息取后缀里的真实时间，助手回复继承上一条用户消息的时间
            assert rows[0]["event_at"] == "2026-07-26T14:24:00+00:00"
            assert rows[1]["event_at"] == "2026-07-26T14:24:00+00:00"
            assert rows[2]["event_at"] == "2026-07-26T14:24:00+00:00"
            assert rows[3]["event_at"] == "2026-07-26T15:53:00+00:00"
            # archived_at 批内逐行递增：同一继承时间下仍能按窗口顺序回放
            archived = [row["archived_at"] for row in rows]
            assert archived == sorted(archived) and len(set(archived)) == 4

    asyncio.run(run())


def test_chat_archive_assistant_quote_does_not_move_clock():
    async def run():
        supabase = FakeSupabase()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(str(Path(tmp) / "test.db"))
            service = ChatArchiveService(store, supabase, Cfg())

            window = [
                {"role": "user", "content": "看到了吗【26/07 周日 22:16 · 第140天】"},
                # 助手引用了一个旧后缀作为消息结尾——不能把时钟拖去引用的时刻
                {"role": "assistant", "content": "看到了。你上一条是【25/07 周六 09:00 · 第139天】"},
            ]
            result = await service.archive_window(
                session_tag="pwa-abc123", client_name="shenyu-pwa", messages=window
            )
            assert result["archived"] == 2, result
            rows = supabase.tables["shenyu_chat_archive"]
            assert rows[0]["event_at"] == "2026-07-26T14:16:00+00:00"
            assert rows[1]["event_at"] == "2026-07-26T14:16:00+00:00"

    asyncio.run(run())


def test_chat_archive_global_dedup_across_session_handoff():
    async def run():
        supabase = FakeSupabase()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = GatewayStore(str(Path(tmp) / "test.db"))
            service = ChatArchiveService(store, supabase, Cfg())

            window = [
                {"role": "user", "content": "老会话里说过的话"},
                {"role": "assistant", "content": "老会话里的回答"},
            ]
            first = await service.archive_window(
                session_tag="7.18", client_name="shenyu-pwa", messages=window
            )
            assert first["archived"] == 2, first

            # 换了一个新 session 接上旧历史：旧消息不能再归档一遍
            handoff = window + [{"role": "user", "content": "新会话里的新消息"}]
            second = await service.archive_window(
                session_tag="pwa-new111", client_name="shenyu-pwa", messages=handoff
            )
            assert second["archived"] == 1, second
            rows = supabase.tables["shenyu_chat_archive"]
            assert len(rows) == 3
            assert rows[2]["content"] == "新会话里的新消息"
            assert rows[2]["thread"] == "pwa-new111"

    asyncio.run(run())


def test_chat_archive_seen_ages_out_globally_with_lru_touch():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = GatewayStore(str(Path(tmp) / "test.db"))
        store.mark_archive_hashes_seen("old-epoch", ["h-alive", "h-dormant"], keep_recent=100)

        # h-alive 还在某个客户端窗口里流通：filter 命中即刷新（LRU touch）
        assert store.filter_unseen_archive_hashes(["h-alive"]) == set()

        # 新纪元继续归档并触发全局修剪（下限 100 条）：休眠纪元最老的被挤出，
        # 刚 touch 过的 h-alive 留下
        fresh = [f"h-new-{i}" for i in range(99)]
        store.mark_archive_hashes_seen("new-epoch", fresh, keep_recent=100)
        assert store.filter_unseen_archive_hashes(["h-dormant"]) == {"h-dormant"}
        # 流通中的和新写入的都还被认得
        assert store.filter_unseen_archive_hashes(["h-alive", "h-new-0"]) == set()


def test_derive_thread():
    assert derive_thread("default") == "main"
    assert derive_thread("") == "main"
    assert derive_thread("tech") == "tech"


def test_archive_routes_merge_sessions_and_page_days():
    async def run():
        supabase = FakeSupabase()
        # 两个"线程"各一半，合并成一条时间线；行数超过一页验证分页
        for idx in range(1205):
            await supabase.insert(
                "shenyu_chat_archive",
                {
                    "thread": "5.15" if idx % 2 else "7.18",
                    "content_hash": f"hash-{idx}",
                    "event_at": "2026-06-14T00:00:00+00:00",
                    "deleted_at": None,
                },
            )
        router = build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda: supabase))
        endpoints = {route.path: route.endpoint for route in router.routes}
        assert "/api/archive/threads" not in endpoints
        days = await endpoints["/api/archive/days"](month="2026-06")
        assert days["days"] == [{"date": "2026-06-14", "count": 1205}]

    asyncio.run(run())


def test_archive_routes_fold_handoff_copies_and_twin_delete():
    async def run():
        supabase = FakeSupabase()
        # 同一句话被历史交接归档了两次（两个 session_tag，同日同 hash）
        for thread, event_at in (
            ("6.20", "2026-07-11T03:46:00+00:00"),
            ("7.18", "2026-07-11T03:46:00+00:00"),
        ):
            await supabase.insert(
                "shenyu_chat_archive",
                {
                    "thread": thread,
                    "session_tag": thread,
                    "role": "user",
                    "content": "同一句话",
                    "content_hash": "dup-hash",
                    "event_at": event_at,
                    "archived_at": event_at,
                    "deleted_at": None,
                },
            )
        await supabase.insert(
            "shenyu_chat_archive",
            {
                "thread": "7.18",
                "session_tag": "7.18",
                "role": "assistant",
                "content": "独一份的回答",
                "content_hash": "solo-hash",
                "event_at": "2026-07-11T03:47:00+00:00",
                "archived_at": "2026-07-11T03:47:01+00:00",
                "deleted_at": None,
            },
        )
        router = build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda: supabase))
        endpoints = {route.path: route.endpoint for route in router.routes}

        days = await endpoints["/api/archive/days"](month="2026-07")
        assert days["days"] == [{"date": "2026-07-11", "count": 2}]

        messages = await endpoints["/api/archive/messages"](date="2026-07-11")
        assert [row["content"] for row in messages["messages"]] == ["同一句话", "独一份的回答"]
        assert all("content_hash" not in row for row in messages["messages"])

        # 删掉可见的那条，隐藏的孪生副本必须一起消失
        visible_id = messages["messages"][0]["id"]
        deleted = await endpoints["/api/archive/messages/{message_id}"](visible_id)
        assert deleted["deleted"] == 2
        after = await endpoints["/api/archive/messages"](date="2026-07-11")
        assert [row["content"] for row in after["messages"]] == ["独一份的回答"]

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

        days = await endpoints["/api/archive/days"](month="2026-06")
        messages = await endpoints["/api/archive/messages"](date="2026-06-14")

        assert days["days"] == [
            {"date": "2026-06-13", "count": 1},
            {"date": "2026-06-14", "count": 2},
            {"date": "2026-06-15", "count": 1},
        ]
        assert [row["content"] for row in messages["messages"]] == ["inside-early", "inside-late"]

    asyncio.run(run())


def test_archive_messages_can_widen_around_a_day():
    """选日期是「定位」不是「框死」。

    圆圆报的：跨过午夜的对话被单日筛断，来历书就截不全。around_days 把窗口对称
    放宽，而 around_days=0 必须与原来的单日行为逐字一致。
    """
    async def run():
        supabase = FakeSupabase()
        for content, event_at in (
            ("前一天深夜", "2026-06-13T15:30:00+00:00"),   # CST 6-13 23:30
            ("跨夜之前", "2026-06-14T15:50:00+00:00"),      # CST 6-14 23:50
            ("跨夜之后", "2026-06-14T16:10:00+00:00"),      # CST 6-15 00:10
            ("再后一天", "2026-06-16T02:00:00+00:00"),      # CST 6-16 10:00
        ):
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
        endpoint = {route.path: route.endpoint for route in router.routes}["/api/archive/messages"]

        # 不传参数：与改动前完全一致，只有那一天
        narrow = await endpoint(date="2026-06-14")
        assert [row["content"] for row in narrow["messages"]] == ["跨夜之前"]
        assert await endpoint(date="2026-06-14", around_days=0) == narrow

        # 放宽一天：跨夜的下半段回来了，前一天深夜也在
        wide = await endpoint(date="2026-06-14", around_days=1)
        assert [row["content"] for row in wide["messages"]] == ["前一天深夜", "跨夜之前", "跨夜之后"]
        # 时间序仍然递增，读者可以直接往两头滑
        assert [row["event_at"] for row in wide["messages"]] == sorted(
            row["event_at"] for row in wide["messages"]
        )

        # 窗口有上限，传个荒唐的值不会把整库拉出来
        clamped = await endpoint(date="2026-06-14", around_days=999)
        assert "再后一天" in [row["content"] for row in clamped["messages"]]
        assert len(clamped["messages"]) == 4

    asyncio.run(run())


def test_archive_messages_page_forward_and_backward():
    """连续阅读：before 往过去翻、after 往当下翻，两头都能一直加载。

    两个方向都返回升序，读者可以直接把整块 prepend / append 上去。
    """
    async def run():
        supabase = FakeSupabase()
        stamps = [
            "2026-06-13T01:00:00+00:00",
            "2026-06-13T02:00:00+00:00",
            "2026-06-13T03:00:00+00:00",
            "2026-06-13T04:00:00+00:00",
            "2026-06-13T05:00:00+00:00",
        ]
        for i, event_at in enumerate(stamps):
            await supabase.insert(
                "shenyu_chat_archive",
                {
                    "thread": "main", "session_tag": "default", "role": "user",
                    "content": f"第{i}条", "content_hash": f"h{i}",
                    "event_at": event_at, "archived_at": event_at, "deleted_at": None,
                },
            )
        endpoint = {
            route.path: route.endpoint
            for route in build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda: supabase)).routes
        }["/api/archive/messages"]

        # 往过去翻：严格早于第3条的，取最近的两条，升序返回
        back = await endpoint(before=stamps[3], limit=2)
        assert [row["content"] for row in back["messages"]] == ["第1条", "第2条"]

        # 往当下翻：严格晚于第1条的，取最早的两条，升序返回
        fwd = await endpoint(after=stamps[1], limit=2)
        assert [row["content"] for row in fwd["messages"]] == ["第2条", "第3条"]

        # 翻到头：after 最后一条，什么都没有
        assert (await endpoint(after=stamps[-1]))["messages"] == []

    asyncio.run(run())


def test_archive_search_is_literal_and_folds_handoff_copies():
    """回看的搜索是字面子串，不是语义；跨会话交接的重复行折叠掉。

    fake client 不实现 ilike/or，会把全表交回来，正好逼出端点里那道
    Python 子串复核——它才是权威，DB 的 ilike 只是先收窄。
    """
    async def run():
        supabase = FakeSupabase()
        rows = [
            ("你还记得那个焦糖布丁的方子吗", "user", "u1", "2026-08-19T01:12:00+00:00"),
            ("糖别一次下锅，先干焦糖，琥珀色就离火", "assistant", "a1", "2026-08-19T01:13:00+00:00"),
            ("今天项目又延期了", "user", "u2", "2026-08-12T15:41:00+00:00"),
        ]
        for content, role, digest, event_at in rows:
            await supabase.insert(
                "shenyu_chat_archive",
                {
                    "thread": "main", "session_tag": "default", "role": role,
                    "content": content, "content_hash": digest,
                    "event_at": event_at, "archived_at": event_at, "deleted_at": None,
                },
            )
        # 同一句被历史交接又归档了一次（另一个 session_tag，同日同 hash）
        await supabase.insert(
            "shenyu_chat_archive",
            {
                "thread": "main", "session_tag": "carried", "role": "assistant",
                "content": "糖别一次下锅，先干焦糖，琥珀色就离火", "content_hash": "a1",
                "event_at": "2026-08-19T01:13:00+00:00", "archived_at": "2026-08-19T01:13:00+00:00",
                "deleted_at": None,
            },
        )
        endpoint = {
            route.path: route.endpoint
            for route in build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda: supabase)).routes
        }["/api/archive/search"]

        # 空 query 不触发全表
        resp = await endpoint(q="  ")
        assert resp["results"] == [] and resp["count"] == 0 and resp["query"] == ""

        # 字面命中「焦糖」：两条，交接副本被折叠成一条
        hit = await endpoint(q="焦糖")
        assert hit["count"] == 2, hit
        # Search results use snippet format, not full content
        assert all("焦糖" in (row.get("snippet_match") or "") for row in hit["results"])
        # Check that duplicate content is folded (only one assistant message about sugar)
        assistant_snippets = [row["snippet_match"] for row in hit["results"] if row["role"] == "assistant"]
        assert len(assistant_snippets) == 1

        # role 过滤
        only_user = await endpoint(q="焦糖", role="user")
        assert [row["role"] for row in only_user["results"]] == ["user"]

        # 字面而非语义：搜「布丁」命中，搜近义的「甜点」一条不给
        assert (await endpoint(q="布丁"))["count"] == 1
        assert (await endpoint(q="甜点"))["count"] == 0

        # content_hash 不外泄给前端
        assert all("content_hash" not in row for row in hit["results"])

    asyncio.run(run())


def test_resident_books_routes_split_generated_home_from_living_identity():
    async def run():
        supabase = FakeSupabase()
        router = build_archive_router(ArchiveRouteDeps(get_supabase_client=lambda: supabase))
        endpoints = {route.path: route.endpoint for route in router.routes}
        read_endpoint = next(
            route.endpoint
            for route in router.routes
            if route.path == "/api/books/{book}" and "GET" in (route.methods or set())
        )
        write_endpoint = next(
            route.endpoint
            for route in router.routes
            if route.path == "/api/books/{book}" and "PATCH" in (route.methods or set())
        )

        overview = await endpoints["/api/books"]()
        assert overview["ok"]
        assert overview["home"]["current_week"]

        written = await write_endpoint(
            "identity",
            ResidentBookWrite(content="我和圆圆一起写的自述", summary="第一版自述"),
        )
        assert written["ok"]
        assert written["book"]["revision"] == 1

        annotated = await endpoints["/api/books/{book}/annotations"](
            "identity",
            ResidentBookAnnotation(content="这条是圆圆留下的批注。"),
        )
        assert annotated["ok"]

        read = await read_endpoint("identity", view="history")
        assert read["book"]["body"] == "我和圆圆一起写的自述"
        assert read["book"]["annotations"][0]["actor"] == "圆圆"
        assert len(read["revisions"]) == 1

        home_write = await write_endpoint(
            "home",
            ResidentBookWrite(content="不该覆盖自动家况"),
        )
        assert home_write["error_kind"] == "read_only"
        home_note = await endpoints["/api/books/{book}/annotations"](
            "home",
            ResidentBookAnnotation(content="这条批注保留。"),
        )
        assert home_note["ok"]
        home = await read_endpoint("home", view="history")
        assert home["kind"] == "snapshot"
        assert "body" not in home["book"]
        assert home["book"]["annotations"][0]["content"] == "这条批注保留。"

    asyncio.run(run())


if __name__ == "__main__":
    test_conflict_book_invariants()
    test_chat_archive_dedup()
    test_chat_archive_uses_client_attachment_time()
    test_chat_archive_backfill_uses_client_attachment_time()
    test_chat_archive_skips_numbered_transcript_messages()
    test_chat_archive_uses_pwa_suffix_time_and_replay_order()
    test_chat_archive_assistant_quote_does_not_move_clock()
    test_chat_archive_global_dedup_across_session_handoff()
    test_derive_thread()
    test_archive_routes_merge_sessions_and_page_days()
    test_archive_routes_fold_handoff_copies_and_twin_delete()
    test_archive_routes_use_cst_day_boundaries()
    test_archive_messages_page_forward_and_backward()
    test_archive_search_is_literal_and_folds_handoff_copies()
    print("ALL_OK")


def test_archive_search_snippet_and_cursor():
    """Test that search returns snippet fields and supports composite cursor."""
    async def run():
        from fastapi.testclient import TestClient
        
        supabase = FakeSupabase()
        deps = ArchiveRouteDeps(get_supabase_client=lambda: supabase)
        router = build_archive_router(deps)
        
        # 准备测试数据：3条消息，其中2条包含"测试"，且同一轮的 user/assistant 共享 event_at
        await supabase.insert("shenyu_chat_archive", {
            "id": "msg-1",
            "role": "user",
            "content": "这是第一条测试消息，前面有很多字后面也有很多字",
            "content_hash": "hash1",
            "event_at": "2026-09-10T10:00:00+08:00",
            "archived_at": "2026-09-10T10:00:00.000001+00:00",
            "session_tag": "test",
            "deleted_at": None,
        })
        await supabase.insert("shenyu_chat_archive", {
            "id": "msg-2",
            "role": "assistant",
            "content": "我理解了你的测试需求，这里是回复内容",
            "content_hash": "hash2",
            "event_at": "2026-09-10T10:00:00+08:00",  # 同一轮，共享时间戳
            "archived_at": "2026-09-10T10:00:00.000002+00:00",
            "session_tag": "test",
            "deleted_at": None,
        })
        await supabase.insert("shenyu_chat_archive", {
            "id": "msg-3",
            "role": "user",
            "content": "另一条不相关的消息",
            "content_hash": "hash3",
            "event_at": "2026-09-10T11:00:00+08:00",
            "archived_at": "2026-09-10T11:00:00.000001+00:00",
            "session_tag": "test",
            "deleted_at": None,
        })
        
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        
        # 测试 1: 搜索返回 snippet 字段而不是完整 content
        resp = client.get("/api/archive/search?q=测试&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "测试"
        assert len(data["results"]) == 2
        assert data["count"] == 2
        assert data["has_more"] is False
        
        # 验证 snippet 字段存在且高亮了匹配词
        result = data["results"][0]
        assert "snippet_before" in result
        assert "snippet_match" in result
        assert "snippet_after" in result
        assert result["snippet_match"] == "测试"  # 原样大小写
        assert "content" not in result  # 不返回完整内容
        
        # 测试 2: 带 cursor 分页
        resp = client.get("/api/archive/search?q=测试&limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["has_more"] is True
        assert data["next_cursor"] is not None
        
        # 使用游标获取下一页
        cursor = data["next_cursor"]
        print(f"\n=== DEBUG: Using cursor: {cursor}")
        resp = client.get(f"/api/archive/search?q=测试&limit=1&cursor={cursor}")
        assert resp.status_code == 200
        data2 = resp.json()
        print(f"=== DEBUG: Second page response: {data2}")
        assert len(data2["results"]) == 1
        assert data2["has_more"] is False
        assert data["results"][0]["id"] != data2["results"][0]["id"]  # 不同的消息
        
    asyncio.run(run())


def test_archive_messages_composite_cursor():
    """Test that archive messages pagination uses composite (event_at, id) cursor."""
    async def run():
        from fastapi.testclient import TestClient
        
        supabase = FakeSupabase()
        deps = ArchiveRouteDeps(get_supabase_client=lambda: supabase)
        router = build_archive_router(deps)
        
        # 准备测试数据：同一轮的 user/assistant 共享 event_at
        await supabase.insert("shenyu_chat_archive", {
            "id": "msg-1",
            "role": "user",
            "content": "第一条",
            "content_hash": "hash1",
            "event_at": "2026-09-10T10:00:00+08:00",
            "archived_at": "2026-09-10T10:00:00.000001+00:00",
            "session_tag": "test",
            "deleted_at": None,
        })
        await supabase.insert("shenyu_chat_archive", {
            "id": "msg-2",
            "role": "assistant",
            "content": "第一条的回复",
            "content_hash": "hash2",
            "event_at": "2026-09-10T10:00:00+08:00",  # 同一时刻
            "archived_at": "2026-09-10T10:00:00.000002+00:00",
            "session_tag": "test",
            "deleted_at": None,
        })
        await supabase.insert("shenyu_chat_archive", {
            "id": "msg-3",
            "role": "user",
            "content": "第二条",
            "content_hash": "hash3",
            "event_at": "2026-09-10T11:00:00+08:00",
            "archived_at": "2026-09-10T11:00:00.000001+00:00",
            "session_tag": "test",
            "deleted_at": None,
        })
        
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        
        # 获取所有消息
        resp = client.get("/api/archive/messages?limit=100")
        assert resp.status_code == 200
        all_msgs = resp.json()["messages"]
        assert len(all_msgs) == 3

        # 用复合游标 "event_at|id" 往过去翻，应该正确处理同一时刻的多条消息
        # before 使用最新一条（msg-3）的复合游标
        cursor = f"{all_msgs[2]['event_at']}|{all_msgs[2]['id']}"
        resp = client.get(f"/api/archive/messages?before={cursor}&limit=10")
        assert resp.status_code == 200
        older = resp.json()["messages"]
        # 应该拿到 msg-1 和 msg-2，因为它们的 event_at < cursor 或者 event_at 相同但 id < cursor_id
        assert len(older) == 2
        assert older[0]["id"] == "msg-1"
        assert older[1]["id"] == "msg-2"

        # 用复合游标往当下翻
        cursor = f"{all_msgs[0]['event_at']}|{all_msgs[0]['id']}"
        resp = client.get(f"/api/archive/messages?after={cursor}&limit=10")
        assert resp.status_code == 200
        newer = resp.json()["messages"]
        # 应该拿到 msg-2 和 msg-3
        assert len(newer) == 2
        assert newer[0]["id"] == "msg-2"  # 同一 event_at 但 id > cursor_id
        assert newer[1]["id"] == "msg-3"
        
    asyncio.run(run())
