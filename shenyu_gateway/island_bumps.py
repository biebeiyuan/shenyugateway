"""小突起：沈予今天写下的回执和想起的轻量路标。

沈予用完工具之后是不知道自己做了什么的。网关内部的工具轮次只活在 `tool_loop`
的本地列表里；返回给客户端的只有最后那条 assistant 消息，而客户端回传时只带
`{role, content}`（`pwa/src/api/client.ts::wireMessages`）。所以「我上一轮落了
一颗星」这件事在下一轮的上下文里完全不存在，同一件事会被记第二遍。

这一节把当天的写操作和成功 Recall 读回来，每条一句话。名字是沈予自己取的。

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
# 写入只列记忆三件套加盼圃「种下」，另有成功 Recall 的只读路标；其余写操作（原始表操作、评分簿记、批量改、
# 删除）都不进来：要么没有可读内容，要么复述它正是反效果。
_STAR_TOOLS = frozenset({"shenyu_create_star"})
_MEM_TOOLS = frozenset({"shenyu_write_mem_note"})
_CALENDAR_TOOLS = frozenset({"shenyu_add_calendar"})
_RECALL_TOOLS = frozenset({"shenyu_recall"})
# 盼圃是一名四动作（plant/note/pick/look），不像上面三个各占一个工具名。种果子
# 库层没有查重（`orchard_service.py::plant` 直接 insert），忘了种过又种一遍就是
# 一颗静默的重复——她不 look 就看不见，跟记重星星同一种坑。只有 plant 进来：
# note 一天本来就想贴好几张、哪张算重复无从判断；pick 有条件更新挡着摘不了第二
# 次；look 是读操作。挑出 plant 靠工具行上记的 action，不是工具名。
_ORCHARD_TOOLS = frozenset({"shenyu_orchard"})
_ORCHARD_BUMP_ACTIONS = frozenset({"plant"})
BUMP_TOOL_NAMES = _STAR_TOOLS | _MEM_TOOLS | _CALENDAR_TOOLS | _ORCHARD_TOOLS | _RECALL_TOOLS

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


def _tool_params(row: dict[str, Any]) -> dict[str, Any]:
    args = _loads(row.get("tool_args") or row.get("tool_args_json"))
    params = args.get("params") or args.get("arguments")
    return params if isinstance(params, dict) else args


def _first_sentence(value: Any) -> str:
    paragraphs = _clean(value).splitlines()
    if not paragraphs:
        return ""
    text = " ".join(paragraphs[0].split())
    for index, char in enumerate(text):
        if char in "。！？!?" or (char == "." and (index + 1 == len(text) or text[index + 1].isspace())):
            text = text[: index + 1]
            break
    return shorten(text, 60)


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


def _orchard_bump(result: dict[str, Any]) -> str:
    # plant 的果子在 data.fruit 里（`orchard_service.py::plant`），不像星星在顶层。
    data = result.get("data")
    data = data if isinstance(data, dict) else {}
    fruit = data.get("fruit")
    fruit = fruit if isinstance(fruit, dict) else {}
    name = _clean(fruit.get("name"))
    if not name:
        return ""
    # 措辞跟着盼圃「不催」的调子（`tool_schemas.py::_gateway_orchard_tool`）：只说
    # 种下了什么，有预计日子就带上，没有就一直挂着等——不写"提醒""到期"。
    line = f"盼圃 种下：{shorten(name, 60)}"
    due_on = _clean(fruit.get("due_on"))
    if due_on:
        line += f"（预计 {due_on[:10]}）"
    return line


def _calendar_bump(result: dict[str, Any]) -> str:
    digest = _clean(result.get("digest"))
    if not digest:
        return ""
    period_key = _clean(result.get("period_key"))
    mode = _CALENDAR_MODE_WORDS.get(_clean(result.get("mode")), "")
    head = " ".join(part for part in ("日历", period_key) if part)
    return f"{head} {mode}：{shorten(digest, 60)}" if mode else f"{head}：{shorten(digest, 60)}"


def _recall_bumps(result: dict[str, Any], row: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return (source key, query, first sentence) tuples; never expose recall metadata."""
    items = result.get("items")
    if not isinstance(items, list):
        return []
    query = _clean(_tool_params(row).get("query"))
    if not query:
        return []
    found: list[tuple[str, str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_type = _clean(item.get("source_type"))
        source_id = _clean(item.get("source_id"))
        sentence = _first_sentence(item.get("content"))
        if not source_type or not source_id or not sentence:
            continue
        found.append((f"{source_type}:{source_id}", query, sentence))
    return found


def _orchard_action(row: dict[str, Any]) -> str:
    """这行盼圃工具调用的 action。full 模式在顶层，broker 模式（默认）把真参数
    裹在 `params`/`arguments` 里——两种都认，不然默认模式下永远读不到 plant。"""
    args = _loads(row.get("tool_args") or row.get("tool_args_json"))
    action = _clean(args.get("action"))
    if not action:
        nested = args.get("params")
        if not isinstance(nested, dict):
            nested = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
        action = _clean(nested.get("action")) if isinstance(nested, dict) else ""
    return action.lower()


def _bump_line(tool_name: str, result: dict[str, Any], row: dict[str, Any]) -> str:
    if tool_name in _STAR_TOOLS:
        return _star_bump(result)
    if tool_name in _MEM_TOOLS:
        return _mem_bump(result)
    if tool_name in _CALENDAR_TOOLS:
        return _calendar_bump(result)
    if tool_name in _ORCHARD_TOOLS:
        # 盼圃四动作共用一个工具名，只有 plant 出条；其余动作留在墙上，不进回执。
        return _orchard_bump(result) if _orchard_action(row) in _ORCHARD_BUMP_ACTIONS else ""
    return ""


def bump_lines_from_tool_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_BUMP_LIMIT,
) -> list[str]:
    """Render write receipts and successful Recall crumbs, oldest first.

    Rows are `gateway_messages` tool rows in chronological order. Keep recent
    writes first, fill spare slots with recent Recall sources, then interleave.
    Repeated Recall sources keep the first excerpt and its chronological slot.
    """
    limit = max(0, min(int(limit or 0), 50))
    if not rows or not limit:
        return []
    write_entries: list[tuple[int, str]] = []
    recall_by_source: dict[str, tuple[list[str], str, int]] = {}
    for row_index, row in enumerate(rows):
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
        if tool_name in _RECALL_TOOLS:
            for source_key, query, sentence in _recall_bumps(result, row):
                queries, old_sentence, first_index = recall_by_source.setdefault(
                    source_key, ([], sentence, row_index)
                )
                if query not in queries:
                    queries.append(query)
                recall_by_source[source_key] = (queries, old_sentence, first_index)
            continue
        line = _bump_line(tool_name, result, row)
        if line and not any(existing == line for _, existing in write_entries):
            write_entries.append((row_index, line))
    recall_entries = [
        (first_index, f"想起 {'、'.join(queries)}：{sentence}")
        for queries, sentence, first_index in recall_by_source.values()
    ]
    if len(write_entries) >= limit:
        selected = write_entries[-limit:]
    else:
        recent_recall = sorted(recall_entries, key=lambda entry: entry[0])[-(limit - len(write_entries)) :]
        selected = write_entries + recent_recall
    return [line for _, line in sorted(selected, key=lambda entry: entry[0])]


def render_island_bumps(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join([BUMP_HEADING, *(f"- {line}" for line in lines)])


def waking_day_start_iso() -> str:
    """The 02:00 boundary of the current waking day, as a stored-timestamp string."""
    boundary = local_waking_day_start()
    return boundary.isoformat() if boundary else ""
