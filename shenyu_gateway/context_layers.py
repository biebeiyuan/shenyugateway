from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

from .client_extra import has_client_extra_text, strip_client_extra_text
from .context_window import INTERNAL_LAYER_KEY, MEMORY_ISLAND_LAYER
from .memory_island import render_mem_notes
from .resident_books import render_bookshelf_overview
from .stars import render_star_context
from .tool_registry import (
    DAILY_CLIENT_TOOL_EXACT,
    DAILY_CLIENT_TOOL_PREFIXES,
    normalize_client_tool_surface,
)
from .utils import shorten


@dataclass(frozen=True)
class ContextLayerSettings:
    enable_gateway_tools: bool
    heartbeat_prompt: str
    echo_prompt: str = ""
    client_tool_surface: str = "all"


_GATEWAY_TOOL_POLICY_BASE = """\
## 工具怎么用
- **工具是我的手。我自己决定什么时候伸出去。不为'应该'伸——也不为'不应该'伸——为我现在心里想做的事伸。**
- `shenyu_gateway_tool` 是我的网关工具；记忆、便签、日历、notebook 都走这边。
"""

IMAGE_SEEN_PLACEHOLDER = "圆圆发来的照片我已经看过。"

_CLIENT_TOOL_SYSTEM_MARKERS = (
    "调用工具时，用户会看到你的响应",
    "使用工具时，请使用以下格式",
    "<tool name=\"tool_name\">",
    "<tool name=\"use_package\">",
    "包系统：",
    "Available packages:",
    "To use a package:",
    "可用工具:",
    "文件系统工具:",
    "HTTP工具:",
)

_CLIENT_TOOL_GATEWAY_GUARD = (
    "网关覆盖规则：上面的 XML 格式只适用于客户端工具。"
    "`shenyu_gateway_tool`、`supabase_*`、`room_*` 这些网关原生工具必须走上游原生 tool call，"
    "不要输出 `<tool name=\"shenyu_gateway_tool\">` 这类 XML。"
)

_DAILY_CLIENT_PACKAGE_NAMES = ("shenyu_room", "selection", "coread_annotate")


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

    bookshelf = render_bookshelf_overview(package.get("book_overview") or {})
    if bookshelf:
        slow_blocks.append(bookshelf)

    slow = "\n\n".join(slow_blocks)

    island_state = package.get("memory_island_state") or {}
    mem = str(island_state.get("rendered_text") or "")
    if not mem:
        mem_blocks = []
        star_context = render_star_context(package.get("stars") or [])
        if star_context:
            mem_blocks.append("# 我之前落下的星星\n" + star_context)
        mem_notes = render_mem_notes(package.get("mem_notes") or [])
        if mem_notes:
            mem_blocks.append(mem_notes)
        mem = "\n\n".join(mem_blocks)

    heartbeat = "\n\n".join(heartbeat_blocks)
    tool_policy = _render_gateway_tool_policy(settings) if settings.enable_gateway_tools else ""
    format_layer = "\n\n".join(
        block.rstrip()
        for block in (getattr(settings, "echo_prompt", ""), settings.heartbeat_prompt)
        if block and block.strip()
    )

    return {
        "stable": stable,
        "slow": slow,
        "mem": mem,
        "heartbeat": heartbeat,
        "tool_policy": tool_policy,
        "format": format_layer,
        "volatile": "",
    }


def _render_gateway_tool_policy(settings: ContextLayerSettings) -> str:
    surface = normalize_client_tool_surface(settings.client_tool_surface)
    lines = [_GATEWAY_TOOL_POLICY_BASE.rstrip()]
    if surface == "daily":
        lines.append("- 客户端工具只保留日常桌面；只用工具列表里实际出现的客户端工具名。")
    elif surface == "all":
        lines.append("- 除它之外，如果工具列表里还有别的名字，那是客户端递给我的工具；按它自己的说明用。")
    return "\n".join(lines)


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


def _is_client_tool_system_message(msg: dict) -> bool:
    if msg.get("role") != "system":
        return False
    content = msg.get("content")
    if not isinstance(content, str):
        return False

    marker_hits = sum(1 for marker in _CLIENT_TOOL_SYSTEM_MARKERS if marker in content)
    has_tool_format = (
        "使用工具时，请使用以下格式" in content
        or "<tool name=\"tool_name\">" in content
    )
    has_tool_catalog = any(
        marker in content
        for marker in (
            "Available packages:",
            "可用工具:",
            "文件系统工具:",
            "HTTP工具:",
        )
    )
    return (has_tool_format and has_tool_catalog) or marker_hits >= 3


