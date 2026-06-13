from __future__ import annotations

"""One-off backfill of shenyu_chat_archive from existing SQLite history.

Reads raw_request_windows (primary, untrimmed) and gateway_messages
(supplementary) and pushes user/assistant texts through the same dedup
path as the live archiver. Safe to re-run: already-seen hashes are skipped.

Usage:
    python scripts/backfill_chat_archive.py            # backfill everything
    python scripts/backfill_chat_archive.py --dry-run  # count only
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json

from shenyu_gateway.chat_archive import ChatArchiveService, _content_hash, _message_text
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.store import GatewayStore
from shenyu_gateway.supabase import SupabaseClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill shenyu_chat_archive from SQLite history.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be archived without writing.")
    parser.add_argument("--session-tag", default="", help="Limit to one session tag.")
    return parser.parse_args()


def _iter_windows(store: GatewayStore, session_tag_filter: str):
    """Yield (session_tag, client_name, messages, created_at) oldest first."""
    with store._connect() as conn:
        sessions = conn.execute("SELECT id, session_tag, client_name FROM gateway_sessions").fetchall()
        for session in sessions:
            tag = session["session_tag"]
            if session_tag_filter and tag != session_tag_filter:
                continue
            # gateway_messages first: they carry accurate per-message timestamps,
            # so dedup lets them claim the event_at before whole-window stamps.
            msg_rows = conn.execute(
                """
                SELECT role, content, created_at FROM gateway_messages
                WHERE session_id = ? AND role IN ('user','assistant') AND content IS NOT NULL
                ORDER BY created_at ASC
                """,
                (session["id"],),
            ).fetchall()
            for row in msg_rows:
                if not (row["content"] or "").strip():
                    continue
                yield (
                    tag,
                    session["client_name"],
                    [{"role": row["role"], "content": row["content"]}],
                    row["created_at"],
                )
            # raw_request_windows as supplement: catches messages pruned from
            # gateway_messages; the whole window shares its snapshot time.
            rows = conn.execute(
                """
                SELECT messages_json, client_name, created_at FROM raw_request_windows
                WHERE session_id = ? ORDER BY created_at ASC
                """,
                (session["id"],),
            ).fetchall()
            for row in rows:
                try:
                    messages = json.loads(row["messages_json"] or "[]")
                except json.JSONDecodeError:
                    continue
                yield tag, row["client_name"] or session["client_name"], messages, row["created_at"]


async def main() -> None:
    args = parse_args()
    cfg = RuntimeConfig()
    if not (cfg.supabase_url and cfg.supabase_key):
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not configured.")
        return
    store = GatewayStore(cfg.gateway_db_path)
    supabase = SupabaseClient(cfg.supabase_url, cfg.supabase_key)
    service = ChatArchiveService(store, supabase, cfg)

    hisense_name = (cfg.hisense_client_name or "hisense").casefold()
    total = 0
    windows = 0
    try:
        for tag, client_name, messages, _created in _iter_windows(store, args.session_tag):
            windows += 1
            is_hisense = (client_name or "").casefold() == hisense_name or (client_name or "") == "海信"
            if args.dry_run:
                hashes = []
                for m in messages:
                    if m.get("role") not in {"user", "assistant"}:
                        continue
                    text = _message_text(m.get("content"))
                    if text:
                        hashes.append(_content_hash(m["role"], text))
                total += len(store.filter_unseen_archive_hashes(tag, hashes))
                continue
            result = await service.archive_window(
                session_tag=tag,
                client_name=client_name,
                messages=messages,
                is_hisense=is_hisense,
                event_at=_created,
            )
            archived = int(result.get("archived") or 0)
            total += archived
            if archived:
                print(f"[{tag}] +{archived} (window {windows})")
    finally:
        await supabase.close()

    label = "would archive" if args.dry_run else "archived"
    print(f"Done: {label} {total} messages across {windows} windows.")


if __name__ == "__main__":
    asyncio.run(main())
