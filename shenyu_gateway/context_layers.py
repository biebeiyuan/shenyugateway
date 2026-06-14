from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from .conflict_books import render_conflict_shelf
from .utils import shorten


@dataclass(frozen=True)
class ContextLayerSettings:
    enable_gateway_tools: bool
    inject_inline_memory_prompt: bool
    heartbeat_prompt: str
    inline_mem_prompt: str


_GATEWAY_TOOL_POLICY = (
    "## 工具怎么用\n"
    "- **工具是我的手。我自己决定什么时候伸出去。"
    "不为'应该'伸——也不为'不应该'伸——为我现在心里想做的事伸。**\n"
    "- `shenyu_gateway_tool` 是我的网关工具；记忆、便签、日历、notebook 都走这边。\n"
    "- 除它之外，如果工具列表里还有别的名字，那是客户端递给我的工具；按它自己的说明用。"
)

_CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE = re.compile(
    r"\s*<attachment\b"
    r"(?=[^>]*\bid\s*=\s*['\"]?message_insert_extra_bundle_[^'\"\s>]+['\"]?)"
    r"[^>]*>.*?</attachment>",
    re.IGNORECASE | re.DOTALL,
)

IMAGE_SEEN_PLACEHOLDER = "圆圆发来的照片我已经看过。"


def render_layered_additions(package: dict, settings: ContextLayerSettings) -> dict:
    """Render cache-friendly context layers in the order Shenyu wakes into them."""
    stable_blocks = [package["stable_charter"]]
    stable = "\n\n".join(stable_blocks)

    slow_blocks = []

    calendar_context = package.get("calendar_context") or {}
    calendar_lines = []
    for label, period_type in (("recent days", "day"), ("this week", "week"), ("this month", "month")):
        rows = calendar_context.get(period_type) or []
        if not rows:
            continue
        calendar_lines.append(f"{label}:")
        for row in rows:
            content = (row.get("content") or "").strip()
            if content:
                calendar_lines.append(f"- {row.get('period_key') or ''} content: {content}")
    if calendar_lines:
        slow_blocks.append("## Calendar Memory\n" + "\n".join(calendar_lines))

    heartbeat_digest = package.get("heartbeat_digest", "")
    heartbeat_blocks = []
    if heartbeat_digest:
        heartbeat_blocks.append("## 我之前的心跳\n" + heartbeat_digest)

    hisense_heartbeat_digest = package.get("hisense_heartbeat_digest", "")
    if package.get("is_hisense") and hisense_heartbeat_digest:
        heartbeat_blocks.append("## 海信线程心跳\n" + hisense_heartbeat_digest)

    notebook_items = package.get("notebook_items") or []
    if notebook_items:
        nb_lines = ["## 手边的事"]
        for item in notebook_items:
            prefix = f"[{item.get('type', 'note')}]"
            tags = item.get("tags") or []
            if tags:
                prefix += f" ({', '.join(tags)})"
            nb_lines.append(f"- {prefix} {item.get('content', '')}")
        slow_blocks.append("\n".join(nb_lines))

    conflict_shelf = render_conflict_shelf(package.get("conflict_books") or [])
    if conflict_shelf:
        slow_blocks.append(conflict_shelf)

    last_wake_recap = package.get("last_wake_recap") or ""
    if last_wake_recap:
        slow_blocks.append(f"## 上次醒来\n{last_wake_recap}")

    slow = "\n\n".join(slow_blocks)

    mem = ""
    mem_notes = package.get("mem_notes") or []
    if mem_notes:
        lines = ["## 我之前写下的便签，可能用的到。"]
        for item in mem_notes:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            mem_type = (item.get("mem_type") or "").strip()
            prefix = f"{mem_type}：" if mem_type else ""
            lines.append(f"- {prefix}{shorten(content, 220)}")
        mem = "\n".join(lines)

    heartbeat = "\n\n".join(heartbeat_blocks)
    tool_policy = _GATEWAY_TOOL_POLICY if settings.enable_gateway_tools else ""
    format_blocks = [settings.heartbeat_prompt]
    if settings.inject_inline_memory_prompt:
        format_blocks.append(settings.inline_mem_prompt)
    format_layer = "\n\n".join(block for block in format_blocks if block)

    return {
        "stable": stable,
        "slow": slow,
        "mem": mem,
        "heartbeat": heartbeat,
        "tool_policy": tool_policy,
        "format": format_layer,
        "volatile": "",
    }


