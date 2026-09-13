#!/usr/bin/env python3
"""
测试档案写入逻辑：验证在多轮工具调用场景下，
第一轮的消息是否会因为某种原因被标记为seen但实际没有写入档案。
"""

import asyncio
import tempfile
from pathlib import Path
from shenyu_gateway.chat_archive import ChatArchiveService
from shenyu_gateway.store import GatewayStore


class FakeSupabase:
    def __init__(self):
        self.archive_table = []
        self.insert_calls = []

    async def insert_many(self, table: str, rows: list[dict]) -> list:
        self.insert_calls.append((table, rows))
        for row in rows:
            self.archive_table.append(row)
        return rows


class FakeConfig:
    enable_chat_archive = True
    chat_archive_seen_retention = 10000


async def _run_multi_round_tool_call():
    """模拟多轮工具调用场景"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = GatewayStore(str(db_path))
        supabase = FakeSupabase()
        cfg = FakeConfig()
        service = ChatArchiveService(store, supabase, cfg)

        # 第一次请求：用户发送消息，assistant回复第1轮
        # 但档案写入只在请求开始时执行，传入的是旧消息窗口（不包含本次回复）
        print("=== 第一次请求开始 ===")
        await service.archive_window(
            session_tag="session_1",
            client_name="pwa",
            messages=[
                {"role": "user", "content": "<!-- 2026-09-13T00:40:00+08:00 -->你好"},
            ],
        )
        print(f"写入档案: {len(supabase.archive_table)} 条")

        # 模拟第一次请求产生的assistant回复（第1轮、第3轮）
        # 这些回复现在在PWA本地，但还没写入档案
        first_round = "她睡了。零点过四十分，抱着检查合格的姿势掉下去的。"
        third_round = "写完了。合上本子。"

        # 第二次请求：PWA发送完整窗口（包含第1轮和第3轮的回复）
        print("\n=== 第二次请求开始 ===")
        print("PWA发送的消息窗口包含:")
        print(f"  - user: 你好")
        print(f"  - assistant: {first_round[:30]}...")
        print(f"  - assistant: {third_round[:30]}...")

        result = await service.archive_window(
            session_tag="session_1",
            client_name="pwa",
            messages=[
                {"role": "user", "content": "<!-- 2026-09-13T00:40:00+08:00 -->你好"},
                {"role": "assistant", "content": first_round},
                {"role": "assistant", "content": third_round},
            ],
        )
        print(f"本次写入档案: {result['archived']} 条")
        print(f"档案总数: {len(supabase.archive_table)} 条")

        # 检查档案内容
        print("\n=== 档案内容 ===")
        for i, row in enumerate(supabase.archive_table, 1):
            content = row['content'][:50] + "..." if len(row['content']) > 50 else row['content']
            print(f"{i}. [{row['role']}] {content}")

        # 检查seen表
        with store._connect() as conn:
            seen_hashes = conn.execute(
                "SELECT content_hash FROM chat_archive_seen"
            ).fetchall()
        print(f"\n=== Seen表中的hash数量: {len(seen_hashes)} ===")

        # 验证：第1轮和第3轮的消息都应该在档案中
        contents = [row['content'] for row in supabase.archive_table]
        assert first_round in contents, f"第1轮消息没有在档案中！档案内容: {contents}"
        assert third_round in contents, f"第3轮消息没有在档案中！档案内容: {contents}"

        print("\n✅ 测试通过：两条消息都在档案中")


def test_multi_round_tool_call():
    """Pytest-discoverable entry point for the multi-round archive regression."""
    asyncio.run(_run_multi_round_tool_call())


def test_archive_snippet_handles_casefold_expansion_without_offset_corruption():
    async def run():
        from shenyu_gateway.archive_routes import ArchiveRouteDeps, build_archive_router

        class Supabase:
            async def query(self, table, params=None):
                return [{
                    "id": "sharp-s",
                    "session_tag": "test",
                    "role": "user",
                    "content": "前缀 ß 后缀",
                    "content_hash": "sharp-s",
                    "event_at": "2026-09-13T00:00:00+08:00",
                    "archived_at": "2026-09-13T00:00:01+08:00",
                    "deleted_at": None,
                }]

        endpoint = next(
            route.endpoint for route in build_archive_router(
                ArchiveRouteDeps(get_supabase_client=lambda: Supabase())
            ).routes if route.path == "/api/archive/search"
        )
        result = await endpoint(q="ß")
        assert result["results"][0]["snippet_before"] == "前缀 "
        assert result["results"][0]["snippet_match"] == "ß"
        assert result["results"][0]["snippet_after"] == " 后缀"

    asyncio.run(run())


if __name__ == "__main__":
    asyncio.run(_run_multi_round_tool_call())
