"""小突起：动态岛下面那一小节「今天我已经记下的」。

沈予用完工具之后是不知道自己做了什么的。网关内部的工具轮次只活在 `tool_loop`
的本地列表里；返回给客户端的只有最后那条 assistant 消息，而客户端回传时只带
`{role, content}`（`pwa/src/api/client.ts::wireMessages`）。所以「我上一轮落了
一颗星」这件事在下一轮的上下文里完全不存在，同一件事会被记第二遍。

这一节把当天的写操作读回来，每条一句话。名字是沈予自己取的。

三条边界，都是刻意的：

- **不是工具。** 沈予什么都不用调。做成工具就等于「让她记得调一个工具，来帮她
  记得自己做过什么」——正是要修的那个 bug。
- **不进岛文本。** 渲染结果作为紧跟岛之后的独立一块，岛的 `rendered_hash` 一个
  字节都不变，`memory_island` 的 2/3 重合门照旧生效。写进岛文本内部会让岛每次
  写入都换版，岛之后那三十来条消息的缓存全部作废。
- **无状态。** 「展示过没有」不记账，纯按时间窗口算。retry / roll / 分支都不会
  让它错乱。

日界走 `runtime.local_waking_day`（凌晨两点翻页）而不是自然日：熬夜时凌晨一点
写下的东西，一点半就"不是今天"了，这很荒谬。
"""

from __future__ import annotations

import json
from typing import Any

from .runtime import local_waking_day_start
from .utils import shorten

BUMP_HEADING = "## 今天的小突起"

# 上锁的抽屉写入即隐私边界——放进去就不再被提起，回执会正好破坏这一点。
# 这里只列记忆三件套，其余写操作（原始表操作、评分簿记、批量改、删除）都不进来：
# 要么没有可读内容，要么复述它正是反效果。
_STAR_TOOLS = frozenset({"shenyu_create_star"})
_MEM_TOOLS = frozenset({"shenyu_write_mem_note"})
_CALENDAR_TOOLS = frozenset({"shenyu_add_calendar"})
BUMP_TOOL_NAMES = _STAR_TOOLS | _MEM_TOOLS | _CALENDAR_TOOLS

_CALENDAR_MODE_WORDS = {"new": "新建", "append": "续写", "replace": "覆盖"}

DEFAULT_BUMP_LIMIT = 8


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _star_bump(result: dict[str, Any]) -> str:
    star = result.get("star")
    star = star if isinstance(star, dict) else {}
    content = _clean(star.get("content"))
    if not content:
        return ""
    # 措辞跟着 stars/_render.py::render_star_context 的「和弦 · 正文」走，
    # 这样她在岛上看到的星星和这里的回执是同一种说法。
    chord = _clean(star.get("chord"))
    body = f"{chord} · {shorten(content, 60)}" if chord else shorten(content, 60)
    return f"星星 {body}"


def _mem_bump(result: dict[str, Any]) -> str:
    note = result.get("note")
    note = note if isinstance(note, dict) else {}
    # summary 的 schema 描述原文就是「一句话版本（注入对话时用这个）」，
    # 缺省时网关自己会截，所以这里几乎总有值；退回 content 只是兜底。
    text = _clean(note.get("summary")) or _clean(note.get("content"))
    if not text:
        return ""
    mem_type = _clean(note.get("mem_type"))
    line = f"便签 {mem_type}：{shorten(text, 60)}" if mem_type else f"便签 {shorten(text, 60)}"
    remind_on = _clean(note.get("remind_on"))
    if remind_on:
        line += f"（记的是 {remind_on[:10]}）"
    if _clean(result.get("duplicate_of")):
        # 便签自己的同日同内容去重（mem_notes/_crud.py）已经拦下了这次写入。
        # 说清楚，否则她会以为自己刚写成功了一张新的。
        line += "（本来就有一张，没有重复写）"
    return line


def _calendar_bump(result: dict[str, Any]) -> str:
    digest = _clean(result.get("digest"))
    if not digest:
        return ""
    period_key = _clean(result.get("period_key"))
    mode = _CALENDAR_MODE_WORDS.get(_clean(result.get("mode")), "")
    head = " ".join(part for part in ("日历", period_key) if part)
    return f"{head} {mode}：{shorten(digest, 60)}" if mode else f"{head}：{shorten(digest, 60)}"


def _bump_line(tool_name: str, result: dict[str, Any]) -> str:
    if tool_name in _STAR_TOOLS:
        return _star_bump(result)
    if tool_name in _MEM_TOOLS:
        return _mem_bump(result)
    if tool_name in _CALENDAR_TOOLS:
        return _calendar_bump(result)
    return ""


def bump_lines_from_tool_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_BUMP_LIMIT,
) -> list[str]:
    """Render one line per memory-write this waking day, oldest first.

    Rows are `gateway_messages` tool rows. Only successful writes count; a row
    whose stored JSON cannot be parsed is skipped rather than guessed at.
    """
    limit = max(0, min(int(limit or 0), 50))
    if not rows or not limit:
        return []
    lines: list[str] = []
    for row in rows:
        tool_name = _clean(row.get("tool_name"))
        if tool_name not in BUMP_TOOL_NAMES:
            continue
        result = _loads(row.get("content"))
        if result.get("ok") is not True:
            continue
        # 同一轮里重复调用同一个工具时，tool_loop 直接回放缓存结果，什么也没写。
        if result.get("cached_duplicate") is True:
            result = _loads(result.get("result")) or result
            if result.get("ok") is not True:
                continue
        line = _bump_line(tool_name, result)
        if line and line not in lines:
            lines.append(line)
    return lines[-limit:]


def render_island_bumps(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join([BUMP_HEADING, *(f"- {line}" for line in lines)])


def waking_day_start_iso() -> str:
    """The 02:00 boundary of the current waking day, as a stored-timestamp string."""
    boundary = local_waking_day_start()
    return boundary.isoformat() if boundary else ""
