from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(int((len(ordered) - 1) * percentile), len(ordered) - 1)
    return int(ordered[index])


def _load_events(db_path: Path, *, limit: int, session_tag: str) -> list[dict[str, Any]]:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'context_window_events'"
        ).fetchone()
        if not table:
            raise SystemExit("context_window_events does not exist; deploy the window observer schema first")
        if session_tag:
            rows = conn.execute(
                """
                SELECT * FROM context_window_events
                WHERE session_tag = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (session_tag, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM context_window_events
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["detail"] = json.loads(item.get("detail_json") or "{}")
        events.append(item)
    return events


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_counts = Counter(str(event.get("event_class") or "unknown") for event in events)
    reset_counts = Counter(
        str((event.get("detail") or {}).get("context_epoch_reset_reason") or "unknown")
        for event in events
        if (event.get("detail") or {}).get("context_epoch_reset")
    )
    island_counts = Counter(
        str(((event.get("detail") or {}).get("memory_island_decision") or {}).get("decision") or "none")
        for event in events
    )
    retained = [
        int((event.get("detail") or {}).get("client_non_system_retained") or 0)
        for event in events
    ]
    protected = [
        int((event.get("detail") or {}).get("raw_tool_protection_turns") or 0)
        for event in events
    ]
    epochs = {str(event.get("epoch_id") or "") for event in events if event.get("epoch_id")}
    return {
        "events": len(events),
        "sessions": len({event.get("session_id") for event in events}),
        "epochs": len(epochs),
        "event_classes": dict(event_counts.most_common()),
        "epoch_resets": dict(reset_counts.most_common()),
        "memory_island_decisions": dict(island_counts.most_common()),
        "retained_non_system_messages": {
            "min": min(retained, default=0),
            "p50": _percentile(retained, 0.50),
            "p90": _percentile(retained, 0.90),
            "max": max(retained, default=0),
        },
        "raw_protected_human_turns": {
            "average": round(mean(protected), 2) if protected else 0,
            "max": max(protected, default=0),
        },
        "latest_at": events[0].get("created_at") if events else None,
        "oldest_at": events[-1].get("created_at") if events else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize persisted context-window observations.")
    parser.add_argument("--db", default="data/shenyu_gateway.db", help="Gateway SQLite database path")
    parser.add_argument("--limit", type=int, default=5000, help="Most recent events to inspect")
    parser.add_argument("--session-tag", default="", help="Optional exact session tag")
    parser.add_argument("--json", action="store_true", help="Emit compact JSON")
    args = parser.parse_args()

    events = _load_events(
        Path(args.db),
        limit=max(1, min(int(args.limit or 5000), 50000)),
        session_tag=args.session_tag.strip(),
    )
    summary = summarize(events)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