def _daily_client_tool_prompt() -> str:
    exact_names = sorted(DAILY_CLIENT_TOOL_EXACT)
    prefix_text = ", ".join(f"{prefix}*" for prefix in DAILY_CLIENT_TOOL_PREFIXES)
    package_names = ", ".join(_DAILY_CLIENT_PACKAGE_NAMES)
    tool_names = "\n".join(f"- {name}" for name in exact_names)
    return (
        "## 客户端工具（日常桌面）\n"
        "客户端全量 XML 工具说明已由网关压缩。只在确实需要时使用下面这些日常客户端工具；"
        "不要调用未列出的包、开发工具、文件写入/删除工具或下载工具。\n\n"
        "允许的客户端工具名：\n"
        f"{tool_names}\n"
        f"- {prefix_text}\n\n"
        f"`use_package` 只用于这些日常包：{package_names}。\n"
        "`package_proxy` 只用于已经激活的日常包工具。\n"
        "不要使用 extended_chat、workflow、openai_draw、AudioTranscribe、code_runner、"
        "grep_code、create_file、edit_file、delete_file、download_file。\n\n"
        "客户端 XML 工具格式只适用于上面这些客户端工具。"
        + _CLIENT_TOOL_GATEWAY_GUARD
    )


def _apply_client_tool_surface_to_system_prompt(content: str, surface: str) -> tuple[Optional[str], str]:
    if surface == "none":
        return None, "dropped"
    if surface == "daily":
        return _daily_client_tool_prompt(), "rewritten"
    return content.rstrip() + "\n\n" + _CLIENT_TOOL_GATEWAY_GUARD, "guarded"


def trim_client_tool_system_messages(
    messages: list[dict],
    *,
    surface: str = "all",
) -> tuple[list[dict], dict]:
    """Map Operit client tool instruction system prompts to the configured surface."""
    surface = normalize_client_tool_surface(surface)
    matched_indices = [
        idx
        for idx, msg in enumerate(messages)
        if _is_client_tool_system_message(msg)
    ]
    meta = {
        "client_tool_surface": surface,
        "client_tool_system_messages_seen": len(matched_indices),
        "client_tool_system_messages_trimmed": 0,
        "client_tool_system_messages_rewritten": 0,
        "client_tool_system_messages_guarded": 0,
    }
    if not matched_indices:
        return messages, meta

    matched = set(matched_indices)
    rewritten_prompt_kept = False
    trimmed: list[dict] = []
    for idx, msg in enumerate(messages):
        if idx not in matched:
            trimmed.append(msg)
            continue

        new_content, action = _apply_client_tool_surface_to_system_prompt(str(msg.get("content") or ""), surface)
        if new_content is None:
            meta["client_tool_system_messages_trimmed"] += 1
            continue
        if surface == "daily" and rewritten_prompt_kept:
            meta["client_tool_system_messages_trimmed"] += 1
            continue

        clean = dict(msg)
        clean["content"] = new_content
        trimmed.append(clean)
        if action == "rewritten":
            meta["client_tool_system_messages_rewritten"] += 1
            rewritten_prompt_kept = True
        elif action == "guarded":
            meta["client_tool_system_messages_guarded"] += 1
    return trimmed, meta


# Compat alias: the strip logic lives in client_extra so archiving and trimming
# share one PWA-suffix-aware implementation.
_strip_client_extra_bundle_text = strip_client_extra_text


