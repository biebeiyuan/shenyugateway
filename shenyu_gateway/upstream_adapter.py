from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from .runtime import now_ts as _now_ts
from .context_window import INTERNAL_LAYER_KEY, MEMORY_ISLAND_LAYER
from .utils import clean_config_text as _clean_config_text
from .utils import coerce_json_object as _coerce_json_object
from .utils import normalize_text as _normalize_text


_SYSTEM_CACHE_LAYER_PREFERENCE = ("format", "tool_policy", "heartbeat", "slow", "stable")
ANTHROPIC_CONTENT_BLOCKS_KEY = "_shenyu_anthropic_content_blocks"
ANTHROPIC_THINKING_CONFIG_KEY = "_shenyu_anthropic_thinking_config"


def _cache_control_value(cache_ttl: str) -> dict[str, str]:
    value = {"type": "ephemeral"}
    if cache_ttl == "1h":
        value["ttl"] = "1h"
    return value


def _add_cache_control(
    block: dict,
    cache_paths: list[str],
    path: str,
    max_breakpoints: int = 4,
    cache_ttl: str = "5m",
) -> bool:
    if len(cache_paths) >= max_breakpoints:
        return False
    if block.get("cache_control"):
        return False
    block["cache_control"] = _cache_control_value(cache_ttl)
    cache_paths.append(path)
    return True


def _add_openai_message_cache_control(
    msg: dict,
    cache_paths: list[str],
    path: str,
    max_breakpoints: int = 4,
    cache_ttl: str = "5m",
) -> bool:
    content = msg.get("content")
    if isinstance(content, list):
        for block_index in range(len(content) - 1, -1, -1):
            block = content[block_index]
            if isinstance(block, dict) and _add_cache_control(
                block,
                cache_paths,
                f"{path}.content[{block_index}]",
                max_breakpoints,
                cache_ttl,
            ):
                return True
        return False
    if not _normalize_text(content).strip():
        return False
    return _add_cache_control(msg, cache_paths, path, max_breakpoints, cache_ttl)


def _guarded_user_message_index(messages: list[dict], guard_user_turns: int) -> int:
    guard = max(int(guard_user_turns or 0), 0)
    if guard <= 0:
        return -1
    user_indices = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user"
        and message.get(INTERNAL_LAYER_KEY) != MEMORY_ISLAND_LAYER
    ]
    if not user_indices:
        return -1
    return user_indices[max(0, len(user_indices) - guard - 1)]


def _sanitize_openai_content_blocks(content: list[Any]) -> list[Any]:
    blocks: list[Any] = []
    for item in content:
        if isinstance(item, str):
            if item.strip():
                blocks.append({"type": "text", "text": item})
            continue
        if not isinstance(item, dict):
            text = str(item)
            if text.strip():
                blocks.append({"type": "text", "text": text})
            continue

        block = dict(item)
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if text is None:
                continue
            text = str(text)
            if not text.strip():
                continue
            block["text"] = text
        blocks.append(block)
    return blocks


def _sanitize_openai_compatible_messages(messages: list[dict]) -> list[dict]:
    sanitized: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        clean = {key: value for key, value in msg.items() if value is not None}
        clean.pop(INTERNAL_LAYER_KEY, None)
        role = clean.get("role")
        content = clean.get("content")

        if isinstance(content, list):
            blocks = _sanitize_openai_content_blocks(content)
            if blocks:
                clean["content"] = blocks
            else:
                clean.pop("content", None)
        elif isinstance(content, str):
            if not content.strip():
                clean.pop("content", None)
        elif "content" in clean:
            text = _normalize_text(content)
            if text.strip():
                clean["content"] = text
            else:
                clean.pop("content", None)

        if role == "tool" and "content" not in clean:
            clean["content"] = "{}"
        if "content" not in clean and not (role == "assistant" and clean.get("tool_calls")):
            continue
        sanitized.append(clean)
    return sanitized


