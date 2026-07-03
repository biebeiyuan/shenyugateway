from __future__ import annotations

from typing import Any

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
    return "proxy_sender" in text and "沈予" in text


def is_room_mode(latest_user_text: str) -> bool:
    """Detect room mode trigger — same signals as free-time fallback, used for routing."""
    return is_free_time_fallback_context(latest_user_text)


def private_capture_kinds(*, heartbeat_content: str = "") -> list[str]:
    kinds: list[str] = []
    if (heartbeat_content or "").strip():
        kinds.append("heartbeat")
    return kinds


def private_capture_fallback_text(latest_user_text: str, stored_kinds: list[str]) -> tuple[str, str]:
    context = "free_time" if is_free_time_fallback_context(latest_user_text) else "generic"
    prefix = "沈予回家了" if context == "free_time" else "沈予已记录"
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
) -> tuple[str, str, dict[str, Any]]:
    """Strip heartbeat from assistant content. Returns (clean_content, heartbeat, fallback_meta)."""
    clean_content, heartbeat_content = split_private_assistant_tags(
        _normalize_text(assistant_message.get("content"))
    )
    if heartbeat_content:
        assistant_message["content"] = clean_content
    stored_kinds = private_capture_kinds(heartbeat_content=heartbeat_content)
    fallback_text, fallback_context = private_capture_fallback_text(latest_user_text, stored_kinds)
    fallback_applied = bool(stored_kinds) and ensure_visible_assistant_content(assistant_message, fallback_text)
    fallback_meta = {
        "applied": fallback_applied,
        "text": fallback_text if fallback_applied else "",
        "kinds": stored_kinds if fallback_applied else [],
        "context": fallback_context if fallback_applied else "",
    }
    return _normalize_text(assistant_message.get("content")), heartbeat_content, fallback_meta
