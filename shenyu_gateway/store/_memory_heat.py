"""记忆加热存储层：幂等事件表 + Stars/Mem Notes 的 activation_score 更新。"""

from __future__ import annotations

from typing import Any

from ..runtime import iso_now


HEAT_EVENTS_TABLE = "shenyu_heat_events"


class MemoryHeatMixin:
    def apply_heat(
        self,
        *,
        session_id: str,
        turn_index: int,
        star_ids: list[str],
        mem_note_ids: list[str],
        heat_increment: float,
    ) -> dict[str, int]:
        """给进了动态岛的记忆加热，幂等。

        Returns:
            {"star_count": int, "mem_count": int} — 实际加热的数量（去重后）
        """
        star_ids = [sid for sid in star_ids if sid]
        mem_note_ids = [mid for mid in mem_note_ids if mid]

        if not star_ids and not mem_note_ids:
            return {"star_count": 0, "mem_count": 0}

        now = iso_now()
        star_count = 0
        mem_count = 0

        with self._connect() as conn:
            # 幂等：先写 heat_events，只有新插入成功的才加热
            for star_id in star_ids:
                event_id = f"{session_id}:{turn_index}:star:{star_id}"
                try:
                    conn.execute(
                        f"""
                        INSERT INTO {HEAT_EVENTS_TABLE} (event_id, session_id, turn_index, memory_kind, memory_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (event_id, session_id, turn_index, "star", star_id, now),
                    )
                    # 插入成功 → 这是新事件，加热
                    conn.execute(
                        """
                        UPDATE shenyu_stars
                        SET activation_score = COALESCE(activation_score, 0) + ?
                        WHERE id = ?
                        """,
                        (heat_increment, star_id),
                    )
                    star_count += 1
                except Exception:
                    # UNIQUE 冲突 → 已经加热过，跳过
                    pass

            for mem_id in mem_note_ids:
                event_id = f"{session_id}:{turn_index}:mem:{mem_id}"
                try:
                    conn.execute(
                        f"""
                        INSERT INTO {HEAT_EVENTS_TABLE} (event_id, session_id, turn_index, memory_kind, memory_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (event_id, session_id, turn_index, "mem_note", mem_id, now),
                    )
                    conn.execute(
                        """
                        UPDATE shenyu_mem_notes
                        SET activation_score = COALESCE(activation_score, 0) + ?
                        WHERE id = ?
                        """,
                        (heat_increment, mem_id),
                    )
                    mem_count += 1
                except Exception:
                    pass

        return {"star_count": star_count, "mem_count": mem_count}
