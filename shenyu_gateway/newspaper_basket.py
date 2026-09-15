"""窗边报纸篓的读取原语。

篓里只放旧报。读它的有两个入口——房间里的 `room_newspaper_basket` 和日常聊天
的 `shenyu_newspaper_basket`——所以这个原语不属于任何一边，它谁都不依赖：只认
一个 duck-typed 的 store，不 import 工具层，也不 import 采编那条线。

采编在 `room_newspaper.py`（抓源、评质、发刊），那份要 httpx 和 upstream_client，
而 upstream_client import tool_registry、tool_registry import gateway_tools——
把这个读取原语放进 room_newspaper.py 会绕出一条循环引用（实测：
ImportError: cannot import name 'merge_tools' from partially initialized module）。
放在这里，依赖方向是单向的：room_tools 和 gateway_tools 都只往这边来。

写 room_trace 的那一层故意留在门外，见 `newspaper_basket_trace_detail` 的注释。
"""
from __future__ import annotations

from typing import Any, Optional


# 两个入口共用同一份说明书。同一次读、同一套参数，措辞分叉过一次：房间那扇门少了
# 「今天那份在椅子上」和 query/date 的优先级，恰好是最容易踩的两条。
NEWSPAPER_BASKET_DESCRIPTION = (
    "翻窗边报纸篓里的旧报纸。篓里只有旧的，今天那份压在窗边椅子上。"
    "无参数时按日期倒序列出；传 date 打开那天整期；"
    "传 query 在标题和摘要里做普通关键词查找。"
    "两个都传时以 query 为主，date 只把搜索范围收到那一天。"
)

NEWSPAPER_BASKET_PARAMETERS = {
    "type": "object",
    "properties": {
        "date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": "旧报日期，格式 YYYY-MM-DD",
        },
        "query": {"type": "string", "description": "标题和摘要中的关键词"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 30},
    },
}


def newspaper_payload(issue: dict, *, reader_date: Optional[str] = None) -> dict:
    payload: dict[str, Any] = {
        "issue_id": issue["id"],
        "published_at": issue.get("published_at"),
        "item_count": issue.get("item_count", 0),
        "items": [
            {
                "position": item.get("position"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "url": item.get("url"),
                "source": item.get("source_name"),
                "date": str(item.get("published_at") or "")[:10],
            }
            for item in issue.get("items") or []
        ],
    }
    if reader_date:
        payload["date"] = reader_date
        payload["read"] = bool(issue.get("delivered_at"))
    return payload


def newspaper_date_label(reader_date: str) -> str:
    try:
        _year, month, day = (int(part) for part in reader_date.split("-"))
    except (TypeError, ValueError):
        return reader_date
    return f"{month}月{day}日"


def newspaper_basket_trace_detail(result: dict) -> Optional[dict]:
    """Derive the room_trace detail for a basket read. None = nothing to record.

    Pure function so the daily-chat shell can reuse the same read without
    touching room_trace: that table answers "was he in the room", and
    last_room_visit_at() reads its newest row regardless of action, so a
    daily-chat write would damp the room charge and hide doors on his next visit.
    """
    if not result.get("ok"):
        return None
    mode = result.get("mode")
    if mode == "search":
        return {"mode": "search", "date": result.get("date"), "match_count": result.get("count", 0)}
    if mode == "read":
        return {"mode": "read", "date": result.get("date"), "issue_count": result.get("count", 0)}
    if mode == "list":
        return {"mode": "list", "visible_count": result.get("count", 0), "total": result.get("total", 0)}
    return None


def read_newspaper_basket(store: Any, arguments: dict) -> dict:
    """Read the old-newspaper basket. Writes no trace — see the room wrapper."""
    if not store:
        return {"ok": False, "error": "报纸篓现在打不开。"}

    reader_date = str(arguments.get("date") or "").strip()
    query = str(arguments.get("query") or "").strip()
    try:
        limit = max(1, min(int(arguments.get("limit", 30)), 50))
    except (TypeError, ValueError):
        limit = 30

    if query:
        try:
            matches = store.search_archived_room_newspaper_items(
                query,
                reader_date=reader_date or None,
                limit=limit,
            )
        except ValueError:
            return {"ok": False, "error": "date 要用 YYYY-MM-DD 格式。"}
        return {
            "ok": True,
            "mode": "search",
            "query": query,
            "date": reader_date or None,
            "count": len(matches),
            "matches": [
                {
                    "date": item["issue_date"],
                    "date_label": newspaper_date_label(item["issue_date"]),
                    "read": item["read"],
                    "position": item.get("position"),
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "url": item.get("url"),
                    "source": item.get("source_name"),
                }
                for item in matches
            ],
            "message": "没有照到相关旧报。" if not matches else f"在旧报里找到 {len(matches)} 条。",
        }

    if reader_date:
        try:
            issues = store.archived_room_newspaper_issues_for_date(reader_date)
        except ValueError:
            return {"ok": False, "error": "date 要用 YYYY-MM-DD 格式。"}
        delivered = [store.mark_room_newspaper_delivered(issue["id"]) or issue for issue in issues]
        return {
            "ok": True,
            "mode": "read",
            "date": reader_date,
            "count": len(delivered),
            "issues": [newspaper_payload(issue, reader_date=reader_date) for issue in delivered],
            "message": "这一天的旧报不在篓里。" if not delivered else f"翻开了{newspaper_date_label(reader_date)}的旧报。",
        }

    issues = store.list_archived_room_newspaper_issues(limit=limit)
    total = store.room_newspaper_archive_count()
    return {
        "ok": True,
        "mode": "list",
        "count": len(issues),
        "total": total,
        "has_more": total > len(issues),
        "issues": [
            {
                "date": issue["date"],
                "item_count": issue["item_count"],
                "read": issue["read"],
                "label": (
                    f"{newspaper_date_label(issue['date'])} · "
                    f"{issue['item_count']}条 · {'已读' if issue['read'] else '未读'}"
                ),
            }
            for issue in issues
        ],
        "message": "报纸篓还是空的。" if not issues else f"报纸篓里有 {total} 期旧报。",
    }
