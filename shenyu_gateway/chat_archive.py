from __future__ import annotations

"""L0 chat capture: immutable event identity, independently projected text.

PWA archive_event carries a stable per-version ID and original creation time.
The selected destination ignores repeated IDs without rewriting originals or
reviving tombstones. Partial/recovering replies defer capture. Replies still
enter when the client returns the selected version in its next request; this
is not an immediate-completion archive or a provider context/history source.

Legacy clients have no trustworthy per-message identity. They keep the global,
bounded SQLite seen-hash compatibility path, dual-reading known old echo
separator hashes. No IDs/times are invented for restored legacy messages.
Their old timestamp-marker/inherited-clock fallback remains approximate.
See REQUEST_CONTEXT.md, Chat archive (L0 source of truth), for the wire,
identity/projection, and migration boundaries.
"""

import asyncio
import hashlib
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from .client_extra import parse_pwa_status_suffix_time
from .context_layers import _strip_client_extra_bundle_text
from .echo import strip_leading_echo
from .response_capture import split_private_assistant_tags
from .local_chat_archive import local_archive_for_config
from .runtime import LOCAL_DAY_TZ, dt_to_iso, iso_now, logger

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


def parse_archive_event(value: Any) -> Optional[dict[str, str]]:
    """Optional client event identity, never inferred from display text.

    Invalid archive-only metadata must not reject the conversation request.
    Old clients/messages remain on the explicitly legacy content-hash path.
    """
    if not isinstance(value, dict):
        return None
    ident, stamp = value.get("id"), value.get("event_at")
    if not isinstance(ident, str) or not ident or len(ident) > 160:
        return None
    if not isinstance(stamp, str) or len(stamp) > 64:
        return None
    try:
        instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return None
        return {"id": ident, "event_at": dt_to_iso(instant.astimezone(timezone.utc))}
    except (ValueError, OverflowError):
        return None


def archive_visible_text(role: str, content: Any) -> str:
    """One pure archive projection. Strip private parts, THEN trim boundaries.

    Do not use this projection as the identity of a modern message. Adding a
    stripper changes only what is captured for new events, not existing IDs.
    Interior whitespace/Markdown and user-quoted private tags are untouched.
    """
    text, _ = _strip_client_extra_bundle_text(_message_text(content))
    if role == "assistant":
        # Removing one private block may expose another leading block. Reach a
        # fixed point so block order never changes the captured public body.
        while True:
            visible, _ = split_private_assistant_tags(strip_leading_echo(text))
            if visible == text:
                break
            text = visible
    return text.strip()


def legacy_archive_hashes(role: str, content: Any, visible: str) -> set[str]:
    """Dual-read known pre-fix representations; never rewrite archived originals.

    Old echo capture trimmed BEFORE stripping the tag, leaving the separator.
    Include the old pipeline's exact output and the deployed echo separators
    even when a returning client has already stripped them. This is legacy
    compatibility, not a universal identity mechanism for arbitrary transforms.
    """
    old, _ = _strip_client_extra_bundle_text(_message_text(content))
    if role == "assistant":
        old = strip_leading_echo(old)
    texts = {old, visible}
    if role == "assistant":
        texts.update(prefix + visible for prefix in ("\n", "\n\n", "\r\n", "\r\n\r\n"))
    return {_content_hash(role, text) for text in texts if text}


