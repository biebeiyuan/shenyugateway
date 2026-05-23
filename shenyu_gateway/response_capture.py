from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, Optional

from .runtime import logger


class AssistantTagFilter:
    """Filter private assistant tags from streamed/non-streamed replies."""

    TAGS = ("heartbeat", "mem")
    HEARTBEAT_OPEN_RE = re.compile(r"<\s*heartbeat(?:\s[^>]*)?>", flags=re.I)
    HEARTBEAT_CLOSE_RE = re.compile(r"<\s*/\s*heartbeat\s*>", flags=re.I)

    def __init__(self):
        self._buffer = ""
        self._active_tag = ""
        self._active_close = ""
        self._active_open = ""
        self._active_attrs: dict[str, str] = {}
        self._active_parts: list[str] = []
        self._captured: dict[str, list[Any]] = {tag: [] for tag in self.TAGS}

    def _find_next_open_tag(self) -> tuple[int, str, int, str, dict[str, str]] | None:
        """Find the earliest complete open tag in the current buffer."""
        candidates: list[tuple[int, str, int, str, dict[str, str]]] = []

        mem_open = re.search(r"\[mem(?:\s[^\]]*)?\]", self._buffer, flags=re.I)
        if mem_open:
            open_text = mem_open.group(0)
            tag_start = open_text.lower().find("[mem")
            attr_text = open_text[tag_start + 4:-1] if tag_start >= 0 else ""
            candidates.append((mem_open.start(), "mem", mem_open.end(), "[/mem]", self._parse_attrs(attr_text)))

        heartbeat_open = self.HEARTBEAT_OPEN_RE.search(self._buffer)
        if heartbeat_open:
            candidates.append((heartbeat_open.start(), "heartbeat", heartbeat_open.end(), "</heartbeat>", {}))

        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])

    def _parse_attrs(self, raw: str) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for match in re.finditer(r"([\w:-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\]]+)", raw or ""):
            value = match.group(2).strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            attrs[match.group(1).lower()] = value.strip()
        return attrs

    def _meaningful_mem_content(self, content: Any) -> str:
        text = str(content or "").strip()
        if not text:
            return ""
        if not re.sub(r"[\W_]+", "", text, flags=re.UNICODE):
            return ""
        return text

    def _capture_active(self, content: str):
        self._active_parts.append(content)

    def _finish_active_capture(self):
        content = "".join(self._active_parts)
        if self._active_tag == "mem":
            self._captured["mem"].append({"content": content, "attrs": dict(self._active_attrs)})
        else:
            self._captured[self._active_tag].append(content)
        self._active_parts = []

    def _reset_active(self):
        self._active_tag = ""
        self._active_close = ""
        self._active_open = ""
        self._active_attrs = {}
        self._active_parts = []

    def _strip_heartbeat_blocks(self, text: str) -> str:
        """Keep visible text while still capturing heartbeat blocks inside it."""
        if not text:
            return ""
        output: list[str] = []
        pos = 0
        while pos < len(text):
            open_match = self.HEARTBEAT_OPEN_RE.search(text, pos)
            if not open_match:
                output.append(text[pos:])
                break
            output.append(text[pos:open_match.start()])
            close_match = self.HEARTBEAT_CLOSE_RE.search(text, open_match.end())
            if not close_match:
                heartbeat = text[open_match.end():].strip()
                if heartbeat:
                    self._captured["heartbeat"].append(heartbeat)
                break
            heartbeat = text[open_match.end():close_match.start()].strip()
            if heartbeat:
                self._captured["heartbeat"].append(heartbeat)
            pos = close_match.end()
        return "".join(output)

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buffer += text
        output: list[str] = []
        while self._buffer:
            if self._active_tag:
                lower = self._buffer.lower()
                close_tag = self._active_close
                close_idx = lower.find(close_tag)
                if close_idx >= 0:
                    self._capture_active(self._buffer[:close_idx])
                    self._finish_active_capture()
                    self._buffer = self._buffer[close_idx + len(close_tag):]
                    self._reset_active()
                    continue
                keep = len(close_tag) - 1
                if len(self._buffer) > keep:
                    self._capture_active(self._buffer[:-keep])
                    self._buffer = self._buffer[-keep:]
                break

            found = self._find_next_open_tag()
            if found:
                open_idx, tag, open_end, close_tag, attrs = found
                open_text = self._buffer[open_idx:open_end]
                output.append(self._buffer[:open_idx])
                self._buffer = self._buffer[open_end:]
                self._active_tag = tag
                self._active_close = close_tag
                self._active_open = open_text if tag == "mem" else ""
                self._active_attrs = attrs
                self._active_parts = []
                continue

            tail_start = max(self._buffer.rfind("<"), self._buffer.rfind("["))
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
        if self._active_tag:
            if self._active_tag == "mem":
                visible = self._active_open + "".join(self._active_parts) + self._buffer
                self._reset_active()
                self._buffer = ""
                return self._strip_heartbeat_blocks(visible)
            self._capture_active(self._buffer)
            self._finish_active_capture()
            self._buffer = ""
            self._reset_active()
            return ""
        remaining = self._buffer
        self._buffer = ""
        return remaining

    def get_heartbeat(self) -> str:
        return "".join(self._captured.get("heartbeat") or []).strip()

    def get_memories(self) -> list[dict[str, Any]]:
        parts = self._captured.get("mem") or []
        memories: list[dict[str, Any]] = []
        for item in parts:
            if isinstance(item, dict):
                content = self._meaningful_mem_content(item.get("content"))
                if content:
                    memories.append({"content": content, "attrs": item.get("attrs") or {}})
            else:
                content = self._meaningful_mem_content(item)
                if content:
                    memories.append({"content": content, "attrs": {}})
        return memories


def split_private_assistant_tags(content: str) -> tuple[str, str, list[dict[str, Any]]]:
    tag_filter = AssistantTagFilter()
    clean_content = tag_filter.feed(content or "") + tag_filter.flush()
    return clean_content, tag_filter.get_heartbeat(), tag_filter.get_memories()


def clean_text_from_filter_source(content: str) -> str:
    tag_filter = AssistantTagFilter()
    return tag_filter.feed(content or "") + tag_filter.flush()


def store_heartbeat(
    *,
    store: Any,
    session_id: str,
    session: dict,
    content: str,
    is_hisense_session: Callable[[dict], bool],
) -> bool:
    heartbeat_content = (content or "").strip()
    if not heartbeat_content or store is None:
        return False
    msg_count = int(session.get("message_count") or 0)
    is_hisense = is_hisense_session(session)
    store.append_heartbeat(
        session_id,
        heartbeat_content,
        turn_number=msg_count,
        hisense=is_hisense,
    )
    log_tag = "HisenseHeartbeat" if is_hisense else "Heartbeat"
    logger.info("[%s] 写入心跳 (%d chars) session=%s", log_tag, len(heartbeat_content), session_id[:8])
    return True


def schedule_inline_memory_capture(
    *,
    enabled: bool,
    inline_memories: list[Any],
    capture: Callable[[], Any],
) -> bool:
    if not enabled or not inline_memories:
        return False
    try:
        asyncio.create_task(capture())
        return True
    except RuntimeError:
        logger.warning("[InlineMemory] failed to schedule inline memory capture")
        return False