def _coerce_schema_default(schema: dict) -> None:
    if "default" not in schema:
        return
    expected = schema.get("type")
    value = schema.get("default")

    if expected == "boolean":
        if isinstance(value, bool):
            return
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"true", "1", "yes", "on"}:
                schema["default"] = True
                return
            if text in {"false", "0", "no", "off"}:
                schema["default"] = False
                return
        schema.pop("default", None)
        return

    if expected == "integer":
        if isinstance(value, bool):
            schema.pop("default", None)
            return
        if isinstance(value, int):
            return
        if isinstance(value, str):
            text = value.strip()
            try:
                if text and str(int(text)) == text:
                    schema["default"] = int(text)
                    return
            except ValueError:
                pass
        schema.pop("default", None)
        return

    if expected == "number":
        if isinstance(value, bool):
            schema.pop("default", None)
            return
        if isinstance(value, (int, float)):
            return
        if isinstance(value, str):
            text = value.strip()
            try:
                schema["default"] = float(text)
                return
            except ValueError:
                pass
        schema.pop("default", None)


def _sanitize_json_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    clean = {key: _sanitize_json_schema(item) for key, item in value.items()}
    _coerce_schema_default(clean)
    return clean


def _sanitize_openai_compatible_tools(tools: list[dict]) -> list[dict]:
    sanitized: list[dict] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        clean = _sanitize_json_schema(tool)
        function = clean.get("function") if isinstance(clean, dict) else {}
        if not isinstance(function, dict) or not function.get("name"):
            continue
        sanitized.append(clean)
    return sanitized


def _assistant_tool_call_message(assistant_message: dict, tool_calls: list[dict]) -> dict:
    message: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
    anthropic_blocks = assistant_message.get(ANTHROPIC_CONTENT_BLOCKS_KEY)
    if isinstance(anthropic_blocks, list) and anthropic_blocks:
        message[ANTHROPIC_CONTENT_BLOCKS_KEY] = json.loads(json.dumps(anthropic_blocks, ensure_ascii=False))
    thinking_config = assistant_message.get(ANTHROPIC_THINKING_CONFIG_KEY)
    if isinstance(thinking_config, dict) and thinking_config:
        message[ANTHROPIC_THINKING_CONFIG_KEY] = json.loads(json.dumps(thinking_config, ensure_ascii=False))
    content = assistant_message.get("content")
    if isinstance(content, list):
        blocks = _sanitize_openai_content_blocks(content)
        if blocks:
            message["content"] = blocks
    else:
        text = _normalize_text(content)
        if text.strip():
            message["content"] = text
    return message


def _apply_openai_compatible_cache_control(
    messages: list[dict],
    tools: list[dict],
    cache_layers: Optional[dict[str, str]] = None,
    max_breakpoints: int = 4,
    cache_ttl: str = "5m",
    tail_guard_user_turns: int = 0,
) -> tuple[list[dict], list[dict], list[str]]:
    layers = cache_layers or {}
    cache_paths: list[str] = []
    cached_messages = _sanitize_openai_compatible_messages(messages)
    cached_tools = _sanitize_openai_compatible_tools(tools)

    for layer_name in _SYSTEM_CACHE_LAYER_PREFERENCE:
        layer_text = layers.get(layer_name) or ""
        if not layer_text:
            continue
        for idx, msg in enumerate(cached_messages):
            if msg.get("role") == "system" and _normalize_text(msg.get("content")) == layer_text:
                _add_openai_message_cache_control(
                    msg,
                    cache_paths,
                    f"messages[{idx}].system_end",
                    max_breakpoints,
                    cache_ttl,
                )
                break
        if cache_paths:
            break

    island_text = layers.get("mem") or ""
    island_idx = next(
        (
            idx
            for idx, msg in enumerate(cached_messages)
            if island_text and _normalize_text(msg.get("content")) == island_text
        ),
        -1,
    )
    if island_idx >= 0:
        if island_idx > 0:
            _add_openai_message_cache_control(
                cached_messages[island_idx - 1],
                cache_paths,
                f"messages[{island_idx - 1}].before_island",
                max_breakpoints,
                cache_ttl,
            )
        _add_openai_message_cache_control(
            cached_messages[island_idx],
            cache_paths,
            f"messages[{island_idx}].memory_island",
            max_breakpoints,
            cache_ttl,
        )

    guarded_user_idx = _guarded_user_message_index(cached_messages, tail_guard_user_turns)
    if guarded_user_idx <= island_idx:
        guarded_user_idx = -1
    last_user_idx = max(
        (idx for idx, msg in enumerate(cached_messages) if msg.get("role") == "user"),
        default=-1,
    )

    if len(cache_paths) < max_breakpoints:
        start_idx = guarded_user_idx if guarded_user_idx >= 0 else last_user_idx
        for idx in range(start_idx, -1, -1):
            msg = cached_messages[idx]
            if msg.get("role") not in {"user", "assistant"}:
                continue
            path = (
                f"messages[{idx}].stable_tail"
                if guarded_user_idx >= 0 and idx == guarded_user_idx
                else f"messages[{idx}]"
            )
            if _add_openai_message_cache_control(
                msg,
                cache_paths,
                path,
                max_breakpoints,
                cache_ttl,
            ):
                break

    return cached_messages, cached_tools, cache_paths


