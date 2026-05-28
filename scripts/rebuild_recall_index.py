from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shenyu_gateway.recall import RecallIndexService
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.supabase import SupabaseClient


async def main() -> None:
    cfg = RuntimeConfig()
    client = SupabaseClient(cfg.supabase_url, cfg.supabase_key)
    try:
        service = RecallIndexService(client, cfg=cfg)
        rebuild = await service.rebuild()
        print(json.dumps({"rebuild": rebuild}, ensure_ascii=False, indent=2))

        result = await service.recall("长隆 海獭", session_tag="5.15", auto_sync=False, limit=5)
        safe_items = result.get("items", [])
        print(
            json.dumps(
                {
                    "recall": {
                        "ok": result.get("ok"),
                        "count": result.get("count"),
                        "items": safe_items,
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
