from __future__ import annotations

import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.recall import RECALL_INDEX_TABLE
from shenyu_gateway.supabase import SupabaseClient


def summarize_numeric(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = []
    missing = 0
    zero = 0
    for row in rows:
        value = row.get(field)
        if value is None:
            missing += 1
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            missing += 1
            continue
        if number == 0:
            zero += 1
        values.append(number)
    if not values:
        return {"count": 0, "missing": missing, "zero": zero}
    return {
        "count": len(values),
        "missing": missing,
        "zero": zero,
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "mean": round(sum(values) / len(values), 3),
    }


def sample_row(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if key in row}


async def main() -> None:
    cfg = RuntimeConfig()
    client = SupabaseClient(cfg.supabase_url, cfg.supabase_key)
    try:
        report: dict[str, Any] = {}

        memories = await client.query(
            "memories",
            {"select": "id,title,importance,weight,is_deleted,date,updated_at", "limit": "300"},
        )
        report["memories"] = {
            "rows": len(memories),
            "importance": summarize_numeric(memories, "importance"),
            "weight": summarize_numeric(memories, "weight"),
            "sample": sample_row(memories[0], ["title", "importance", "weight", "is_deleted", "date"]) if memories else {},
        }

        atomic = await client.query(
            "atomic_memories",
            {"select": "id,subject,memory_type,importance,heat,status,updated_at", "limit": "300"},
        )
        report["atomic_memories"] = {
            "rows": len(atomic),
            "importance": summarize_numeric(atomic, "importance"),
            "heat": summarize_numeric(atomic, "heat"),
            "sample": sample_row(atomic[0], ["subject", "memory_type", "importance", "heat", "status"]) if atomic else {},
        }

        notes = await client.query(
            "shenyu_mem_notes",
            {"select": "id,mem_type,status,trigger_count,updated_at", "limit": "300"},
        )
        report["shenyu_mem_notes"] = {
            "rows": len(notes),
            "trigger_count": summarize_numeric(notes, "trigger_count"),
            "sample": sample_row(notes[0], ["mem_type", "status", "trigger_count"]) if notes else {},
        }

        index_rows = await client.query(
            RECALL_INDEX_TABLE,
            {
                "select": "source_type,source_table,importance,status,visibility,title",
                "deleted_at": "is.null",
                "limit": "1000",
            },
        )
        by_source: dict[str, list[dict[str, Any]]] = {}
        for row in index_rows:
            by_source.setdefault(row.get("source_type") or "unknown", []).append(row)
        report["recall_index"] = {
            "rows": len(index_rows),
            "by_source": {
                source: {
                    "rows": len(rows),
                    "importance": summarize_numeric(rows, "importance"),
                    "sample": sample_row(rows[0], ["source_table", "title", "importance", "status", "visibility"]) if rows else {},
                }
                for source, rows in sorted(by_source.items())
            },
        }

        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