def _cache_usage_summary(usage: Optional[dict], protocol: str = "") -> dict:
    usage = usage or {}
    protocol = str(protocol or "").strip().lower()
    creation = usage.get("cache_creation") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    input_details = usage.get("input_tokens_details") or {}
    read_reported = (
        "cache_read_input_tokens" in usage
        or "cached_tokens" in prompt_details
        or "cached_tokens" in input_details
    )
    write_reported = (
        "cache_creation_input_tokens" in usage
        or "cached_creation_tokens" in prompt_details
        or "cached_creation_tokens" in input_details
        or "cache_creation" in usage
        or "claude_cache_creation_5_m_tokens" in usage
        or "claude_cache_creation_1_h_tokens" in usage
    )
    read_tokens = int(
        usage.get("cache_read_input_tokens")
        or prompt_details.get("cached_tokens")
        or input_details.get("cached_tokens")
        or 0
    )
    if not creation:
        creation = {
            k: int(v or 0)
            for k, v in {
                "ephemeral_5m_input_tokens": usage.get("claude_cache_creation_5_m_tokens"),
                "ephemeral_1h_input_tokens": usage.get("claude_cache_creation_1_h_tokens"),
            }.items()
            if v
        }
    write_tokens = int(
        usage.get("cache_creation_input_tokens")
        or prompt_details.get("cached_creation_tokens")
        or input_details.get("cached_creation_tokens")
        or sum(int(value or 0) for value in creation.values())
        or 0
    )
    explicit_input_tokens = _usage_int(usage.get("cache_input_tokens"))
    if "cache_input_tokens" in usage:
        input_tokens = explicit_input_tokens
        input_reported = True
    elif "prompt_tokens" in usage:
        input_tokens = _usage_int(usage.get("prompt_tokens"))
        input_reported = True
    elif "cached_tokens" in input_details:
        input_tokens = _usage_int(usage.get("input_tokens"))
        input_reported = "input_tokens" in usage
    else:
        input_tokens = _usage_int(usage.get("input_tokens"))
        input_reported = not read_reported and not write_reported and "input_tokens" in usage
    if "cache_input_tokens" in usage:
        total_input_tokens = explicit_input_tokens
        total_input_reported = True
    elif protocol == "anthropic" and "input_tokens" in usage:
        total_input_tokens = _usage_int(usage.get("input_tokens")) + read_tokens + write_tokens
        total_input_reported = True
    elif "prompt_tokens" in usage:
        total_input_tokens = _usage_int(usage.get("prompt_tokens"))
        total_input_reported = True
    elif "input_tokens" in usage:
        total_input_tokens = _usage_int(usage.get("input_tokens"))
        total_input_reported = True
    else:
        total_input_tokens = 0
        total_input_reported = False
    return {
        "cache_read_input_tokens": read_tokens,
        "cache_creation_input_tokens": write_tokens,
        "cache_creation": creation,
        "hit": read_tokens > 0,
        "write": write_tokens > 0,
        "read_reported": read_reported,
        "write_reported": write_reported,
        "reported": read_reported or write_reported,
        "input_tokens": input_tokens,
        "input_reported": input_reported,
        "total_input_tokens": total_input_tokens,
        "total_input_reported": total_input_reported,
        "cache_read_percent": (
            round(read_tokens * 100 / total_input_tokens, 1)
            if total_input_reported and total_input_tokens > 0 and read_tokens <= total_input_tokens
            else None
        ),
        "cache_prefix_reuse_percent": (
            round(read_tokens * 100 / (read_tokens + write_tokens), 1)
            if read_tokens + write_tokens > 0
            else None
        ),
    }


def _anthropic_stop_reason_to_openai(stop_reason: Any) -> str | None:
    reason = str(stop_reason or "").strip()
    if reason == "tool_use":
        return "tool_calls"
    if reason == "max_tokens":
        return "length"
    if reason in {"end_turn", "stop_sequence", "stop"}:
        return "stop"
    return None


