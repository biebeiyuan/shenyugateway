#!/usr/bin/env python3
"""记忆衰减：每晚把 activation_score 乘以保留率。

恒星（is_constant=true）不衰减，普通记忆每晚衰减 18%（保留率 0.82）。
这让常用的记忆保持高分，久未想起的自然降温。

Usage:
    python scripts/nightly_memory_decay.py

Cron (本地 VPS，每天凌晨 4:07 跑):
    7 4 * * * cd /root/shenyu-gateway && /usr/bin/python3 scripts/nightly_memory_decay.py >> /var/log/shenyu_decay.log 2>&1
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 把项目根目录加到 sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from shenyu_gateway.runtime import logger
from shenyu_gateway.store._base import get_supabase_client


RETENTION_RATE = 0.82  # 普通记忆的保留率（每晚乘以这个数）
# 恒星的保留率是 1.0（不衰减），通过 WHERE is_constant IS NOT TRUE 跳过


def decay_memory_activation(supabase):
    """对 stars 和 mem_notes 表执行衰减。"""

    # Stars
    stars_result = supabase.rpc(
        "decay_activation_scores",
        {
            "table_name": "shenyu_stars",
            "retention": RETENTION_RATE,
        }
    ).execute()
    stars_count = stars_result.data if isinstance(stars_result.data, int) else 0

    # Mem Notes
    mem_result = supabase.rpc(
        "decay_activation_scores",
        {
            "table_name": "shenyu_mem_notes",
            "retention": RETENTION_RATE,
        }
    ).execute()
    mem_count = mem_result.data if isinstance(mem_result.data, int) else 0

    logger.info(
        "[MemoryDecay] 衰减完成：%d 颗星星、%d 条便签 (保留率 %.2f)",
        stars_count,
        mem_count,
        RETENTION_RATE,
    )
    return {"stars": stars_count, "mem_notes": mem_count}


def main():
    # 从环境变量读取 Supabase 配置
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        logger.error("[MemoryDecay] SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY 未配置")
        sys.exit(1)

    supabase = get_supabase_client(url, key)

    try:
        result = decay_memory_activation(supabase)
        print(f"✓ 衰减完成：{result['stars']} 颗星星、{result['mem_notes']} 条便签")
    except Exception as e:
        logger.exception("[MemoryDecay] 衰减失败")
        print(f"✗ 衰减失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
