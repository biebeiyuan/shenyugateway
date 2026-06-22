from __future__ import annotations

from typing import Any, Optional

from .runtime import logger
from .response_capture import split_private_assistant_tags
from .utils import normalize_text as _normalize_text


EMPTY_VISIBLE_ASSISTANT_REPLY = "沈予已记录。"


def mark_context_consumed(meta: dict, *, store: Any):
    if meta.get("_context_consumed") or store is None:
        return
    meta["_context_consumed"] = True
    try:
        package = meta.get("package") or {}
        session = meta.get("session") or {}
        heartbeat_ids = [str(item) for item in package.get("heartbeat_pending_ids") or [] if item]
        if heartbeat_ids:
            store.mark_heartbeats_injected(heartbeat_ids=heartbeat_ids)
            logger.info(
                "[Heartbeat] 标记 %d 条全局心跳已注入 (session=%s)",
                len(heartbeat_ids),
                str(session.get("id") or "")[:8],
            )

        hisense_heartbeat_ids = [str(item) for item in package.get("hisense_heartbeat_pending_ids") or [] if item]
        if hisense_heartbeat_ids:
            store.mark_heartbeats_injected(heartbeat_ids=hisense_heartbeat_ids, hisense=True)
            logger.info("[HisenseHeartbeat] 标记 %d 条海信心跳已注入", len(hisense_heartbeat_ids))

        cold_start_snapshot = meta.get("cold_start_snapshot")
        bridge_count = int((meta.get("client_message_window") or {}).get("cold_start_bridge_messages") or 0)
        if cold_start_snapshot and bridge_count > 0:
            store.mark_cold_start_injected(cold_start_snapshot["id"])

        pending_ids = [str(item) for item in meta.get("pending_gateway_tool_turn_ids") or [] if item]
        if pending_ids:
            marked = store.mark_pending_gateway_tool_turns_consumed(pending_ids)
            logger.info("[GatewayTool] 标记 %d 个 mixed pending transcript 已消费", marked)
    except Exception:
        logger.exception("Failed to mark injected context as consumed")


def is_free_time_fallback_context(latest_user_text: str) -> bool:
    text = latest_user_text or ""
    lower = text.lower()
    if "自由时间" in text or "free_time" in lower or "free-time" in lower:
        return True
    return "proxy_sender" in lower and "沈予" in text and ("提醒" in text or "自动" in text)


def private_capture_kinds(
    *,
    heartbeat_content: str = "",
    inline_memories: Optional[list[dict[str, Any]]] = None,
    inline_stars: Optional[list[dict[str, Any]]] = None,
    mem_note_written: bool = False,
) -> list[str]:
    kinds: list[str] = []
    if (heartbeat_content or "").strip():
        kinds.append("heartbeat")
    if mem_note_written or bool(inline_memories):
        kinds.append("mem")
    if bool(inline_stars):
        kinds.append("star")
    return kinds


def private_capture_fallback_text(latest_user_text: str, stored_kinds: list[str]) -> tuple[str, str]:
    context = "free_time" if is_free_time_fallback_context(latest_user_text) else "generic"
    prefix = "沈予在自由时间" if context == "free_time" else "沈予已记录"
    if stored_kinds:
        return f"{prefix} · 已记录私有块 {' + '.join(stored_kinds)}", context
    if context == "free_time":
        return f"{prefix} · 已记录", context
    return EMPTY_VISIBLE_ASSISTANT_REPLY, context


def ensure_visible_assistant_content(
    assistant_message: dict,
    fallback_text: str = EMPTY_VISIBLE_ASSISTANT_REPLY,
) -> bool:
    if assistant_message.get("tool_calls"):
        return False
    if _normalize_text(assistant_message.get("content")).strip():
        return False
    assistant_message["content"] = fallback_text
    return True


def finalize_assistant_private_content(
    assistant_message: dict,
    *,
    latest_user_text: str = "",
    mem_note_written: bool = False,
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    clean_content, heartbeat_content, inline_memories, inline_stars = split_private_assistant_tags(
        _normalize_text(assistant_message.get("content"))
    )
    if heartbeat_content or inline_memories or inline_stars:
        assistant_message["content"] = clean_content
    stored_kinds = private_capture_kinds(
        heartbeat_content=heartbeat_content,
        inline_memories=inline_memories,
        inline_stars=inline_stars,
        mem_note_written=mem_note_written,
    )
    fallback_text, fallback_context = private_capture_fallback_text(latest_user_text, stored_kinds)
    fallback_applied = ensure_visible_assistant_content(assistant_message, fallback_text)
    fallback_meta = {
        "applied": fallback_applied,
        "text": fallback_text if fallback_applied else "",
        "kinds": stored_kinds if fallback_applied else [],
        "context": fallback_context if fallback_applied else "",
    }
    return _normalize_text(assistant_message.get("content")), heartbeat_content, inline_memories, inline_stars, fallback_meta
