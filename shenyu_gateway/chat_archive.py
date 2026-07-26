from __future__ import annotations

"""L0 verbatim chat archive.

Archives user/assistant messages from the client request window into the
Supabase `shenyu_chat_archive` table, message by message.

Archiving only from the client window means a message is archived once the
client sends it back as history — so re-rolled assistant replies, which never
return in the window, are naturally excluded. The surviving reply of a re-roll
is archived on the next request.

Dedup consults the seen-hash table in SQLite globally (recent hashes only,
recorded per session_tag for provenance): the same sliding window resent on
every request archives each message once, and a window handed over into a new
session — PWA history handoff, cold-start bridge — does not re-archive the
carried history. A genuinely repeated message months later is archived again
as a new event once its hash ages out of the retention window.

event_at is the client-local send time. User messages carry it themselves:
the PWA tail status suffix (第N天 anchors the year) or the legacy Operit time
markers. Assistant replies inherit the time of the user message right before
them in the window. The stored `thread` column is provenance only — the
archive reader shows one merged timeline.
"""

import asyncio
import hashlib
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from .client_extra import parse_pwa_status_suffix_time
from .context_layers import _strip_client_extra_bundle_text
from .runtime import dt_to_iso, iso_now, logger

CHAT_ARCHIVE_TABLE = "shenyu_chat_archive"

_CLIENT_CURRENT_TIME_RE = re.compile(
    r"【当前时间】\s*\n(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})"
)
_CLIENT_ATTACHMENT_FILENAME_TIME_RE = re.compile(
    r'filename="Time:(?P<hour>\d{1,2}):(?P<minute>\d{2})\s+(?P<day>\d{1,2})/(?P<year>\d{4})/(?P<month>\d{1,2})"'
)
_NUMBERED_TRANSCRIPT_RE = re.compile(r"^#\d+:\s*", re.MULTILINE)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(part for part in parts if part).strip()
    return ""


def _content_hash(role: str, text: str) -> str:
    return hashlib.sha256(f"{role}\n{text}".encode("utf-8")).hexdigest()


def _client_time_from_text(text: str, *, now: Optional[datetime] = None) -> Optional[str]:
    """Extract the client-stamped local time and return UTC ISO when present.

    PWA tail status suffix first (the live client), then the legacy Operit
    markers for old windows. ``now`` anchors the no-第N天 year-inference
    fallback — the backfill passes the window's own historical time.
    """
    if not text:
        return None
    stamped = parse_pwa_status_suffix_time(text, now=now)
    if stamped is not None:
        return dt_to_iso(stamped)
    match = _CLIENT_CURRENT_TIME_RE.search(text)
    if match:
        raw = f"{match.group('date')}T{match.group('time')}"
    else:
        match = _CLIENT_ATTACHMENT_FILENAME_TIME_RE.search(text)
        if not match:
            return None
        raw = (
            f"{int(match.group('year')):04d}-"
            f"{int(match.group('month')):02d}-"
            f"{int(match.group('day')):02d}T"
            f"{int(match.group('hour')):02d}:{match.group('minute')}:00"
        )
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # Operit's injected clock is the client local clock. The current client is
    # Asia/Shanghai; keep this path explicit rather than treating it as UTC.
    dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt_to_iso(dt.astimezone(timezone.utc))


def _looks_like_numbered_transcript(text: str) -> bool:
    stripped = (text or "").lstrip()
    return bool(_NUMBERED_TRANSCRIPT_RE.match(stripped))


def derive_thread(session_tag: str) -> str:
    tag = (session_tag or "").strip()
    if not tag or tag in {"default", "main"}:
        return "main"
    return tag


class ChatArchiveService:
    def __init__(self, store: Any, supabase: Any, cfg: Any):
        self.store = store
        self.supabase = supabase
        self.cfg = cfg

    def enabled(self) -> bool:
        return bool(
            getattr(self.cfg, "enable_chat_archive", True)
            and self.supabase
            and self.store
        )

    async def archive_window(
        self,
        *,
        session_tag: str,
        client_name: Optional[str],
        messages: list[dict],
        event_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Archive unseen user/assistant messages from one client window."""
        if not self.enabled():
            return {"archived": 0}

        thread = derive_thread(session_tag)
        candidates: list[dict] = []
        latest_client_event_at = event_at
        for msg in messages or []:
            role = msg.get("role")
            if role not in {"user", "assistant"}:
                continue
            # Skip tool-call shells without visible text.
            text = _message_text(msg.get("content"))
            if not text:
                continue
            # Only user messages move the clock: the stamps are client-injected
            # into user text, and an assistant reply merely *quoting* an old
            # suffix must not drag its neighbours to that quoted moment.
            # Assistant replies inherit the preceding user message's time.
            client_event_at = _client_time_from_text(text) if role == "user" else None
            if client_event_at:
                latest_client_event_at = client_event_at
            text, _ = _strip_client_extra_bundle_text(text)
            if not text:
                continue
            if _looks_like_numbered_transcript(text):
                continue
            candidates.append(
                {
                    "role": role,
                    "content": text,
                    "content_hash": _content_hash(role, text),
                    "event_at": client_event_at or latest_client_event_at,
                }
            )
        if not candidates:
            return {"archived": 0}

        unseen = self.store.filter_unseen_archive_hashes(
            [item["content_hash"] for item in candidates]
        )
        if not unseen:
            return {"archived": 0}

        # Keep first occurrence per unseen hash, preserving window order.
        # archived_at gets one microsecond per row on top of the batch time so
        # that (event_at, archived_at) sorting replays the window order even
        # when several rows share one inherited event_at.
        rows: list[dict] = []
        taken: set[str] = set()
        event_at = event_at or iso_now()
        archived_base = datetime.now(timezone.utc)
        for item in candidates:
            digest = item["content_hash"]
            if digest not in unseen or digest in taken:
                continue
            taken.add(digest)
            rows.append(
                {
                    "session_tag": session_tag,
                    "thread": thread,
                    "client_name": client_name,
                    "role": item["role"],
                    "content": item["content"],
                    "content_hash": digest,
                    "event_at": item.get("event_at") or event_at,
                    "archived_at": dt_to_iso(archived_base + timedelta(microseconds=len(rows))),
                }
            )

        await self.supabase.insert_many(CHAT_ARCHIVE_TABLE, rows)
        self.store.mark_archive_hashes_seen(
            session_tag,
            [row["content_hash"] for row in rows],
            keep_recent=getattr(self.cfg, "chat_archive_seen_retention", 10000),
        )
        return {"archived": len(rows), "thread": thread}


async def archive_window_safely(service: ChatArchiveService, **kwargs) -> None:
    """Fire-and-forget wrapper: archive failures must never affect chat flow."""
    try:
        result = await service.archive_window(**kwargs)
        if result.get("archived"):
            logger.info("[ChatArchive] archived=%s thread=%s", result["archived"], result.get("thread"))
    except asyncio.CancelledError:
        # A retained task should not be GC-cancelled, but surface it if it ever is.
        logger.warning("[ChatArchive] archive task cancelled before completion")
        raise
    except Exception:
        logger.exception("[ChatArchive] archive pass failed")