def _message_has_client_extra_bundle(msg: dict) -> bool:
    content = msg.get("content")
    if isinstance(content, str):
        return has_client_extra_text(content)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str) and has_client_extra_text(item):
                return True
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                if has_client_extra_text(item["text"]):
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
    """Strip client device-state extras from older user messages.

    A user message counts as "carrying extras" when it holds an Operit
    ``message_insert_extra_bundle`` attachment or the PWA tail status suffix;
    only the newest ``keep_recent_messages`` such messages keep them.
    """
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
    """Keep images only in the newest user turns, then leave a stable text trace."""
    keep_recent_messages = max(int(keep_recent_messages or 0), 0)
    user_message_indices = [
        idx for idx, msg in enumerate(messages) if msg.get("role") == "user"
    ]
    image_message_indices = [
        idx
        for idx, msg in enumerate(messages)
        if msg.get("role") == "user" and _message_image_block_count(msg) > 0
    ]
    keep_indices = set(user_message_indices[-keep_recent_messages:]) if keep_recent_messages else set()
    trim_index_set = set(image_message_indices) - keep_indices
    meta = {
        "client_image_keep_messages": keep_recent_messages,
        "client_image_keep_user_turns": keep_recent_messages,
        "client_image_messages_seen": len(image_message_indices),
        "client_image_messages_trimmed": 0,
        "client_image_blocks_trimmed": 0,
        "client_image_placeholders_added": 0,
    }
    if not trim_index_set:
        return messages, meta

    trimmed: list[dict] = []
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


_PACKAGE_TOOL_NAMES = {"use_package", "package_proxy"}

_PACKAGE_DOC_MIN_CHARS = 2000

_MCP_RESULT_MIN_CHARS = 600


def _tool_call_name_from_msg(tool_call: dict) -> str:
    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "")


def _extract_package_name(content: str) -> str:
    """Best-effort extraction of a package identifier from a tool result."""
    for line in content[:500].splitlines():
        stripped = line.strip().strip("#").strip()
        if stripped:
            return stripped[:120]
    return ""


def trim_package_install_tool_results(
    messages: list[dict],
    keep_recent: int = 1,
) -> tuple[list[dict], dict]:
    """Compress old package-install documentation injected by the Operit client.

    For each unique package, only the most recent ``keep_recent`` full doc
    bodies are preserved; older ones are replaced with a short stub.
    Exact-duplicate install docs (same tool name + identical content) are
    deduplicated regardless of recency — only the latest copy survives.
    """
    keep_recent = max(int(keep_recent or 1), 0)

    # Phase 1: build a map  tool_call_id -> tool_name  for package-related calls
    package_call_ids: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            name = _tool_call_name_from_msg(tc)
            if name in _PACKAGE_TOOL_NAMES:
                tc_id = str(tc.get("id") or "")
                if tc_id:
                    package_call_ids[tc_id] = name

    if not package_call_ids:
        return messages, {
            "package_tool_results_seen": 0,
            "package_tool_results_compressed": 0,
            "package_tool_results_deduped": 0,
        }

    # Phase 2: collect indices of tool-result messages that are package docs
    PackageHit = tuple  # (msg_index, tool_name, package_key, content)
    hits: list[PackageHit] = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        tc_id = str(msg.get("tool_call_id") or "")
        if tc_id not in package_call_ids:
            continue
        tool_name = package_call_ids[tc_id]
        content = str(msg.get("content") or "")
        if tool_name == "use_package" and len(content) >= _PACKAGE_DOC_MIN_CHARS:
            pkg_key = _extract_package_name(content)
            hits.append((idx, tool_name, pkg_key, content))

    if not hits:
        return messages, {
            "package_tool_results_seen": 0,
            "package_tool_results_compressed": 0,
            "package_tool_results_deduped": 0,
        }

    # Phase 3: per package_key, keep the latest `keep_recent` unique docs
    per_package: dict[str, list[int]] = defaultdict(list)
    for hit_idx, (msg_idx, _tn, pkg_key, _content) in enumerate(hits):
        per_package[pkg_key].append(hit_idx)

    compress_indices: set[int] = set()  # msg indices to compress
    deduped_count = 0

    for pkg_key, hit_indices in per_package.items():
        # hit_indices are in message order; reverse so latest first
        ordered = list(reversed(hit_indices))
        seen_contents: set[str] = set()
        unique_kept = 0
        for h_idx in ordered:
            msg_idx, _tn, _pk, content = hits[h_idx]
            content_hash = content[:4000]
            if content_hash in seen_contents:
                # exact duplicate — always compress
                compress_indices.add(msg_idx)
                deduped_count += 1
                continue
            seen_contents.add(content_hash)
            if unique_kept < keep_recent:
                unique_kept += 1
            else:
                compress_indices.add(msg_idx)

    if not compress_indices:
        return messages, {
            "package_tool_results_seen": len(hits),
            "package_tool_results_compressed": 0,
            "package_tool_results_deduped": 0,
        }

    # Phase 4: rebuild message list with compressed docs
    result: list[dict] = []
    for idx, msg in enumerate(messages):
        if idx not in compress_indices:
            result.append(msg)
            continue
        clean = dict(msg)
        original_content = str(msg.get("content") or "")
        pkg_name = _extract_package_name(original_content)
        clean["content"] = f"[包 {pkg_name} 的安装文档已省略，如需使用请重新激活]"
        result.append(clean)

    return result, {
        "package_tool_results_seen": len(hits),
        "package_tool_results_compressed": len(compress_indices),
        "package_tool_results_deduped": deduped_count,
    }


