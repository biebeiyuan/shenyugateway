from __future__ import annotations

import json
from typing import Any, Optional

from .chat_archive import parse_archive_event
from .private_capture import restore_assistant_echo
from .runtime import json_dumps, logger
from .utils import normalize_text


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return normalize_text(message.get("content"))
    return ""


def completion_snapshot_messages(base_messages: list[dict], assistant_content: Any) -> list[dict]:
    messages = json.loads(json_dumps(base_messages or []))
    assistant_text = normalize_text(assistant_content).strip()
    if not assistant_text:
        return messages
    if messages:
        last = messages[-1]
        if last.get("role") == "assistant" and normalize_text(last.get("content")).strip() == assistant_text:
            return messages
    messages.append({"role": "assistant", "content": assistant_text})
    return messages


def write_completion_context_snapshot(
    store: Any,
    meta: dict,
    assistant_content: Any,
    echo: str = "",
) -> Optional[dict]:
    if store is None or not meta:
        return None
    session = meta.get("session") or {}
    session_id = session.get("id")
    session_tag = session.get("session_tag")
    if not session_id or not session_tag:
        return None
    base_messages = meta.get("snapshot_messages") or []
    if not base_messages:
        return None

    messages = completion_snapshot_messages(base_messages, restore_assistant_echo(assistant_content, echo))
    event = parse_archive_event(meta.get("reply_archive_event"))
    try:
        media = store.message_media(session_tag, event["id"], "assistant") if event else []
    except Exception:
        logger.warning("[Album] 完成快照暂时无法补图，仍保存文字", exc_info=True)
        media = []
    if media and len(messages) == len(base_messages):
        messages.append({"role": "assistant", "content": normalize_text(assistant_content)})
    if event and len(messages) > len(base_messages):
        messages[-1]["archive_event"] = event
        if media:
            messages[-1]["media"] = media
    latest_user_text = meta.get("snapshot_latest_user_text") or _latest_user_text(messages)
    return store.write_request_context_snapshot(
        session_id=session_id,
        session_tag=session_tag,
        client_name=session.get("client_name"),
        messages=messages,
        latest_user_text=latest_user_text,
    )
