from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ECHO_OPEN_MARKER = "[回响]"
ECHO_CLOSE_MARKER = "[/回响]"

_SEEK = 0
_IN = 1
_PASS = 2


@dataclass(frozen=True)
class EchoSplit:
    visible: str
    echo: str
    matched: bool
    closed: bool


class EchoStreamFilter:
    """Split one leading ``[回响]`` block from a streamed assistant reply."""

    def __init__(
        self,
        open_marker: str = ECHO_OPEN_MARKER,
        close_marker: str = ECHO_CLOSE_MARKER,
    ) -> None:
        if not open_marker or not close_marker:
            raise ValueError("echo markers must be non-empty")
        if open_marker[0].isspace():
            raise ValueError("echo open marker must not start with whitespace")
        self.open_marker = open_marker
        self.close_marker = close_marker
        self._state = _SEEK
        self._buffer = ""
        self._echo_parts: list[str] = []
        self._matched = False
        self._closed = False

    @property
    def matched(self) -> bool:
        return self._matched

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def echo_text(self) -> str:
        return "".join(self._echo_parts)

    @staticmethod
    def _overlap_length(text: str, marker: str) -> int:
        max_length = min(len(text), len(marker) - 1)
        for length in range(max_length, 0, -1):
            if text.endswith(marker[:length]):
                return length
        return 0

    def feed(self, text: str) -> tuple[str, str, bool]:
        if not text:
            return "", "", False
        if self._state == _PASS:
            return text, "", False

        self._buffer += text
        visible_parts: list[str] = []
        echo_parts: list[str] = []
        closed_now = False

        while self._buffer and self._state != _PASS:
            if self._state == _SEEK:
                leading_length = len(self._buffer) - len(self._buffer.lstrip())
                candidate = self._buffer[leading_length:]
                if not candidate:
                    break
                if self.open_marker.startswith(candidate):
                    break
                if candidate.startswith(self.open_marker):
                    self._buffer = candidate[len(self.open_marker):]
                    self._state = _IN
                    self._matched = True
                    continue
                visible_parts.append(self._buffer)
                self._buffer = ""
                self._state = _PASS
                break

            close_index = self._buffer.find(self.close_marker)
            if close_index >= 0:
                echo_part = self._buffer[:close_index]
                if echo_part:
                    echo_parts.append(echo_part)
                    self._echo_parts.append(echo_part)
                self._buffer = self._buffer[close_index + len(self.close_marker):]
                self._state = _PASS
                self._closed = True
                closed_now = True
                if self._buffer:
                    visible_parts.append(self._buffer)
                    self._buffer = ""
                break

            overlap = self._overlap_length(self._buffer, self.close_marker)
            emit_length = len(self._buffer) - overlap
            if emit_length <= 0:
                break
            echo_part = self._buffer[:emit_length]
            echo_parts.append(echo_part)
            self._echo_parts.append(echo_part)
            self._buffer = self._buffer[emit_length:]

        return "".join(visible_parts), "".join(echo_parts), closed_now

    def finish(self) -> tuple[str, str]:
        if self._state == _SEEK:
            visible = self._buffer
            self._buffer = ""
            self._state = _PASS
            return visible, ""
        if self._state == _IN:
            echo = self._buffer
            if echo:
                self._echo_parts.append(echo)
            self._buffer = ""
            self._state = _PASS
            return "", echo
        return "", ""


def split_leading_echo(content: str) -> EchoSplit:
    echo_filter = EchoStreamFilter()
    visible, echo, _ = echo_filter.feed(content or "")
    final_visible, final_echo = echo_filter.finish()
    return EchoSplit(
        visible=visible + final_visible,
        echo=echo + final_echo,
        matched=echo_filter.matched,
        closed=echo_filter.closed,
    )


def strip_leading_echo(content: str) -> str:
    split = split_leading_echo(content or "")
    return split.visible if split.matched else content or ""


def trim_assistant_echoes(
    messages: list[dict[str, Any]],
    *,
    keep_subsequent_user_turns: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep echo tags only while an assistant message is within N later user turns."""
    keep_turns = max(int(keep_subsequent_user_turns or 0), 0)
    later_user_turns = 0
    trimmed_reversed: list[dict[str, Any]] = []
    seen = 0
    stripped = 0

    for message in reversed(messages):
        clean = message
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            split = split_leading_echo(str(message.get("content") or ""))
            if split.matched:
                seen += 1
                if later_user_turns > keep_turns:
                    clean = dict(message)
                    clean["content"] = split.visible
                    stripped += 1
        trimmed_reversed.append(clean)
        if message.get("role") == "user":
            later_user_turns += 1

    return list(reversed(trimmed_reversed)), {
        "echo_keep_subsequent_user_turns": keep_turns,
        "echo_messages_seen": seen,
        "echo_messages_trimmed": stripped,
    }


def strip_all_assistant_echoes(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stripped: list[dict[str, Any]] = []
    seen = 0
    removed = 0
    for message in messages:
        if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
            stripped.append(message)
            continue
        split = split_leading_echo(str(message.get("content") or ""))
        if not split.matched:
            stripped.append(message)
            continue
        seen += 1
        clean = dict(message)
        clean["content"] = split.visible
        stripped.append(clean)
        removed += 1
    return stripped, {
        "echo_messages_seen": seen,
        "echo_messages_trimmed": removed,
    }
