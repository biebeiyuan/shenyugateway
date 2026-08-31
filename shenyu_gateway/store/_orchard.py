from __future__ import annotations

import uuid
from typing import Any, Optional

from ..runtime import iso_now, local_today

# 盼圃的天气，存本机卷的 SQLite（生产是 named volume `shenyu-gateway-data`
# 挂在 `/data`），不进 Supabase。
#
# 判据跟相册那条一样：**只有需要被 Recall 想起来的东西才值得占 Supabase 的额度。**
# 果子和纸条要进（摘了之后是他们等到过的往事，以后会被想起来），天气不要——
# 没人会去搜"那天下的那场冰雹"，它只是算料，用来决定摘下来的果子长什么样。
# 卷万一出事，丢的是几行天气记录，果子和他们说过的话都还在。
#
# `(on_day, kind)` 唯一：同一天同一类天气只记一行，所以调用方可以放心地顺手
# 写，重复和并发都靠约束挡掉。


class OrchardMixin:
    def record_orchard_weather(
        self,
        *,
        kind: str,
        detail: str = "",
        observed_text: str = "",
        temp_c: Optional[int] = None,
        on_day: Optional[str] = None,
    ) -> None:
        day = str(on_day or local_today().isoformat())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orchard_weather (id, on_day, kind, detail, observed_text, temp_c, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(on_day, kind) DO NOTHING
                """,
                (
                    str(uuid.uuid4()),
                    day,
                    str(kind or ""),
                    str(detail or ""),
                    str(observed_text or ""),
                    temp_c,
                    iso_now(),
                ),
            )

    def orchard_weather_since(self, on_day: str) -> list[dict[str, Any]]:
        """这一天（含）之后记下的天气，按日子正序。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM orchard_weather WHERE on_day >= ? ORDER BY on_day ASC",
                (str(on_day or ""),),
            ).fetchall()
        return [dict(row) for row in rows]
