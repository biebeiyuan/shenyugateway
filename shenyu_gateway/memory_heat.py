"""记忆热度：写事件账本，读时算活性，把活性压成一个排序修正项。

活性不存在任何一张表的列上。事件表 `shenyu_heat_events` 是不可变账本，
活性由 Supabase 的 `shenyu_star_activation` / `shenyu_mem_note_activation`
两个视图按 `created_at` 读时算出来（衰减 0.82/天，半衰期 ≈ 3.5 天，90 天窗口）。
所以没有夜间衰减任务——漏跑一晚这件事不存在。

为什么修正项要取对数再封顶
---------------------------
视图给的 activation 是原始值、无上界：每天进岛 n 次的稳态是 0.547n，
n=20 就到 11。直接乘 `1 + 0.15 * 11` 是 2.6 倍，会把便签的分数顶出 0–1 值域，
`mem_note_min_score` 那几条线全部静默漂移。而且沈予要的是「偶尔冒出一个我没料到的」，
一个没有上界的使用权重恰好压掉的就是这个——常想起的更容易再被想起，
于是进过的更容易留下、留下的又加热，那是车辙不是地形。

所以照 ACT-R 本来的样子取对数（`B = ln Σ t^-d`），再 clamp 到 [1.0, MAX]，
和家里其他 modifier 同一把尺（constant_boost 1.3、date_boost_max 0.3）。
封顶意味着热度最多推 30%，不足以盖掉一次真正的语义命中——
novelty_mod 还有得打，这场拔河才有意义。
"""

from __future__ import annotations

import math
from typing import Any

from .runtime import logger, local_today


HEAT_EVENTS_TABLE = "shenyu_heat_events"
STAR_ACTIVATION_VIEW = "shenyu_star_activation"
MEM_NOTE_ACTIVATION_VIEW = "shenyu_mem_note_activation"

# 修正项的上界。1.3 = 和 star_rrf_constant_boost 同一个量级，刻意的：
# 热度最多和「恒星」一样重，不该更重。
ACTIVATION_MOD_MAX = 1.3


def activation_modifier(activation: Any, weight: float) -> float:
    """把原始活性压成一个 [1.0, ACTIVATION_MOD_MAX] 之间的乘法修正项。

    `1 + weight * ln(1 + activation)`，再封顶。activation=0 时正好是 1.0
    （没热度就是不修正，不是罚分）。
    """
    try:
        raw = float(activation or 0.0)
    except (TypeError, ValueError):
        return 1.0
    if raw <= 0:
        return 1.0
    try:
        w = float(weight)
    except (TypeError, ValueError):
        return 1.0
    if w <= 0:
        return 1.0
    return min(ACTIVATION_MOD_MAX, 1.0 + w * math.log1p(raw))


async def fetch_star_activations(supabase: Any, star_ids: list[str]) -> dict[str, float]:
    """读这批星星的活性。任何失败都退回空 dict——没热度只是没修正，不是故障。"""
    return await _fetch_activations(
        supabase, STAR_ACTIVATION_VIEW, "star_id", star_ids, label="星星"
    )


async def fetch_mem_note_activations(supabase: Any, note_ids: list[str]) -> dict[str, float]:
    """读这批便签的活性。"""
    return await _fetch_activations(
        supabase, MEM_NOTE_ACTIVATION_VIEW, "mem_note_id", note_ids, label="便签"
    )


async def _fetch_activations(
    supabase: Any,
    view: str,
    id_column: str,
    ids: list[str],
    *,
    label: str,
) -> dict[str, float]:
    wanted = sorted({str(item).strip() for item in ids or [] if str(item or "").strip()})
    if not supabase or not wanted:
        return {}
    # 别按 id 过滤：500 个 UUID 会造 18,500 字符的 URL，Kong 默认 16k header
    # buffer 拒掉（414）。视图有 `having count(e.id) > 0`，只返回 90 天内真的
    # 有事件的记忆，实际大概几百行，远少于 2000 上限。读下来后在 Python 里过滤。
    # 按热度降序，万一哪天真超 2000 行，丢掉的是最冷的那些，而不是随机的。
    try:
        rows = await supabase.query(
            view,
            {
                "select": f"{id_column},activation",
                "order": "activation.desc",
                "limit": "2000",
            },
        )
    except Exception as exc:
        # 读不到活性不该拖垮一次召回：地形消失，语义排序照常。
        logger.warning("[MemoryHeat] 读%s活性失败，这一轮按无热度排: %s", label, exc)
        return {}
    if rows and len(rows) >= 2000:
        logger.warning(
            "[MemoryHeat] %s 视图返回 %d 行（达到 limit），可能截断了最冷的部分",
            view, len(rows)
        )
    wanted_set = set(wanted)
    result: dict[str, float] = {}
    for row in rows or []:
        key = str((row or {}).get(id_column) or "").strip()
        if not key or key not in wanted_set:
            continue
        try:
            result[key] = float(row.get("activation") or 0.0)
        except (TypeError, ValueError):
            continue
    return result


async def record_island_entry(
    supabase: Any,
    *,
    session_id: str,
    turn_index: Any,
    star_ids: list[str],
    mem_note_ids: list[str],
) -> int:
    """给这一轮**新进岛**的记忆记一笔热度事件。返回写了几行。

    只记 `entering`（新进岛），不记「这一轮在岛上」。岛有 retain：一颗星留十轮，
    按驻留写就会记十次，那量的是驻留时长不是被想起的次数。
    `resolve_memory_island` 返回的 `entering` 按 item id 算而不是按指纹算，
    所以留在岛上的不会被重复打戳——这个区分那边已经替我们做好了。

    幂等靠 `event_id` 的唯一约束 + `on_conflict` 合并：重试、流式断连重连、
    tool loop 里多次 mark，都只会留下一行。`event_id` 加了日期，防止冷启动、
    刷新等情况下 `human_turn_index` 重置后和几个月前的事件碰撞——碰撞窗口从
    「整个 session 生命周期」缩到「同一天内」，而同一天内 turn_index 不会倒退。
    """
    if not supabase or not session_id:
        return 0
    try:
        turn = int(turn_index)
    except (TypeError, ValueError):
        turn = 0

    # 取当天日期（Asia/Shanghai），event_id 加上日期防止 turn_index 重置后碰撞。
    today = local_today().isoformat()  # YYYY-MM-DD

    rows: list[dict[str, Any]] = []
    for kind, column, ids in (
        ("star", "star_id", star_ids),
        ("mem", "mem_note_id", mem_note_ids),
    ):
        for raw in ids or []:
            memory_id = str(raw or "").strip()
            if not memory_id:
                continue
            rows.append(
                {
                    "event_id": f"{session_id}:{today}:{turn}:{kind}:{memory_id}",
                    "event_type": "island_enter",
                    column: memory_id,
                    "session_id": str(session_id),
                    "turn_index": turn,
                }
            )
    if not rows:
        return 0

    try:
        await supabase.upsert_minimal(HEAT_EVENTS_TABLE, rows, on_conflict="event_id")
    except Exception as exc:
        # 记不上热度不该影响这一轮对话。但要吼出来——静默失败正是上一版
        # 死在生产、活在测试的原因。
        logger.warning("[MemoryHeat] 记录热度事件失败 (%d 行): %s", len(rows), exc)
        return 0
    logger.info(
        "[MemoryHeat] 记录 %d 条热度事件 (session=%s turn=%d)",
        len(rows),
        str(session_id)[:8],
        turn,
    )
    return len(rows)