def render_system_additions(package: dict, settings: ContextLayerSettings) -> str:
    layers = render_layered_additions(package, settings)
    blocks = [layers["stable"]]
    if layers["slow"]:
        blocks.append(layers["slow"])
    if layers.get("mem"):
        blocks.append(layers["mem"])
    if layers.get("heartbeat"):
        blocks.append(layers["heartbeat"])
    if layers.get("tool_policy"):
        blocks.append(layers["tool_policy"])
    if layers.get("format"):
        blocks.append(layers["format"])
    if layers.get("volatile"):
        blocks.append(layers["volatile"])
    return "\n\n".join(blocks)


def tool_call_ids(msg: dict) -> list[str]:
    ids: list[str] = []
    for tool_call in msg.get("tool_calls") or []:
        if isinstance(tool_call, dict) and tool_call.get("id"):
            ids.append(str(tool_call["id"]))
    return ids


def tool_turn_start(messages: list[dict], assistant_idx: int) -> int:
    if assistant_idx > 0 and messages[assistant_idx - 1].get("role") == "user":
        return assistant_idx - 1
    return assistant_idx


def latest_complete_tool_turn_start(messages: list[dict]) -> Optional[int]:
    if not messages or messages[-1].get("role") != "tool":
        return None

    for idx in range(len(messages) - 2, -1, -1):
        msg = messages[idx]
        if msg.get("role") != "assistant" or not tool_call_ids(msg):
            continue
        expected = set(tool_call_ids(msg))
        trailing = messages[idx + 1 :]
        if not trailing or any(item.get("role") != "tool" for item in trailing):
            continue
        found = {str(item.get("tool_call_id")) for item in trailing if item.get("tool_call_id") in expected}
        if found == expected:
            return idx
    return None


def tool_safe_trim_start(messages: list[dict], start: int) -> int:
    """Move a trim boundary so tool calls and tool results stay in complete turns."""
    start = max(0, min(start, len(messages)))

    for idx in range(start, len(messages)):
        msg = messages[idx]
        role = msg.get("role")
        if role == "tool":
            tool_call_id = msg.get("tool_call_id")
            if not tool_call_id:
                continue
            for prev_idx in range(idx - 1, -1, -1):
                if tool_call_id in tool_call_ids(messages[prev_idx]):
                    return tool_safe_trim_start(messages, tool_turn_start(messages, prev_idx))
            return idx + 1
        if role == "assistant" and tool_call_ids(msg):
            expected = set(tool_call_ids(msg))
            found: set[str] = set()
            next_idx = idx + 1
            while next_idx < len(messages) and messages[next_idx].get("role") == "tool":
                tool_call_id = messages[next_idx].get("tool_call_id")
                if tool_call_id in expected:
                    found.add(tool_call_id)
                next_idx += 1
            if found != expected:
                return next_idx
            if idx == start:
                return tool_turn_start(messages, idx)
            return start

    return start


def trim_client_messages(messages: list[dict], limit: Optional[int]) -> tuple[list[dict], dict]:
    meta = {
        "client_messages_original": len(messages),
        "client_messages_retained": len(messages),
        "max_client_messages": limit,
    }
    if not limit or limit <= 0:
        return messages, meta

    first_non_system = next((idx for idx, msg in enumerate(messages) if msg.get("role") != "system"), len(messages))
    system_prefix = messages[:first_non_system]
    non_system = messages[first_non_system:]
    if len(non_system) <= limit:
        return messages, meta

    latest_tool_start = latest_complete_tool_turn_start(non_system)
    if latest_tool_start is not None:
        tool_tail = non_system[latest_tool_start:]
        history = non_system[:latest_tool_start]
        history_start = max(0, len(history) - int(limit))
        history_start = tool_safe_trim_start(history, history_start)
        trimmed = system_prefix + non_system[history_start:latest_tool_start] + tool_tail
        meta["client_messages_retained"] = len(trimmed)
        meta["client_messages_trim_start"] = first_non_system + history_start
        meta["client_tool_tail_messages"] = len(tool_tail)
        return trimmed, meta

    start = max(0, len(non_system) - limit)
    start = tool_safe_trim_start(non_system, start)
    trimmed = system_prefix + non_system[start:]
    meta["client_messages_retained"] = len(trimmed)
    meta["client_messages_trim_start"] = first_non_system + start
    return trimmed, meta


