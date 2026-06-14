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

from shenyu_gateway.chat_archive import (
    CHAT_ARCHIVE_TABLE,
    ChatArchiveService,
    derive_thread,
    _client_time_from_text,
    _content_hash,
    _message_text,
)
from shenyu_gateway.context_layers import _strip_client_extra_bundle_text
from shenyu_gateway.config import RuntimeConfig
from shenyu_gateway.runtime import iso_now
from shenyu_gateway.store import GatewayStore
from shenyu_gateway.supabase import SupabaseClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill shenyu_chat_archive from SQLite history.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be archived without writing.")
    parser.add_argument("--session-tag", default="", help="Limit to one session tag.")
    parser.add_argument("--batch-size", type=int, default=250, help="Supabase insert batch size.")
    parser.add_argument(
        "--ignore-supabase-existing",
        action="store_true",
        help="Only use local chat_archive_seen for dedup. By default existing Supabase hashes are skipped too.",
    )
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


async def _load_existing_archive_hashes_by_tag(
    supabase: SupabaseClient,
    session_tag_filter: str,
    page_size: int = 1000,
) -> dict[str, set[str]]:
    existing: dict[str, set[str]] = {}
    start = 0
    while True:
        params = {
            "select": "session_tag,content_hash",
            "deleted_at": "is.null",
            "order": "id.asc",
            "limit": str(page_size),
            "offset": str(start),
        }
        if session_tag_filter:
            params["session_tag"] = f"eq.{session_tag_filter}"
        rows = await supabase.query(CHAT_ARCHIVE_TABLE, params)
        for row in rows or []:
            tag = str(row.get("session_tag") or "")
            digest = str(row.get("content_hash") or "")
            if tag and digest:
                existing.setdefault(tag, set()).add(digest)
        if len(rows or []) < page_size:
            break
        start += page_size
    return existing


def _flatten_existing(existing_by_tag: dict[str, set[str]]) -> set[tuple[str, str]]:
    return {
        (tag, digest)
        for tag, hashes in existing_by_tag.items()
        for digest in hashes
    }


def _seed_seen_from_existing(store: GatewayStore, cfg: RuntimeConfig, existing_by_tag: dict[str, set[str]]) -> int:
    total = 0
    retention = getattr(cfg, "chat_archive_seen_retention", 10000)
    for tag, hashes in existing_by_tag.items():
        if not hashes:
            continue
        store.mark_archive_hashes_seen(tag, list(hashes), keep_recent=retention)
        total += len(hashes)
    return total


def _candidate_rows(
    *,
    tag: str,
    client_name: str | None,
    messages: list[dict],
    created_at: str | None,
    is_hisense: bool,
    existing: set[tuple[str, str]],
) -> list[dict]:
    rows: list[dict] = []
    event_at = created_at or iso_now()
    latest_client_event_at = event_at
    thread = derive_thread(tag, is_hisense)
    taken: set[str] = set()
    for msg in messages or []:
        role = msg.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = _message_text(msg.get("content"))
        if not text:
            continue
        client_event_at = _client_time_from_text(text)
        if client_event_at:
            latest_client_event_at = client_event_at
        text, _ = _strip_client_extra_bundle_text(text)
        if not text:
            continue
        digest = _content_hash(role, text)
        key = (tag, digest)
        if digest in taken or key in existing:
            continue
        taken.add(digest)
        rows.append(
            {
                "session_tag": tag,
                "thread": thread,
                "client_name": client_name,
                "role": role,
                "content": text,
                "content_hash": digest,
                "event_at": client_event_at or latest_client_event_at,
            }
        )
    return rows


async def _insert_batch(service: ChatArchiveService, rows: list[dict]) -> int:
    if not rows:
        return 0
    await service.supabase.insert_many(CHAT_ARCHIVE_TABLE, rows)
    by_tag: dict[str, list[str]] = {}
    for row in rows:
        by_tag.setdefault(row["session_tag"], []).append(row["content_hash"])
    for tag, hashes in by_tag.items():
        service.store.mark_archive_hashes_seen(
            tag,
            hashes,
            keep_recent=getattr(service.cfg, "chat_archive_seen_retention", 10000),
        )
    return len(rows)


async def main() -> None:
    args = parse_args()
    cfg = RuntimeConfig()
    if not (cfg.supabase_url and cfg.supabase_key):
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not configured.")
        return
    store = GatewayStore(cfg.gateway_db_path)
    supabase = SupabaseClient(cfg.supabase_url, cfg.supabase_key)
    service = ChatArchiveService(store, supabase, cfg)
    batch_size = max(1, min(int(args.batch_size or 250), 1000))

    hisense_name = (cfg.hisense_client_name or "hisense").casefold()
    total = 0
    windows = 0
    pending: list[dict] = []
    try:
        existing = set()
        if not args.ignore_supabase_existing:
            existing_by_tag = await _load_existing_archive_hashes_by_tag(supabase, args.session_tag)
            seeded = _seed_seen_from_existing(store, cfg, existing_by_tag)
            existing = _flatten_existing(existing_by_tag)
            print(f"Loaded {len(existing)} existing Supabase archive hashes.")
            if seeded:
                print(f"Seeded {seeded} existing archive hashes into local chat_archive_seen.")
        for tag, client_name, messages, _created in _iter_windows(store, args.session_tag):
            windows += 1
            is_hisense = (client_name or "").casefold() == hisense_name or (client_name or "") == "海信"
            rows = _candidate_rows(
                tag=tag,
                client_name=client_name,
                messages=messages,
                created_at=_created,
                is_hisense=is_hisense,
                existing=existing,
            )
            if args.dry_run:
                hashes = [row["content_hash"] for row in rows]
                unseen = store.filter_unseen_archive_hashes(tag, hashes)
                total += len(unseen)
                for row in rows:
                    if row["content_hash"] in unseen:
                        existing.add((row["session_tag"], row["content_hash"]))
                continue
            unseen = store.filter_unseen_archive_hashes(tag, [row["content_hash"] for row in rows])
            rows = [row for row in rows if row["content_hash"] in unseen]
            for row in rows:
                existing.add((row["session_tag"], row["content_hash"]))
            pending.extend(rows)
            if len(pending) >= batch_size:
                total += await _insert_batch(service, pending)
                print(f"+{len(pending)} (through window {windows})")
                pending = []
        if not args.dry_run and pending:
            total += await _insert_batch(service, pending)
            print(f"+{len(pending)} (final)")
    finally:
        await supabase.close()

    label = "would archive" if args.dry_run else "archived"
    print(f"Done: {label} {total} messages across {windows} windows.")


if __name__ == "__main__":
    asyncio.run(main())
