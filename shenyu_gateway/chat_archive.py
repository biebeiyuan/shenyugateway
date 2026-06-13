from __future__ import annotations

"""L0 verbatim chat archive.

Archives user/assistant messages from the client request window into the
Supabase `shenyu_chat_archive` table, message by message.

Archiving only from the client window means a message is archived once the
client sends it back as history — so re-rolled assistant replies, which never
return in the window, are naturally excluded. The surviving reply of a re-roll
is archived on the next request.

Dedup uses a per-session_tag seen-hash table in SQLite (recent hashes only),
so the same sliding window resent on every request archives each message once,
while a genuinely repeated message months later is archived again as a new event.
"""

import hashlib
from typing import Any, Optional

from .context_layers import _strip_client_extra_bundle_text
from .runtime import iso_now, logger

CHAT_ARCHIVE_TABLE = "shenyu_chat_archive"


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


def derive_thread(session_tag: str, is_hisense: bool) -> str:
    if is_hisense:
        return "hisense"
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
        is_hisense: bool,
        event_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Archive unseen user/assistant messages from one client window."""
        if not self.enabled():
            return {"archived": 0}

        thread = derive_thread(session_tag, is_hisense)
        candidates: list[dict] = []
        for msg in messages or []:
            role = msg.get("role")
            if role not in {"user", "assistant"}:
                continue
            # Skip tool-call shells without visible text.
            text = _message_text(msg.get("content"))
            if not text:
                continue
            text, _ = _strip_client_extra_bundle_text(text)
            if not text:
                continue
            candidates.append(
                {
                    "role": role,
                    "content": text,
                    "content_hash": _content_hash(role, text),
                }
            )
        if not candidates:
            return {"archived": 0}

        unseen = self.store.filter_unseen_archive_hashes(
            session_tag, [item["content_hash"] for item in candidates]
        )
        if not unseen:
            return {"archived": 0}

        # Keep first occurrence per unseen hash, preserving window order.
        rows: list[dict] = []
        taken: set[str] = set()
        event_at = event_at or iso_now()
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
                    # Window messages carry no client timestamps; dedup means a
                    # message is archived close to when it first appeared, so
                    # first-seen time is the best available event time.
                    "event_at": event_at,
                }
            )

        await self.supabase.insert_many(CHAT_ARCHIVE_TABLE, rows)
        self.store.mark_archive_hashes_seen(session_tag, [row["content_hash"] for row in rows])
        return {"archived": len(rows), "thread": thread}


async def archive_window_safely(service: ChatArchiveService, **kwargs) -> None:
    """Fire-and-forget wrapper: archive failures must never affect chat flow."""
    try:
        result = await service.archive_window(**kwargs)
        if result.get("archived"):
            logger.info("[ChatArchive] archived=%s thread=%s", result["archived"], result.get("thread"))
    except Exception:
        logger.exception("[ChatArchive] archive pass failed")