def _usage_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _anthropic_usage_to_openai(usage: Optional[dict]) -> dict:
    if not isinstance(usage, dict) or not usage:
        return {}
    prompt_tokens = _usage_int(usage.get("prompt_tokens", usage.get("input_tokens")))
    completion_tokens = _usage_int(usage.get("completion_tokens", usage.get("output_tokens")))
    total_tokens = _usage_int(usage.get("total_tokens")) or prompt_tokens + completion_tokens
    result = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    input_details = usage.get("input_tokens_details") or {}
    cached_tokens = _usage_int(
        usage.get("cache_read_input_tokens")
        or input_details.get("cached_tokens")
    )
    if cached_tokens:
        result["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
    if "cache_read_input_tokens" in usage:
        result["cache_read_input_tokens"] = _usage_int(usage.get("cache_read_input_tokens"))
    if "cache_creation_input_tokens" in usage:
        result["cache_creation_input_tokens"] = _usage_int(usage.get("cache_creation_input_tokens"))
    if isinstance(usage.get("cache_creation"), dict):
        result["cache_creation"] = {
            str(key): _usage_int(value)
            for key, value in usage["cache_creation"].items()
        }
    if "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage:
        cache_read_tokens = _usage_int(usage.get("cache_read_input_tokens"))
        cache_creation_tokens = _usage_int(usage.get("cache_creation_input_tokens"))
        result["uncached_input_tokens"] = prompt_tokens
        result["cache_input_tokens"] = prompt_tokens + cache_read_tokens + cache_creation_tokens
    return result


def _content_blocks(content: Any) -> list[dict]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        blocks: list[dict] = []
        for item in content:
            if isinstance(item, str):
                if item:
                    blocks.append({"type": "text", "text": item})
                continue
            if not isinstance(item, dict):
                text = str(item)
                if text:
                    blocks.append({"type": "text", "text": text})
                continue
            block = dict(item)
            block_type = block.get("type")
            if block_type == "image_url":
                image_url = block.get("image_url")
                url = image_url.get("url") if isinstance(image_url, dict) else image_url
                if isinstance(url, str) and url.strip():
                    normalized_url = url.strip()
                    if normalized_url.startswith("data:"):
                        header, separator, data = normalized_url.partition(",")
                        metadata = header[5:].split(";") if separator else []
                        media_type = metadata[0].strip() if metadata else ""
                        is_base64 = any(part.strip().lower() == "base64" for part in metadata[1:])
                        if separator and is_base64 and media_type.startswith("image/") and data:
                            blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": data,
                                    },
                                }
                            )
                            continue
                    else:
                        blocks.append(
                            {
                                "type": "image",
                                "source": {"type": "url", "url": normalized_url},
                            }
                        )
                        continue
                # Do not send an invalid OpenAI image wrapper to Anthropic.
                continue
            if block_type:
                blocks.append(block)
            elif isinstance(block.get("text"), str):
                blocks.append({"type": "text", "text": block["text"]})
        if blocks:
            return blocks
    text = _normalize_text(content)
    return [{"type": "text", "text": text}] if text else []


