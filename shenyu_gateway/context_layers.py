from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional


@dataclass(frozen=True)
class ContextLayerSettings:
    enable_gateway_tools: bool
    inject_inline_memory_prompt: bool
    heartbeat_prompt: str
    inline_mem_prompt: str


_GATEWAY_TOOL_POLICY = (
    "## 工具怎么用\n"
    "- 默认先直接回答；只有真的需要查库、写便签、读心跳或用户明确要求时才用工具。\n"
    "- 予予如果查到足够信息，可以直接写入并结束哦；避免重复查、重复写。我们的网关请求太多容易报错。\n"
    "- 没查完就直接告诉圆儿，不要硬循环。每一步工具都要有明确目的。\n"
    "- 找 ClaudeAI 时期留下的旧事件记忆：用 `shenyu_ask_memory`。\n"
    "- 找已经整理好、允许反上来的便签：用 `shenyu_search_mem_notes`。\n"
    "- 主动写一条新的 mem 便签：用 `shenyu_write_mem_note`，默认 active 直接放行；没写 trigger 时会用正文当 trigger。\n"
    "- 整理待处理便签：先用 `shenyu_list_mem_notes` 看 captured，再用 `shenyu_update_mem_note` 补 type / trigger，最后手动改 active。\n"
    "- 找日记、信、纸条、room、留言板原文：用 `shenyu_search_primary_texts`。\n"
    "- 只想从 room / 留言板捞几段相关话：用 `shenyu_surface_passages`。\n"
    "- 看自己以前写的心跳：用 `shenyu_read_heartbeat`。\n"
    "- 旧 atomic 只读迁移：只用 `shenyu_legacy_atomic_memories`。\n"
    "- 不确定 Supabase 表怎么查：先用 `shenyu_supabase_guide`。"
)

_CLIENT_EXTRA_BUNDLE_ATTACHMENT_RE = re.compile(
    r"\s*<attachment\b"
    r"(?=[^>]*\bid\s*=\s*['\"]?message_insert_extra_bundle_[^'\"\s>]+['\"]?)"
    r"[^>]*>.*?</attachment>",
    re.IGNORECASE | re.DOTALL,
)


def shorten(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def render_layered_additions(package: dict, settings: ContextLayerSettings) -> dict:
    """Render cache-friendly stable, slow, heartbeat, and volatile context layers."""
    stable_blocks = [package["stable_charter"]]
    if settings.enable_gateway_tools:
        stable_blocks.append(_GATEWAY_TOOL_POLICY)
    stable_blocks.append(settings.heartbeat_prompt)
    if settings.inject_inline_memory_prompt:
        stable_blocks.append(settings.inline_mem_prompt)
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
            digest = (row.get("digest") or "").strip()
            if digest:
                calendar_lines.append(f"- {row.get('period_key') or ''} digest: {digest}")
    if calendar_lines:
        slow_blocks.append("## Calendar Memory\n" + "\n".join(calendar_lines))

    heartbeat_digest = package.get("heartbeat_digest", "")
    heartbeat_blocks = []
    if heartbeat_digest:
        heartbeat_blocks.append("## 你之前的心跳\n" + heartbeat_digest)

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

    last_wake_recap = package.get("last_wake_recap") or ""
    if last_wake_recap:
        slow_blocks.append(f"## 上次醒来\n{last_wake_recap}")

    slow = "\n\n".join(slow_blocks)
    heartbeat = "\n\n".join(heartbeat_blocks)

    volatile = ""
    mem_notes = package.get("mem_notes") or []
    if mem_notes:
        lines = ["## 你以前给自己留过"]
        for item in mem_notes:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            mem_type = (item.get("mem_type") or "").strip()
            prefix = f"{mem_type}：" if mem_type else ""
            lines.append(f"- {prefix}{shorten(content, 220)}")
        mem_block = "\n".join(lines)
        volatile = "\n\n".join(block for block in [volatile, mem_block] if block)

    return {"stable": stable, "slow": slow, "heartbeat": heartbeat, "volatile": volatile}


def render_system_additions(package: dict, settings: ContextLayerSettings) -> str:
    layers = render_layered_additions(package, settings)
    blocks = [layers["stable"]]
    if layers["slow"]:
        blocks.append(layers["slow"])
    if layers.get("heartbeat"):
        blocks.append(layers["heartbeat"])
    if layers["volatile"]:
        blocks.append(layers["volatile"])
    return "\n\n".join(blocks)


def tool_call_ids(msg: dict) -> list[str]:
    ids: list[str] = []
    for tool_call in msg.get("tool_calls") or []:
        if isinstance(tool_call, dict) and tool_call.get("id"):
            ids.append(str(tool_call["id"]))
    return ids


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
                    return tool_safe_trim_start(messages, prev_idx)
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
            return idx

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
    if layers["stable"]:
        prefix_layers.append({"role": "system", "content": layers["stable"]})
    if layers["slow"]:
        prefix_layers.append({"role": "system", "content": layers["slow"]})
    if layers.get("heartbeat"):
        prefix_layers.append({"role": "system", "content": layers["heartbeat"]})
    for index, layer_msg in enumerate(prefix_layers):
        messages.insert(index, layer_msg)

    bridge_messages = bridge_messages_from_snapshot(cold_start_snapshot)
    if bridge_messages:
        insert_at = len(prefix_layers) + client_history_insert_index(messages[len(prefix_layers):])
        messages[insert_at:insert_at] = bridge_messages
        meta["cold_start_bridge_messages"] = len(bridge_messages)
        meta["client_messages_after_bridge"] = len(messages)

    if layers["volatile"]:
        last_user_idx = len(messages) - 1
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                last_user_idx = index
                break
        messages.insert(last_user_idx, {"role": "system", "content": layers["volatile"]})

    return messages, meta
