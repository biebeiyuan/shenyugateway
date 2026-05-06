from __future__ import annotations

from typing import Optional

from .config import RuntimeConfig
from .runtime import json_dumps
from .store import GatewayStore


def normalize_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
        return "\n".join(part for part in parts if part)
    return str(content)


def shorten(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


class SessionManager:
    def __init__(self, store: GatewayStore, cfg: RuntimeConfig):
        self.store = store
        self.cfg = cfg

    def open_session(self, session_tag: str, client_name: str) -> dict:
        return self.store.get_or_create_session(session_tag=session_tag, client_name=client_name)

    def is_first_turn(self, session: dict) -> bool:
        return int(session.get("message_count") or 0) == 0

    def log_input_messages(self, session_id: str, messages: list[dict]):
        logged_count = 0
        for msg in messages:
            role = msg.get("role", "")
            if role not in {"user", "assistant", "tool"}:
                continue
            content = normalize_text(msg.get("content"))
            tool_name = msg.get("name") if role == "tool" else None
            self.store.append_message(
                session_id=session_id,
                role=role,
                content=content,
                tool_name=tool_name,
                tool_args=None,
                tool_result_summary=shorten(content, 180) if role == "tool" else None,
            )
            logged_count += 1
        self.store.touch_session(session_id, message_increment=logged_count)

    def log_tool_result(self, session_id: str, tool_name: str, args: dict, result: dict):
        content = json_dumps(result)
        self.store.append_message(
            session_id=session_id,
            role="tool",
            content=content,
            tool_name=tool_name,
            tool_args=args,
            tool_result_summary=shorten(content, 200),
        )
        self.store.touch_session(session_id, message_increment=1)

    def log_assistant_output(self, session_id: str, message: dict):
        content = normalize_text(message.get("content"))
        self.store.append_message(session_id=session_id, role="assistant", content=content)
        self.store.touch_session(session_id, message_increment=1)

    def latest_summary(self, session_id: str) -> Optional[str]:
        row = self.store.latest_summary(session_id)
        return row["content"] if row else None

    def latest_frozen_window(self, session_id: str) -> Optional[list[dict]]:
        row = self.store.latest_frozen_window(session_id)
        return row["messages"] if row else None

    def recent_tail(self, session_id: str, limit: int = 4) -> list[dict]:
        rows = self.store.get_recent_messages(session_id, limit=limit)
        tail = []
        for row in rows:
            if row["role"] == "tool":
                continue
            tail.append({"role": row["role"], "content": row["content"]})
        return tail

    def maybe_refresh_summary(self, session_id: str):
        count = self.store.get_message_count(session_id)
        if count == 0 or count % max(self.cfg.summary_update_every_messages, 1) != 0:
            return
        messages = self.store.get_recent_messages(session_id, limit=12)
        content = self._summarize_messages(messages)
        self.store.write_summary(
            session_id=session_id,
            summary_type="rolling",
            content=content,
            covered_from=max(count - len(messages) + 1, 1),
            covered_to=count,
        )

    def maybe_refresh_frozen_window(self, session_id: str):
        count = self.store.get_message_count(session_id)
        if count == 0 or count % max(self.cfg.freeze_every_messages, 1) != 0:
            return
        messages = self.store.get_recent_messages(session_id, limit=max(self.cfg.freeze_tail_messages, 2))
        raw_messages = [{"role": item["role"], "content": item["content"]} for item in messages if item["role"] in {"user", "assistant"}]
        token_estimate = sum(len(item["content"] or "") for item in raw_messages) // 4
        self.store.write_frozen_window(session_id, raw_messages, token_estimate)

    def _summarize_messages(self, rows: list[dict]) -> str:
        bullets = []
        for row in rows:
            role = row.get("role")
            content = shorten(row.get("content") or "", 120)
            if not content:
                continue
            prefix = "User" if role == "user" else "Assistant"
            bullets.append(f"- {prefix}: {content}")
        if not bullets:
            return "No rolling summary yet."
        return "Recent thread summary:\n" + "\n".join(bullets)
