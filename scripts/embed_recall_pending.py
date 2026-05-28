from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.recall import RECALL_INDEX_TABLE, RecallIndexService
from shenyu_gateway.supabase import SupabaseClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed pending rows in shenyu_recall_index.")
    parser.add_argument("--batch-size", type=int, default=50, help="Rows to embed per batch.")
    parser.add_argument("--max-batches", type=int, default=0, help="Stop after N batches; 0 means run until drained.")
    parser.add_argument("--max-errors", type=int, default=5, help="Stop after N failed batches.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between batches.")
    parser.add_argument("--retry-sleep", type=float, default=5.0, help="Seconds to sleep after a failed batch.")
    parser.add_argument("--once", action="store_true", help="Run one batch and exit.")
    return parser.parse_args()


async def pending_counts(client: SupabaseClient) -> dict[str, int]:
    rows = await client.query(
        RECALL_INDEX_TABLE,
        {
            "select": "embedding_status",
            "deleted_at": "is.null",
            "embedding_status": "in.(pending,failed)",
            "limit": "1000",
        },
    )
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("embedding_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


async def main() -> None:
    args = parse_args()
    cfg = RuntimeConfig()
    client = SupabaseClient(cfg.supabase_url, cfg.supabase_key)
    try:
        service = RecallIndexService(client, cfg=cfg)
        if not service.embedding_client or not service.embedding_client.enabled:
            print(
                json.dumps(
                    {"ok": False, "error": "Embedding API is not configured."},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        batch_size = max(1, min(int(args.batch_size or 50), 1000))
        max_batches = 1 if args.once else max(0, int(args.max_batches or 0))
        batch_index = 0
        error_count = 0
        total_embedded = 0
        total_failed = 0
        progress = []

        while True:
            before = await pending_counts(client)
            if not before:
                break
            if max_batches and batch_index >= max_batches:
                break

            batch_index += 1
            try:
                result = await service.embed_pending(limit=batch_size)
            except Exception as exc:
                error_count += 1
                after = await pending_counts(client)
                error_item = {
                    "batch": batch_index,
                    "before": before,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                    "after": after,
                    "errors": error_count,
                }
                progress.append(error_item)
                print(json.dumps(error_item, ensure_ascii=False))
                if error_count >= max(1, int(args.max_errors or 5)):
                    break
                if args.retry_sleep and args.retry_sleep > 0:
                    await asyncio.sleep(float(args.retry_sleep))
                continue
            total_embedded += int(result.get("embedded") or 0)
            total_failed += int(result.get("failed") or 0)
            after = await pending_counts(client)
            progress.append({"batch": batch_index, "before": before, "result": result, "after": after})
            print(json.dumps(progress[-1], ensure_ascii=False))

            if not result.get("seen") or not after:
                break
            if args.sleep and args.sleep > 0:
                await asyncio.sleep(float(args.sleep))

        print(
            json.dumps(
                {
                    "ok": total_failed == 0,
                    "batches": batch_index,
                    "embedded": total_embedded,
                    "failed": total_failed,
                    "errors": error_count,
                    "remaining": await pending_counts(client),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