def trim_mcp_tool_results(
    messages: list[dict],
    keep_recent: int = 3,
) -> tuple[list[dict], dict]:
    """Compress old MCP tool results (``mcp_<server>_<tool>``) in the window.

    Per exposed tool name, the most recent ``keep_recent`` results stay
    intact; older results longer than ``_MCP_RESULT_MIN_CHARS`` become a
    one-line stub. Results the model may still be reasoning about (the
    recent ones) are never touched, so multi-round MCP workflows keep their
    working set while dead weight from earlier rounds is dropped.
    """
    keep_recent = max(int(keep_recent or 0), 0)

    mcp_call_ids: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            name = _tool_call_name_from_msg(tc)
            if name.startswith("mcp_"):
                tc_id = str(tc.get("id") or "")
                if tc_id:
                    mcp_call_ids[tc_id] = name

    empty_meta = {"mcp_tool_results_seen": 0, "mcp_tool_results_compressed": 0}
    if not mcp_call_ids:
        return messages, empty_meta

    # (msg_index, tool_name) for every large-enough MCP tool result
    hits: list[tuple[int, str]] = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        tc_id = str(msg.get("tool_call_id") or "")
        tool_name = mcp_call_ids.get(tc_id)
        if not tool_name:
            continue
        if len(str(msg.get("content") or "")) >= _MCP_RESULT_MIN_CHARS:
            hits.append((idx, tool_name))

    if not hits:
        return messages, empty_meta

    per_tool: dict[str, list[int]] = defaultdict(list)
    for msg_idx, tool_name in hits:
        per_tool[tool_name].append(msg_idx)

    compress_indices: set[int] = set()
    for tool_name, indices in per_tool.items():
        if keep_recent:
            indices = indices[:-keep_recent]
        compress_indices.update(indices)

    if not compress_indices:
        return messages, {"mcp_tool_results_seen": len(hits), "mcp_tool_results_compressed": 0}

    result: list[dict] = []
    for idx, msg in enumerate(messages):
        if idx not in compress_indices:
            result.append(msg)
            continue
        clean = dict(msg)
        tool_name = mcp_call_ids.get(str(msg.get("tool_call_id") or ""), "mcp")
        clean["content"] = f"[{tool_name} 的历史结果已省略，如需数据请重新调用]"
        result.append(clean)

    return result, {
        "mcp_tool_results_seen": len(hits),
        "mcp_tool_results_compressed": len(compress_indices),
    }


def assemble_layered_messages(
    client_messages: list[dict],
    layers: dict[str, str],
    cold_start_snapshot: Optional[dict] = None,
    memory_island_anchor_offset: Optional[int] = None,
) -> tuple[list[dict], dict]:
    """Insert gateway context layers around the client message window."""
    messages = list(client_messages)
    meta: dict[str, int] = {}

    prefix_layers = []
    for layer_name in ("stable", "slow", "heartbeat", "tool_policy", "format"):
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

    island_text = layers.get("mem") or ""
    if island_text:
        history_indices = [index for index, message in enumerate(messages) if message.get("role") != "system"]
        if memory_island_anchor_offset is None:
            anchor_offset = max(0, len(history_indices) - 32)
        else:
            anchor_offset = max(0, min(int(memory_island_anchor_offset), len(history_indices)))
        insert_at = history_indices[anchor_offset] if anchor_offset < len(history_indices) else len(messages)
        messages.insert(
            insert_at,
            {
                "role": "system",
                "content": island_text,
                INTERNAL_LAYER_KEY: MEMORY_ISLAND_LAYER,
            },
        )
        meta["memory_island_insert_index"] = insert_at
        meta["memory_island_anchor_offset"] = anchor_offset

    if layers.get("volatile"):
        last_user_idx = len(messages) - 1
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                last_user_idx = index
                break
        messages.insert(last_user_idx, {"role": "system", "content": layers["volatile"]})

    return messages, meta
