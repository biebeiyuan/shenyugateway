#!/usr/bin/env python3
"""记忆衰减：每晚对所有非恒星记忆的 activation_score 乘以 0.82。

运行时机：每晚 04:00（用户睡眠时段）通过 cron 触发。
衰减规则：
  - 普通记忆：activation_score *= 0.82
  - 恒星记忆（is_constant=true）：不衰减
  - 衰减后 < 0.01 的归零（避免长尾噪声）
"""

from __future__ import annotations

import sys
from pathlib import Path

# 把项目根目录加入 Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shenyu_gateway.runtime import logger
from shenyu_gateway.store import GatewayStore
from shenyu_gateway.config import load_config


DECAY_RATE = 0.82  # 普通记忆保留率
FLOOR_THRESHOLD = 0.01  # 低于此值归零


def decay_memory_activation():
    """对所有非恒星记忆执行一次衰减。"""
    try:
        cfg = load_config()
        store = GatewayStore(cfg)

        with store._connect() as conn:
            # Stars: 非恒星的 activation_score *= 0.82，< 0.01 归零
            cursor = conn.execute(
                """
                UPDATE shenyu_stars
                SET activation_score = CASE
                    WHEN activation_score * ? < ? THEN 0.0
                    ELSE activation_score * ?
                END
                WHERE activation_score > 0
                  AND (is_constant IS NULL OR is_constant = 0)
                """,
                (DECAY_RATE, FLOOR_THRESHOLD, DECAY_RATE),
            )
            stars_updated = cursor.rowcount

            # Mem Notes: 同样的逻辑
            cursor = conn.execute(
                """
                UPDATE shenyu_mem_notes
                SET activation_score = CASE
                    WHEN activation_score * ? < ? THEN 0.0
                    ELSE activation_score * ?
                END
                WHERE activation_score > 0
                  AND (is_constant IS NULL OR is_constant = 0)
                """,
                (DECAY_RATE, FLOOR_THRESHOLD, DECAY_RATE),
            )
            mem_notes_updated = cursor.rowcount

        logger.info(
            "[MemoryDecay] 衰减完成：%d 颗星星、%d 条便签",
            stars_updated,
            mem_notes_updated,
        )
        print(f"✓ 衰减完成：{stars_updated} stars, {mem_notes_updated} mem_notes")
        return 0

    except Exception:
        logger.exception("[MemoryDecay] 衰减失败")
        print("✗ 衰减失败，详见日志", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(decay_memory_activation())