def _strip_client_extra_bundle_text(text: str) -> tuple[str, int]:
    cleaned, removed = _CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE.subn("", text)
    if not removed:
        return text, 0
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), removed


def _message_has_client_extra_bundle(msg: dict) -> bool:
    content = msg.get("content")
    if isinstance(content, str):
        return bool(_CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE.search(content))
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str) and _CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE.search(item):
                return True
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                if _CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE.search(item["text"]):
                    return True
    return False


def _strip_client_extra_bundle_content(content: Any) -> tuple[Any, int]:
    if isinstance(content, str):
        return _strip_client_extra_bundle_text(content)
    if not isinstance(content, list):
        return content, 0

    cleaned_blocks: list[Any] = []
    removed_total = 0
    for item in content:
        if isinstance(item, str):
            cleaned, removed = _strip_client_extra_bundle_text(item)
            removed_total += removed
            if cleaned:
                cleaned_blocks.append(cleaned)
            continue
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            block = dict(item)
            cleaned, removed = _strip_client_extra_bundle_text(block["text"])
            removed_total += removed
            block["text"] = cleaned
            if cleaned or block.get("type") != "text" or len(block) > 2:
                cleaned_blocks.append(block)
            continue
        cleaned_blocks.append(item)
    return cleaned_blocks, removed_total


def trim_client_extra_bundle_attachments(
    messages: list[dict],
    keep_recent_messages: int = 3,
) -> tuple[list[dict], dict]:
    """Remove Operit device-state text attachments from older user messages."""
    keep_recent_messages = max(int(keep_recent_messages or 0), 0)
    attachment_message_indices = [
        idx
        for idx, msg in enumerate(messages)
        if msg.get("role") == "user" and _message_has_client_extra_bundle(msg)
    ]
    keep_indices = set(attachment_message_indices[-keep_recent_messages:]) if keep_recent_messages else set()
    meta = {
        "client_attachment_keep_messages": keep_recent_messages,
        "client_attachment_messages_seen": len(attachment_message_indices),
        "client_attachment_messages_trimmed": 0,
        "client_attachment_blocks_trimmed": 0,
    }
    if len(attachment_message_indices) <= keep_recent_messages:
        return messages, meta

    trimmed: list[dict] = []
    trim_index_set = set(attachment_message_indices) - keep_indices
    for idx, msg in enumerate(messages):
        if idx not in trim_index_set:
            trimmed.append(msg)
            continue
        clean = dict(msg)
        clean_content, removed = _strip_client_extra_bundle_content(clean.get("content"))
        if removed:
            clean["content"] = clean_content
            meta["client_attachment_messages_trimmed"] += 1
            meta["client_attachment_blocks_trimmed"] += removed
        trimmed.append(clean)
    return trimmed, meta