def _convert_openai_tools_to_anthropic(
    tools: list[dict],
    cache_paths: Optional[list[str]] = None,
    max_breakpoints: int = 4,
) -> list[dict]:
    converted = []
    for tool in tools:
        function = tool.get("function", {})
        name = function.get("name")
        if not name:
            continue
        converted.append(
            {
                "name": name,
                "description": function.get("description", ""),
                "input_schema": function.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return converted


def _normalize_anthropic_thinking(value: Any) -> Optional[dict]:
    if value is None or value is False:
        return None

    if value is True:
        value = {"type": "adaptive"}
    elif isinstance(value, str):
        value = {"type": value}
    elif not isinstance(value, dict):
        return None

    thinking = dict(value)
    if "budgetTokens" in thinking and "budget_tokens" not in thinking:
        thinking["budget_tokens"] = thinking.pop("budgetTokens")
    if "budget" in thinking and "budget_tokens" not in thinking:
        thinking["budget_tokens"] = thinking.pop("budget")
    if "max_tokens" in thinking and "budget_tokens" not in thinking:
        thinking["budget_tokens"] = thinking.pop("max_tokens")

    thinking_type = str(thinking.get("type") or "").strip().lower()
    if not thinking_type:
        if "budget_tokens" in thinking:
            thinking_type = "enabled"
        else:
            thinking_type = "adaptive"
    if thinking_type in {"on", "enabled", "true", "1"}:
        thinking_type = "enabled"
    elif thinking_type in {"adaptive", "auto"}:
        thinking_type = "adaptive"
    elif thinking_type in {"off", "disabled", "false", "0"}:
        return None

    thinking["type"] = thinking_type

    if thinking_type != "disabled" and "display" not in thinking:
        thinking["display"] = "summarized"

    budget_tokens = thinking.get("budget_tokens")
    if budget_tokens is not None:
        try:
            thinking["budget_tokens"] = max(1, int(budget_tokens))
        except (TypeError, ValueError):
            thinking.pop("budget_tokens", None)

    if thinking_type != "enabled":
        thinking.pop("budget_tokens", None)

    allowed_keys = {"type", "budget_tokens", "display"}
    return {key: value for key, value in thinking.items() if key in allowed_keys and value is not None}


def _openai_to_anthropic(
    messages: list[dict],
    cache_layers: Optional[dict[str, str]] = None,
    cache_paths: Optional[list[str]] = None,
    max_breakpoints: int = 4,
    cache_ttl: str = "5m",
    tail_guard_user_turns: int = 0,
) -> tuple[Optional[list[dict]], list[dict]]:
    layers = cache_layers or {}
    cache_paths = cache_paths if cache_paths is not None else []
    volatile_text = layers.get("volatile") or ""
    system_blocks: list[dict] = []
    anthropic_messages: list[dict] = []
    source_user_to_anthropic: dict[int, int] = {}
    island_anthropic_idx = -1
    pending_volatile = ""
    system_cache_text = next(
        (layers.get(name) for name in _SYSTEM_CACHE_LAYER_PREFERENCE if layers.get(name)),
        "",
    )

    for source_index, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content")
        layer_name = msg.get(INTERNAL_LAYER_KEY)

        if layer_name == MEMORY_ISLAND_LAYER:
            if anthropic_messages:
                previous_content = anthropic_messages[-1].get("content")
                if isinstance(previous_content, list):
                    for block_index in range(len(previous_content) - 1, -1, -1):
                        block = previous_content[block_index]
                        if isinstance(block, dict) and block.get("type") != "thinking":
                            _add_cache_control(
                                block,
                                cache_paths,
                                f"messages[{len(anthropic_messages) - 1}].before_island",
                                max_breakpoints,
                                cache_ttl,
                            )
                            break
            island_text = _normalize_text(content)
            island_block = {
                "type": "text",
                "text": (
                    '<memory_island source="gateway_background">\n'
                    + island_text
                    + "\n</memory_island>"
                ),
            }
            _add_cache_control(
                island_block,
                cache_paths,
                f"messages[{len(anthropic_messages)}].memory_island",
                max_breakpoints,
                cache_ttl,
            )
            island_anthropic_idx = len(anthropic_messages)
            anthropic_messages.append({"role": "user", "content": [island_block]})
            continue

        if role == "system":
            text = _normalize_text(content)
            if text:
                if volatile_text and text == volatile_text:
                    pending_volatile = text
                    continue
                block = {"type": "text", "text": text}
                if system_cache_text and text == system_cache_text:
                    _add_cache_control(
                        block,
                        cache_paths,
                        "system.end",
                        max_breakpoints,
                        cache_ttl,
                    )
                system_blocks.append(block)
            continue

        if role == "user":
            blocks = _content_blocks(content)
            if pending_volatile:
                blocks.insert(0, {"type": "text", "text": pending_volatile})
                pending_volatile = ""
            source_user_to_anthropic[source_index] = len(anthropic_messages)
            anthropic_messages.append({"role": "user", "content": blocks or ""})
            continue

        if role == "assistant":
            anthropic_blocks = msg.get(ANTHROPIC_CONTENT_BLOCKS_KEY)
            if isinstance(anthropic_blocks, list) and anthropic_blocks:
                anthropic_messages.append(
                    {
                        "role": "assistant",
                        "content": json.loads(json.dumps(anthropic_blocks, ensure_ascii=False)),
                    }
                )
                continue
            blocks: list[dict] = []
            text = _normalize_text(content)
            if text:
                blocks.append({"type": "text", "text": text})
            for tool_call in msg.get("tool_calls") or []:
                function = tool_call.get("function", {})
                args = function.get("arguments") or "{}"
                parsed_args = _coerce_json_object(args)
                if parsed_args is None:
                    parsed_args = {"raw_arguments": args}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.get("id") or f"toolu_{uuid.uuid4().hex[:10]}",
                        "name": function.get("name", "unknown_tool"),
                        "input": parsed_args or {},
                    }
                )
            anthropic_messages.append({"role": "assistant", "content": blocks or text or ""})
            continue

        if role == "tool":
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id") or "unknown_tool_call",
                            "content": _normalize_text(content),
                        }
                    ],
                }
            )

    guarded_source_idx = _guarded_user_message_index(messages, tail_guard_user_turns)
    guarded_anthropic_idx = source_user_to_anthropic.get(guarded_source_idx, -1)
    if guarded_anthropic_idx <= island_anthropic_idx:
        guarded_anthropic_idx = -1

    last_user_idx = -1
    for i, msg in enumerate(anthropic_messages):
        if msg.get("role") == "user":
            last_user_idx = i

    if len(cache_paths) < max_breakpoints:
        start_idx = guarded_anthropic_idx if guarded_anthropic_idx >= 0 else last_user_idx
        for msg_index in range(start_idx, -1, -1):
            content = anthropic_messages[msg_index].get("content")
            if not isinstance(content, list):
                continue
            for block_index in range(len(content) - 1, -1, -1):
                block = content[block_index]
                if not isinstance(block, dict) or block.get("type") == "thinking":
                    continue
                if _add_cache_control(
                    block,
                    cache_paths,
                    (
                        f"messages[{msg_index}].stable_tail.content[{block_index}]"
                        if guarded_anthropic_idx >= 0 and msg_index == guarded_anthropic_idx
                        else f"messages[{msg_index}].content[{block_index}]"
                    ),
                    max_breakpoints,
                    cache_ttl,
                ):
                    break
            else:
                continue
            break

    return (system_blocks or None, anthropic_messages)


