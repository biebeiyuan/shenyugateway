from __future__ import annotations

import re
from typing import Any

from .runtime import logger


class AssistantTagFilter:
    """Filter private assistant tags (heartbeat only) from streamed/non-streamed replies."""

    HEARTBEAT_OPEN_RE = re.compile(r"<\s*heartbeat(?:\s[^>]*)?>", flags=re.I)
    HEARTBEAT_CLOSE_RE = re.compile(r"<\s*/\s*heartbeat\s*>", flags=re.I)

    def __init__(self):
        self._buffer = ""
        self._active = False
        self._active_parts: list[str] = []
        self._captured: list[str] = []

    def _consume_active_buffer(self) -> bool:
        close_match = self.HEARTBEAT_CLOSE_RE.search(self._buffer)
        if close_match:
            self._active_parts.append(self._buffer[: close_match.start()])
            self._buffer = self._buffer[close_match.end():]
            content = "".join(self._active_parts).strip()
            if content:
                self._captured.append(content)
            self._active = False
            self._active_parts = []
            return True

        tail_start = self._buffer.rfind("<")
        if tail_start > 0:
            self._active_parts.append(self._buffer[:tail_start])
            self._buffer = self._buffer[tail_start:]
        elif tail_start < 0:
            self._active_parts.append(self._buffer)
            self._buffer = ""
        return False

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buffer += text
        output: list[str] = []
        while self._buffer:
            if self._active:
                if self._consume_active_buffer():
                    continue
                break

            open_match = self.HEARTBEAT_OPEN_RE.search(self._buffer)
            if open_match:
                output.append(self._buffer[: open_match.start()])
                self._buffer = self._buffer[open_match.end():]
                self._active = True
                self._active_parts = []
                continue

            tail_start = self._buffer.rfind("<")
            if tail_start > 0:
                output.append(self._buffer[:tail_start])
                self._buffer = self._buffer[tail_start:]
            elif tail_start == 0:
                break
            else:
                output.append(self._buffer)
                self._buffer = ""
            break
        return "".join(output)

    def flush(self) -> str:
        if self._active:
            self._active_parts.append(self._buffer)
            content = "".join(self._active_parts).strip()
            if content:
                self._captured.append(content)
            self._active = False
            self._active_parts = []
            self._buffer = ""
            return ""
        remaining = self._buffer
        self._buffer = ""
        return remaining

    def get_heartbeat(self) -> str:
        return "".join(self._captured).strip()


def split_private_assistant_tags(content: str) -> tuple[str, str]:
    """Return (clean_content, heartbeat_content). Only strips heartbeat tags."""
    tag_filter = AssistantTagFilter()
    clean_content = tag_filter.feed(content or "") + tag_filter.flush()
    return clean_content, tag_filter.get_heartbeat()


def clean_text_from_filter_source(content: str) -> str:
    tag_filter = AssistantTagFilter()
    return tag_filter.feed(content or "") + tag_filter.flush()


def store_heartbeat(
    *,
    store: Any,
    session_id: str,
    session: dict,
    content: str,
) -> bool:
    heartbeat_content = (content or "").strip()
    if not heartbeat_content or store is None:
        return False
    msg_count = int(session.get("message_count") or 0)
    store.append_heartbeat(
        session_id,
        heartbeat_content,
        turn_number=msg_count,
    )
    logger.info("[Heartbeat] 写入心跳 (%d chars) session=%s", len(heartbeat_content), session_id[:8])
    return True
