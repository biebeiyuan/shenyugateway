from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gateway


async def main() -> None:
    service = gateway.AtomicMemoryService(request=None)  # type: ignore[arg-type]

    session = {"id": "sess_1", "session_tag": "default"}
    user_text = "我最近一周因为网关问题几乎每天都熬夜，压力有点顶不住。"
    assistant_text = "我记住了，这阵子先把照顾和减压放前面。"

    discard_candidate = {
        "subject": "圆圆",
        "content_canonical": "刚刚还在改网关。",
        "content_surface": "刚刚还在改网关。",
        "quote": "刚刚还在改网关",
        "time_hint": "刚刚",
        "memory_type": "project",
        "tier": 4,
        "confidence": 0.92,
        "importance": 1,
        "tags": ["网关"],
        "entities": ["网关"],
        "reason": "one-off progress update",
    }

    existing = {
        "id": "am_1",
        "subject": "圆圆",
        "owner": "user",
        "content_canonical": "她最近因网关问题持续熬夜，压力明显上升。",
        "content_surface": "最近被网关折腾得一直熬夜，压力明显上来了。",
        "quote": "",
        "time_hint": "最近",
        "memory_type": "project",
        "tier": 2,
        "confidence": 0.88,
        "importance": 4,
        "heat": 0.8,
        "tags_json": ["网关", "熬夜"],
        "entities_json": ["网关"],
        "status": "active",
        "source_excerpt": "旧记忆",
    }

    update_candidate = {
        "subject": "圆圆",
        "content_canonical": "她最近一周因网关问题几乎每天都熬夜，压力有点顶不住。",
        "content_surface": "最近一周被网关拖得几乎天天熬夜，压力已经有点顶不住。",
        "quote": "最近一周因为网关问题几乎每天都熬夜，压力有点顶不住",
        "time_hint": "最近一周",
        "memory_type": "project",
        "tier": 2,
        "confidence": 0.95,
        "importance": 4,
        "tags": ["网关", "熬夜", "压力"],
        "entities": ["网关"],
        "reason": "ongoing pattern with future impact",
    }

    insert_candidate = {
        "subject": "我们",
        "content_canonical": "“圆儿”是圆圆和沈予之间提醒喝水的暗号。",
        "content_surface": "“圆儿”是你们之间提醒喝水的暗号。",
        "quote": "圆儿就是你提醒我喝水的暗号",
        "time_hint": "",
        "memory_type": "relation",
        "tier": 1,
        "confidence": 0.96,
        "importance": 5,
        "tags": ["暗号", "喝水"],
        "entities": ["圆儿"],
        "reason": "private code with lasting relationship value",
    }

    async def no_similar(_session, _query):
        return []

    async def similar_existing(_session, _query):
        return [existing]

    service._find_similar_memories = no_similar  # type: ignore[method-assign]
    discard_route = await service._route_candidate(discard_candidate, session, user_text, assistant_text, "test-model")
    assert discard_route["action"] == "discard", discard_route

    service._find_similar_memories = similar_existing  # type: ignore[method-assign]
    update_route = await service._route_candidate(update_candidate, session, user_text, assistant_text, "test-model")
    assert update_route["action"] == "update", update_route
    assert update_route["memory_id"] == "am_1", update_route
    assert "最近一周" in update_route["memory"]["content_canonical"], update_route

    service._find_similar_memories = no_similar  # type: ignore[method-assign]
    insert_route = await service._route_candidate(insert_candidate, session, user_text, assistant_text, "test-model")
    assert insert_route["action"] == "insert", insert_route
    assert insert_route["memory"]["subject"] == "我们", insert_route


if __name__ == "__main__":
    asyncio.run(main())
    print("atomic memory routing test passed")