def _anthropic_to_openai_completion(model: str, response: dict) -> dict:
    text_parts = []
    thinking_parts = []
    tool_calls = []
    for block in response.get("content", []):
        block_type = block.get("type")
        if block_type == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        elif block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_input = block.get("input", {})
            parsed_input = _coerce_json_object(tool_input)
            if parsed_input is None:
                parsed_input = {"raw_arguments": tool_input}
            tool_calls.append(
                {
                    "id": block.get("id") or f"call_{uuid.uuid4().hex[:10]}",
                    "type": "function",
                    "function": {
                        "name": block.get("name", "unknown_tool"),
                        "arguments": json.dumps(parsed_input, ensure_ascii=False),
                    },
                }
            )

    message = {"role": "assistant", "content": "".join(text_parts)}
    if thinking_parts:
        message["reasoning_content"] = "".join(thinking_parts)
    content_blocks = response.get("content")
    if tool_calls and isinstance(content_blocks, list) and any(
        isinstance(block, dict) and block.get("type") in {"thinking", "redacted_thinking"}
        for block in content_blocks
    ):
        message[ANTHROPIC_CONTENT_BLOCKS_KEY] = json.loads(json.dumps(content_blocks, ensure_ascii=False))
    finish_reason = _anthropic_stop_reason_to_openai(response.get("stop_reason")) or "stop"
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": _now_ts(),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": _anthropic_usage_to_openai(response.get("usage", {})),
    }