def _archive_event_row_id(role: str, event: dict[str, str]) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
        "shenyugateway/archive-event/v1/" + role + "/" + event["id"]))


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
    dt = dt.replace(tzinfo=LOCAL_DAY_TZ)
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
        self._archive_destination = self._destination()
        self._use_local_archive = self._archive_destination[0] == "sqlite"

    def _destination(self) -> tuple:
        return (getattr(self.cfg, "chat_archive_backend", "supabase"),
                getattr(self.cfg, "chat_archive_db_path", ""),
                getattr(self.cfg, "gateway_db_path", ""))

    def _check_destination(self) -> None:
        # Unsupported config mutation must not silently switch either direction
        # midway through a pass. Admin does not accept archive deployment fields.
        if self._destination() != self._archive_destination:
            raise ValueError("Chat archive destination changed during an archive pass")

    def enabled(self) -> bool:
        return bool(
            getattr(self.cfg, "enable_chat_archive", True)
            and (self.supabase or self._use_local_archive)
            and self.store
        )

    def _append_local_rows(self, rows: list[dict]) -> int:
        # Open inside the safe archive task, not in chat preparation. A disk
        # failure after startup must not abort a conversation or mark hashes seen.
        self._check_destination()
        archive = local_archive_for_config(self.cfg)
        if archive is None:
            raise ValueError("Chat archive destination changed during an archive pass")
        return archive.append_legacy_rows(rows)

    async def archive_window(
        self,
        *,
        session_tag: str,
        client_name: Optional[str],
        messages: list[dict],
        event_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Archive unseen user/assistant messages from one client window."""
        self._check_destination()
        if not self.enabled():
            return {"archived": 0}

        thread = derive_thread(session_tag)
        candidates: list[dict] = []
        latest_client_event_at = event_at
        for msg in messages or []:
            role = msg.get("role")
            if role not in {"user", "assistant"} or msg.get("archive_pending") is True:
                # Partial/recovering replies must not consume an immutable ID.
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
            event = parse_archive_event(msg.get("archive_event"))
            if event and role == "user":
                latest_client_event_at = event["event_at"]
            original_content = msg.get("content")
            text = archive_visible_text(role, original_content)
            if not text:
                continue
            if _looks_like_numbered_transcript(text):
                continue
            candidates.append(
                {
                    "role": role,
                    "content": text,
                    "content_hash": ("event:v1:" + _archive_event_row_id(role, event)
                                     if event else _content_hash(role, text)),
                    "id": _archive_event_row_id(role, event) if event else None,
                    "legacy_hashes": legacy_archive_hashes(role, original_content, text),
                    "event_at": event["event_at"] if event else client_event_at or latest_client_event_at,
                }
            )
        if not candidates:
            return {"archived": 0}

        unseen = self.store.filter_unseen_archive_hashes(
            [digest for item in candidates if not item["id"] for digest in item["legacy_hashes"]]
        )

        # Keep first occurrence per unseen hash, preserving window order.
        # archived_at gets one microsecond per row on top of the batch time so
        # that (event_at, archived_at) sorting replays the window order even
        # when several rows share one inherited event_at.
        rows: list[dict] = []
        taken: set[str] = set()
        seen_aliases: set[str] = set()
        event_at = event_at or iso_now()
        archived_base = datetime.now(timezone.utc)
        for item in candidates:
            digest = item["content_hash"]
            if digest in taken:
                continue
            if not item["id"] and not item["legacy_hashes"].issubset(unseen):
                # A known old representation confirms this is not a new event.
                seen_aliases.add(_content_hash(item["role"], item["content"]))
                continue
            taken.add(digest)
            rows.append(
                {
                    **({"id": item["id"]} if item["id"] else {}),
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
            seen_aliases.add(_content_hash(item["role"], item["content"]))

        inserted = 0
        if rows and self._use_local_archive:
            inserted = await asyncio.to_thread(self._append_local_rows, rows)
        elif rows:
            legacy = [row for row in rows if "id" not in row]
            identified = [row for row in rows if "id" in row]
            # Do durable/idempotent writes first. If the later legacy insert
            # fails, replay cannot duplicate a modern event already committed.
            if identified:
                inserted += len(await self.supabase.insert_archive_events(CHAT_ARCHIVE_TABLE, identified))
            if legacy:
                await self.supabase.insert_many(CHAT_ARCHIVE_TABLE, legacy)
                inserted += len(legacy)
        # Only publish aliases after the write succeeded (including an ID conflict
        # proving an original/tombstone already exists). An I/O failure retries.
        self.store.mark_archive_hashes_seen(
            session_tag,
            list(seen_aliases),
            keep_recent=getattr(self.cfg, "chat_archive_seen_retention", 10000),
        )
        return {"archived": inserted, "thread": thread}


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
