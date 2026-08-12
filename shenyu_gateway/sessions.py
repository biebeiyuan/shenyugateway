from __future__ import annotations

from .config import RuntimeConfig
from .private_capture import restore_assistant_echo
from .runtime import json_dumps
from .store import GatewayStore
from .utils import normalize_text


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
        latest_user = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                latest_user = msg
                break
        if latest_user is None:
            self.store.touch_session(session_id, message_increment=0)
            return

        content = normalize_text(latest_user.get("content"))
        self.store.append_message(session_id=session_id, role="user", content=content)
        self.store.touch_session(session_id, message_increment=1)

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

    def log_assistant_output(self, session_id: str, message: dict, *, echo: str = ""):
        content = restore_assistant_echo(message.get("content"), echo)
        self.store.append_message(session_id=session_id, role="assistant", content=content)
        self.store.touch_session(session_id, message_increment=1)

    def recent_tail(self, session_id: str, limit: int = 4) -> list[dict]:
        rows = self.store.get_recent_messages(session_id, limit=limit)
        tail = []
        for row in rows:
            if row["role"] == "tool":
                continue
            tail.append({"role": row["role"], "content": row["content"]})
        return tail