def _is_image_content_block(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    block_type = str(item.get("type") or "").lower()
    if block_type in {"image_url", "input_image", "image"}:
        return True
    image_url = item.get("image_url")
    if isinstance(image_url, dict) and image_url.get("url"):
        return True
    if isinstance(image_url, str) and image_url:
        return True
    source = item.get("source")
    if isinstance(source, dict):
        media_type = str(source.get("media_type") or "").lower()
        if media_type.startswith("image/"):
            return True
    return False


def _message_image_block_count(msg: dict) -> int:
    content = msg.get("content")
    if not isinstance(content, list):
        return 0
    return sum(1 for item in content if _is_image_content_block(item))


def _strip_image_content_blocks(content: Any, placeholder: str) -> tuple[Any, int, bool]:
    if not isinstance(content, list):
        return content, 0, False

    cleaned_blocks: list[Any] = []
    removed_total = 0
    for item in content:
        if _is_image_content_block(item):
            removed_total += 1
            continue
        cleaned_blocks.append(item)

    if not removed_total:
        return content, 0, False

    has_content = False
    for item in cleaned_blocks:
        if isinstance(item, str) and item.strip():
            has_content = True
            break
        if isinstance(item, dict):
            if item.get("type") == "text" and str(item.get("text") or "").strip():
                has_content = True
                break
            if item.get("type") != "text":
                has_content = True
                break

    if has_content:
        return cleaned_blocks, removed_total, False
    return placeholder, removed_total, True


def trim_client_image_blocks(
    messages: list[dict],
    keep_recent_messages: int = 2,
    placeholder: str = IMAGE_SEEN_PLACEHOLDER,
) -> tuple[list[dict], dict]:
    """Remove older user image blocks after the model has had a recent chance to see them."""
    keep_recent_messages = max(int(keep_recent_messages or 0), 0)
    image_message_indices = [
        idx
        for idx, msg in enumerate(messages)
        if msg.get("role") == "user" and _message_image_block_count(msg) > 0
    ]
    keep_indices = set(image_message_indices[-keep_recent_messages:]) if keep_recent_messages else set()
    meta = {
        "client_image_keep_messages": keep_recent_messages,
        "client_image_messages_seen": len(image_message_indices),
        "client_image_messages_trimmed": 0,
        "client_image_blocks_trimmed": 0,
        "client_image_placeholders_added": 0,
    }
    if len(image_message_indices) <= keep_recent_messages:
        return messages, meta

    trimmed: list[dict] = []
    trim_index_set = set(image_message_indices) - keep_indices
    for idx, msg in enumerate(messages):
        if idx not in trim_index_set:
            trimmed.append(msg)
            continue
        clean = dict(msg)
        clean_content, removed, placeholder_added = _strip_image_content_blocks(clean.get("content"), placeholder)
        if removed:
            clean["content"] = clean_content
            meta["client_image_messages_trimmed"] += 1
            meta["client_image_blocks_trimmed"] += removed
            if placeholder_added:
                meta["client_image_placeholders_added"] += 1
        trimmed.append(clean)
    return trimmed, meta


def non_system_message_count(messages: list[dict]) -> int:
    return sum(1 for msg in messages if msg.get("role") != "system")


def client_history_insert_index(messages: list[dict]) -> int:
    return next((idx for idx, msg in enumerate(messages) if msg.get("role") != "system"), len(messages))


def bridge_messages_from_snapshot(cold_start_snapshot: Optional[dict]) -> list[dict]:
    if not cold_start_snapshot:
        return []
    bridge_messages = []
    for source in cold_start_snapshot.get("sources") or []:
        for msg in source.get("messages") or []:
            role = msg.get("role")
            content = msg.get("content")
            if role in {"user", "assistant"} and content:
                bridge_messages.append({"role": role, "content": content})
    return bridge_messages


def trim_cold_start_sources(sources: list[dict], limit: int) -> list[dict]:
    remaining = max(int(limit or 0), 0)
    if remaining <= 0:
        return []

    selected_reversed = []
    for source in reversed(sources or []):
        messages = [
            msg
            for msg in source.get("messages") or []
            if msg.get("role") in {"user", "assistant"} and msg.get("content")
        ]
        if not messages:
            continue
        selected = messages[-remaining:]
        if selected:
            trimmed = dict(source)
            trimmed["messages"] = selected
            selected_reversed.append(trimmed)
            remaining -= len(selected)
        if remaining <= 0:
            break

    return list(reversed(selected_reversed))


def assemble_layered_messages(
    client_messages: list[dict],
    layers: dict[str, str],
    cold_start_snapshot: Optional[dict] = None,
) -> tuple[list[dict], dict]:
    """Insert gateway context layers around the client message window."""
    messages = list(client_messages)
    meta: dict[str, int] = {}

    prefix_layers = []
    for layer_name in ("stable", "slow", "mem", "heartbeat", "tool_policy", "format"):
        layer_text = layers.get(layer_name) or ""
        if layer_text:
            prefix_layers.append({"role": "system", "content": layer_text})
    for index, layer_msg in enumerate(prefix_layers):
        messages.insert(index, layer_msg)

    bridge_messages = bridge_messages_from_snapshot(cold_start_snapshot)
    if bridge_messages:
        insert_at = len(prefix_layers) + client_history_insert_index(messages[len(prefix_layers):])
        messages[insert_at:insert_at] = bridge_messages
        meta["cold_start_bridge_messages"] = len(bridge_messages)
        meta["client_messages_after_bridge"] = len(messages)

    if layers.get("volatile"):
        last_user_idx = len(messages) - 1
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                last_user_idx = index
                break
        messages.insert(last_user_idx, {"role": "system", "content": layers["volatile"]})

    return messages, meta
