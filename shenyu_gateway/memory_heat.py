"""记忆加热：追踪哪些记忆真正进了提示词，给它们加 activation 权重。

activation_score 是记忆被想起的次数的指数衰减累积。每次真正进提示词 +0.12，
每晚衰减一次（乘以 0.82）。恒星（is_constant=true）和被钉住的记忆不衰减。

heat_events 是幂等事件表：同一个 (session_id, turn_index, memory_kind, memory_id)
只记录一次，防止重试、重放或流式断连重连时重复加热。
"""

from __future__ import annotations

from typing import Any

from .runtime import logger


HEAT_INCREMENT = 0.12  # 每次注入加这么多


def _apply_heat_for_island_injection(meta: dict, store: Any):
    """从 mark_context_consumed 调用：给这一轮真正进了动态岛的记忆加热。

    幂等：同一个 (session_id, turn_index, memory_kind, memory_id) 只记录一次。
    """
    try:
        package = meta.get("package") or {}
        session = meta.get("session") or {}
        session_id = session.get("id")
        if not session_id:
            return

        # turn_index 从 session 的 turn_count 推：这轮准备上下文时 turn_count 还没加，
        # 所以这轮的 turn_index 就是当时的 turn_count（从 0 开始）
        turn_index = session.get("turn_count", 0)

        island_state = package.get("memory_island_state") or {}
        star_ids = [item["id"] for item in island_state.get("stars") or [] if item.get("id")]
        mem_ids = [item["id"] for item in island_state.get("mem_notes") or [] if item.get("id")]

        if not star_ids and not mem_ids:
            return

        heated = store.apply_heat(
            session_id=str(session_id),
            turn_index=turn_index,
            star_ids=[str(sid) for sid in star_ids],
            mem_note_ids=[str(mid) for mid in mem_ids],
            heat_increment=HEAT_INCREMENT,
        )
        if heated.get("star_count") or heated.get("mem_count"):
            logger.info(
                "[MemoryHeat] 加热 %d 颗星星、%d 条便签 (session=%s turn=%d)",
                heated.get("star_count", 0),
                heated.get("mem_count", 0),
                str(session_id)[:8],
                turn_index,
            )
    except Exception:
        logger.exception("[MemoryHeat] 加热失败")