def _anthropic_to_openai_chunk(
    model: str,
    chunk: dict,
    *,
    finish_reason_override: str | None = None,
    tool_index_override: int | None = None,
    chunk_id: str | None = None,
    created: int | None = None,
) -> str:
    chunk_type = chunk.get("type", "")
    resolved_chunk_id = chunk_id or f"chatcmpl-{uuid.uuid4().hex[:12]}"
    base = {
        "id": resolved_chunk_id,
        "object": "chat.completion.chunk",
        "created": created if created is not None else _now_ts(),
        "model": model,
    }

    if chunk_type == "content_block_start":
        block = chunk.get("content_block", {})
        if block.get("type") == "thinking":
            base["choices"] = [{"index": 0, "delta": {"role": "assistant", "reasoning_content": ""}, "finish_reason": None}]
        elif block.get("type") == "tool_use":
            tool_index = tool_index_override if tool_index_override is not None else int(chunk.get("index") or 0)
            base["choices"] = [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": tool_index,
                                "id": block.get("id") or f"call_{uuid.uuid4().hex[:10]}",
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": "",
                                },
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ]
        else:
            base["choices"] = [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]
        return json.dumps(base)

    if chunk_type == "content_block_delta":
        delta = chunk.get("delta", {})
        delta_type = delta.get("type", "")
        if delta_type == "thinking_delta":
            thinking = delta.get("thinking", "")
            if not thinking:
                return ""
            base["choices"] = [{"index": 0, "delta": {"reasoning_content": thinking}, "finish_reason": None}]
            return json.dumps(base)
        text = delta.get("text", "")
        if not text:
            if delta_type != "input_json_delta":
                return ""
        if delta_type == "input_json_delta":
            partial_json = delta.get("partial_json", "")
            if not partial_json:
                return ""
            tool_index = tool_index_override if tool_index_override is not None else int(chunk.get("index") or 0)
            base["choices"] = [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": tool_index,
                                "function": {"arguments": partial_json},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
            return json.dumps(base)
        base["choices"] = [{"index": 0, "delta": {"content": text}, "finish_reason": None}]
        return json.dumps(base)

    if chunk_type == "message_stop":
        base["choices"] = [{"index": 0, "delta": {}, "finish_reason": finish_reason_override or "stop"}]
        return json.dumps(base)

    return ""


def _anthropic_tool_index_override(data: dict, tool_index_by_block: dict[int, int]) -> Optional[int]:
    chunk_type = data.get("type")
    is_tool_chunk = False
    if chunk_type == "content_block_start":
        is_tool_chunk = (data.get("content_block") or {}).get("type") == "tool_use"
    elif chunk_type == "content_block_delta":
        is_tool_chunk = (data.get("delta") or {}).get("type") == "input_json_delta"
    if not is_tool_chunk:
        return None
    try:
        block_index = int(data.get("index") or 0)
    except (TypeError, ValueError):
        block_index = 0
    if block_index not in tool_index_by_block:
        tool_index_by_block[block_index] = len(tool_index_by_block)
    return tool_index_by_block[block_index]


def _text_chunks(text: str, chunk_chars: int):
    if chunk_chars <= 0:
        yield text
        return
    for index in range(0, len(text), chunk_chars):
        yield text[index : index + chunk_chars]


def _completion_to_stream_events(
    completion: dict,
    *,
    include_role: bool = True,
    content_chunk_chars: int = 0,
    chunk_id: str | None = None,
):
    model = completion.get("model", "unknown")
    created = completion.get("created", _now_ts())
    resolved_chunk_id = chunk_id or f"chatcmpl-{uuid.uuid4().hex[:12]}"
    choice = completion.get("choices", [{}])[0]
    message = choice.get("message", {})

    if include_role:
        first = {
            "id": resolved_chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"

    # Send reasoning_content before normal content when the upstream supplied it.
    reasoning = message.get("reasoning_content", "")
    if reasoning:
        body = {
            "id": resolved_chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"reasoning_content": reasoning}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(body, ensure_ascii=False)}\n\n"

    text = message.get("content", "")
    if text:
        for text_part in _text_chunks(text, content_chunk_chars):
            body = {
                "id": resolved_chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": text_part}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(body, ensure_ascii=False)}\n\n"

    tool_calls = message.get("tool_calls") or []
    for index, tool_call in enumerate(tool_calls):
        function = tool_call.get("function") or {}
        arguments = function.get("arguments", "")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {}, ensure_ascii=False)
        stream_call = {
            "index": index,
            "id": tool_call.get("id") or f"call_{uuid.uuid4().hex[:10]}",
            "type": tool_call.get("type") or "function",
            "function": {
                "name": function.get("name", ""),
                "arguments": arguments,
            },
        }
        body = {
            "id": resolved_chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"tool_calls": [stream_call]}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(body, ensure_ascii=False)}\n\n"

    finish_reason = "tool_calls" if tool_calls else choice.get("finish_reason") or "stop"
    final = {
        "id": resolved_chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
    }
    yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def _models_url_for(upstream: dict[str, str]) -> str:
    base_url = _clean_config_text(upstream.get("base_url"))
    if not base_url:
        return ""
    if base_url.endswith("/v1/chat/completions"):
        return base_url[: -len("/v1/chat/completions")] + "/v1/models"
    if base_url.endswith("/chat/completions"):
        return base_url[: -len("/chat/completions")] + "/models"
    if base_url.endswith("/v1"):
        return base_url + "/models"
    return base_url.rstrip("/") + "/v1/models"
