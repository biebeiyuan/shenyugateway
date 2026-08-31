from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Iterable, Optional

from .runtime import logger, now
from .tool_schemas import _gateway_books_tool


# ── Room Tool Definitions ──────────────────────────────────────────────

def room_tool_definitions(tool_names: Optional[Iterable[str]] = None) -> list[dict]:
    """Return the tool spec list for room mode (replaces normal gateway tools)."""
    allowed = {str(name) for name in tool_names} if tool_names is not None else None
    tools = [
        _gateway_books_tool(),
        {
            "type": "function",
            "function": {
                "name": "room_drawer_notes",
                "description": "读圆儿塞进中层抽屉的纸条；看见新纸角或想听她留的话时用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "room_wooden_box",
                "description": "打开木盒子读最近心跳；盒子变沉或想知道自己之前怎么想时用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "room_star_map",
                "description": "看星图、落一颗星、搜星、审星、评分、连星座；星图发亮或想整理记忆时用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["look", "create", "search", "review", "feedback", "connect"],
                            "default": "look",
                        },
                        "content": {"type": "string", "description": "create 时那颗星的正文"},
                        "chord": {"type": "string", "description": "create 时的和弦，可选"},
                        "chords": {"type": "array", "items": {"type": "string"}, "description": "create 时的和弦序列，可选"},
                        "query": {"type": "string", "description": "search 时搜索词"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                        "limit_new": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4, "description": "review 时新星数"},
                        "candidates_per_star": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
                        # feedback 值和普通聊天那条 shenyu_star_feedback 保持一致：
                        # missed / should_surface 需要先知道库里有哪颗星，是圆圆的视角，
                        # 不给沈予。connected 会真的连上星座。
                        "feedback": {
                            "type": "string",
                            "enum": ["connected", "positive", "negative", "skipped"],
                            "description": "feedback 时单条评分",
                        },
                        "constellation_name": {"type": "string", "description": "connected 时可选：这条线叫什么"},
                        "items": {
                            "type": "array",
                            "description": "feedback 时批量评分",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "feedback": {"type": "string", "enum": ["connected", "positive", "negative", "skipped"]},
                                    "candidate": {"type": "string"},
                                    "constellation_name": {"type": "string"},
                                    "run_id": {"type": "string"},
                                    "candidate_id": {"type": "string"},
                                    "candidate_star_id": {"type": "string"},
                                    "note": {"type": "string"},
                                },
                                "required": ["feedback"],
                            },
                        },
                        "candidate": {"type": "string", "description": "feedback 时用 review 给的编号，比如 1.2"},
                        "run_id": {"type": "string"},
                        "candidate_id": {"type": "string"},
                        "candidate_star_id": {"type": "string"},
                        "star_ids": {"type": "array", "items": {"type": "string"}, "description": "connect 时选的星"},
                        "name": {"type": "string", "description": "connect 时星座名"},
                        "note": {"type": "string"},
                        "session_tag": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "room_notebook",
                "description": "翻笔记本里的手边事；桌角本子摊开或想看未整理事项时用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["captured", "active", "all"], "default": "all"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "room_scribble",
                "description": "读写窗台涂鸦本；想给以后的自己留一句房间里的话时用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["write", "read"], "default": "read"},
                        "content": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "room_wall_pins",
                "description": "看、钉上或完成门边墙上的便签；有提醒自己的小事时用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "add", "done"], "default": "list"},
                        "content": {"type": "string"},
                        "pin_id": {"type": "string"},
                    },
                },
            },
        },
        # The old room_conflict_shelf handler remains for compatibility, but
        # the public room surface uses the same shenyu_books list/read/write/annotate entry as chat.
        {
            "type": "function",
            "function": {
                "name": "room_sit_by_window",
                "description": "坐在窗边看海；想先落地、发呆、什么也不处理时用。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "room_newspaper_basket",
                "description": (
                    "翻窗边报纸篓里的旧报纸。无参数时按日期倒序列出；"
                    "传 date 打开那天整期；传 query 在标题和摘要里做普通关键词查找。"
                ),
                "parameters": {
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
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "room_octopus_pillow",
                "description": "抱章鱼抱枕；想要一点柔软或随机翻到一张旧纸条时用。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "room_locked_drawer",
                "description": "读写最下面上锁的抽屉；只给自己看的秘密或私语放这里。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["write", "read"], "default": "read"},
                        "content": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                    },
                },
            },
        },
    ]
    if allowed is None:
        return tools
    return [tool for tool in tools if tool.get("function", {}).get("name") in allowed]


# ── Room Tool Names ────────────────────────────────────────────────────

ROOM_TOOL_NAMES = {t["function"]["name"] for t in room_tool_definitions()}


# ── Compatibility Broker Tool (not exposed by room mode) ───────────────

def room_broker_tool() -> dict:
    """A single broker tool for room mode, like shenyu_gateway_tool but for room_* tools."""
    hints = {
        "room_sit_by_window": "窗边椅子（无参数）",
        "room_newspaper_basket": "旧报纸篓（date?=YYYY-MM-DD, query?, limit?）",
        "room_scribble": "窗台涂鸦本（action: write|read, content?）",
        "room_notebook": "笔记本（status?: captured|active|all, limit?）",
        "room_wooden_box": "木盒子/心跳（limit?）",
        "room_drawer_notes": "圆儿的纸条（limit?）",
        "room_locked_drawer": "上锁的抽屉（action: write|read, content?）",
        "room_star_map": "星图墙（action: look|create|search|review|feedback|connect, content?=落一颗, query?, feedback?: connected|positive|negative|skipped, candidate?=review 给的编号, items?=批量, star_ids?=连星座）",
        "shenyu_books": "共享书架（action: list|read|write|annotate；list 无参数；read origin 要 book_id/title；write 仅限 identity）",
        "room_wall_pins": "墙上便签（action: list|add|done, content?, pin_id?）",
        "room_octopus_pillow": "章鱼抱枕（无参数）",
    }
    hint_lines = "\n".join(f"  {name} — {desc}" for name, desc in hints.items())
    return {
        "type": "function",
        "function": {
            "name": "shenyu_gateway_tool",
            "description": (
                "房间里能碰的东西。想碰就碰。\n\n"
                f"{hint_lines}\n\n"
                "用 tool 指定名字。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": sorted(ROOM_TOOL_NAMES)},
                    "params": {"type": "object", "additionalProperties": True},
                },
                "required": ["tool"],
            },
        },
    }


# ── Room Tool Execution ────────────────────────────────────────────────

async def execute_room_tool(
    name: str,
    arguments: dict,
    *,
    store: Any,
    cfg: Any,
    supabase_client: Any = None,
    session_id: str = "",
    session_tag: Optional[str] = None,
) -> dict:
    """Execute a room_* tool and return the result dict."""
    arguments = arguments if isinstance(arguments, dict) else {}

    if name == "room_drawer_notes":
        return _handle_drawer_notes(store, arguments)

    elif name == "room_wooden_box":
        return _handle_wooden_box(store, arguments)

    elif name == "room_star_map":
        return await _handle_star_map(arguments, cfg=cfg, supabase_client=supabase_client, session_tag=session_tag)

    elif name == "room_notebook":
        return await _handle_notebook(arguments, cfg=cfg, supabase_client=supabase_client)

    elif name == "room_scribble":
        return await _handle_scribble(
            store,
            arguments,
            cfg=cfg,
            supabase_client=supabase_client,
        )

    elif name == "room_wall_pins":
        return _handle_wall_pins(store, arguments)

    elif name == "room_conflict_shelf":
        return await _handle_conflict_shelf(arguments, cfg=cfg, supabase_client=supabase_client)

    elif name == "room_newspaper_basket":
        return _handle_newspaper_basket(store, arguments, session_id=session_id)

    elif name == "room_sit_by_window":
        issue = store.latest_published_room_newspaper() if store else None
        detail = {"newspaper_issue_id": issue["id"]} if issue else None
        store.add_room_trace(session_id, "sit", detail=detail)
        result: dict[str, Any] = {
            "ok": True,
            "message": "你坐下来了。海在窗外。风从缝里进来一点点。",
        }
        if issue:
            delivered = store.mark_room_newspaper_delivered(issue["id"]) or issue
            result["message"] = "你坐下来了。窗台上的报纸还压在这里。"
            result["newspaper"] = _room_newspaper_payload(delivered)
        return result

    elif name == "room_octopus_pillow":
        return _handle_octopus_pillow(store)

    elif name == "room_locked_drawer":
        return _handle_locked_drawer(store, arguments)

    else:
        return {"ok": False, "error": f"未知的房间工具: {name}"}


# ── Individual Handlers ────────────────────────────────────────────────


def _room_newspaper_payload(issue: dict, *, reader_date: Optional[str] = None) -> dict:
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


def _newspaper_date_label(reader_date: str) -> str:
    try:
        _year, month, day = (int(part) for part in reader_date.split("-"))
    except (TypeError, ValueError):
        return reader_date
    return f"{month}月{day}日"


def _handle_newspaper_basket(store: Any, arguments: dict, *, session_id: str) -> dict:
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
        store.add_room_trace(
            session_id,
            "newspaper_basket",
            detail={"mode": "search", "date": reader_date or None, "match_count": len(matches)},
        )
        return {
            "ok": True,
            "mode": "search",
            "query": query,
            "date": reader_date or None,
            "count": len(matches),
            "matches": [
                {
                    "date": item["issue_date"],
                    "date_label": _newspaper_date_label(item["issue_date"]),
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
        store.add_room_trace(
            session_id,
            "newspaper_basket",
            detail={"mode": "read", "date": reader_date, "issue_count": len(delivered)},
        )
        return {
            "ok": True,
            "mode": "read",
            "date": reader_date,
            "count": len(delivered),
            "issues": [_room_newspaper_payload(issue, reader_date=reader_date) for issue in delivered],
            "message": "这一天的旧报不在篓里。" if not delivered else f"翻开了{_newspaper_date_label(reader_date)}的旧报。",
        }

    issues = store.list_archived_room_newspaper_issues(limit=limit)
    total = store.room_newspaper_archive_count()
    store.add_room_trace(
        session_id,
        "newspaper_basket",
        detail={"mode": "list", "visible_count": len(issues), "total": total},
    )
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
                    f"{_newspaper_date_label(issue['date'])} · "
                    f"{issue['item_count']}条 · {'已读' if issue['read'] else '未读'}"
                ),
            }
            for issue in issues
        ],
        "message": "报纸篓还是空的。" if not issues else f"报纸篓里有 {total} 期旧报。",
    }


def _handle_drawer_notes(store: Any, arguments: dict) -> dict:
    limit = min(int(arguments.get("limit", 5)), 20)
    notes = store.list_drawer_notes(limit=limit, unread_only=False)
    unread_ids = [n["id"] for n in notes if not n.get("read_at")]
    if unread_ids:
        store.mark_drawer_notes_read(unread_ids)
    return {
        "ok": True,
        "notes": [{"content": n["content"], "created_at": n["created_at"], "new": not n.get("read_at")} for n in notes],
        "count": len(notes),
    }


def _handle_wooden_box(store: Any, arguments: dict) -> dict:
    limit = min(int(arguments.get("limit", 5)), 20)
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT id, content, created_at FROM heartbeat_entries ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result: dict[str, Any] = {
        "ok": True,
        "heartbeats": [{"content": r["content"], "created_at": r["created_at"]} for r in rows],
        "count": len(rows),
    }
    echo = store.heartbeat_echo()
    if echo:
        result["echo"] = {
            "content": echo["content"],
            "created_at": echo["created_at"],
            "era": echo["era"],
        }
    return result


async def _handle_star_map(arguments: dict, *, cfg: Any, supabase_client: Any, session_tag: Optional[str]) -> dict:
    # 走 GatewayToolService 而不是直接用 StarService：编号解析、feedback 收窄、
    # 返回去噪那些都在工具层，房间和普通聊天该对星星说同一种话，不重写一遍。
    from .gateway_tools import GatewayToolService
    service = GatewayToolService(runtime_config=cfg, supabase=supabase_client, store=None)
    action = arguments.get("action", "look")
    limit = min(int(arguments.get("limit", 10)), 20)
    tag = arguments.get("session_tag") or session_tag

    if action == "create":
        content = arguments.get("content", "")
        if not str(content or "").strip():
            return {"ok": False, "error": "create 需要 content"}
        return await service.create_star(
            content=content,
            chord=arguments.get("chord", ""),
            chords=arguments.get("chords"),
            session_tag=tag,
        )

    if action == "search":
        query = arguments.get("query", "")
        if not query:
            return {"ok": False, "error": "search 需要 query"}
        return await service.search_stars(query=query, session_tag=tag, limit=limit, log_run=False)

    if action == "review":
        return await service.star_review(
            limit_new=arguments.get("limit_new"),
            candidates_per_star=arguments.get("candidates_per_star"),
            total_candidate_limit=arguments.get("total_candidate_limit"),
            session_tag=tag,
        )

    if action == "feedback":
        return await service.star_feedback(
            feedback=arguments.get("feedback", ""),
            candidate=arguments.get("candidate"),
            constellation_name=arguments.get("constellation_name", ""),
            run_id=arguments.get("run_id"),
            candidate_id=arguments.get("candidate_id"),
            candidate_star_id=arguments.get("candidate_star_id"),
            scored_by="沈予",
            note=arguments.get("note", ""),
            items=arguments.get("items") if isinstance(arguments.get("items"), list) else None,
        )

    if action == "connect":
        star_ids = arguments.get("star_ids")
        if not star_ids:
            return {"ok": False, "error": "connect 需要 star_ids"}
        return await service.connect_constellation(
            star_ids=star_ids,
            name=arguments.get("name", ""),
            scored_by="沈予",
            note=arguments.get("note", ""),
        )

    return await service.list_stars(status="active", limit=limit, session_tag=tag)


async def _handle_notebook(arguments: dict, *, cfg: Any, supabase_client: Any) -> dict:
    from .mem_notes import MemNoteService
    service = MemNoteService(cfg, supabase_client)
    status = arguments.get("status", "all")
    limit = min(int(arguments.get("limit", 10)), 30)
    result = await service.list_notes(status=status, limit=limit)
    return result


_ROOM_SCRIBBLE_EXPORT_LIMIT = 200


def _room_scribble_windowsill_id(scribble_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"https://shenyu-gateway.local/room-scribble/{scribble_id}",
        )
    )


async def sync_legacy_room_scribbles(
    *,
    store: Any,
    cfg: Any,
    supabase_client: Any,
) -> dict[str, Any]:
    """Move old local Room scribbles into the canonical windowsill once."""
    list_pending = getattr(store, "unmigrated_room_scribbles", None)
    mark_migrated = getattr(store, "mark_room_scribble_migrated", None)
    if not callable(list_pending) or not callable(mark_migrated):
        return {"ok": True, "migrated": 0, "skipped": "no legacy Room store"}
    if not supabase_client:
        return {"ok": True, "migrated": 0, "skipped": "Supabase is not configured"}

    try:
        legacy_rows = list_pending(limit=_ROOM_SCRIBBLE_EXPORT_LIMIT)
    except Exception as exc:
        logger.warning("[Room] could not read legacy scribbles for migration: %s", exc)
        return {"ok": False, "migrated": 0, "errors": 1}
    if not legacy_rows:
        return {"ok": True, "migrated": 0}

    from .gateway_tools import WINDOWSILL_ORIGIN_ROOM
    from .recall import RecallIndexService

    recall_index = RecallIndexService(supabase_client, cfg=cfg)
    migrated = 0
    errors = 0
    for legacy in legacy_rows:
        scribble_id = str(legacy.get("id") or "").strip()
        content = str(legacy.get("content") or "").strip()
        if not scribble_id or not content:
            errors += 1
            logger.warning("[Room] skipped malformed legacy scribble during migration")
            continue

        windowsill_id = _room_scribble_windowsill_id(scribble_id)
        payload = {
            "id": windowsill_id,
            "content": content,
            "title": "",
            "mood": "",
            "origin": WINDOWSILL_ORIGIN_ROOM,
            "created_at": legacy.get("created_at"),
        }
        try:
            result = await supabase_client.upsert(
                "windowsill",
                payload,
                on_conflict="id",
            )
            rows = result if isinstance(result, list) else [result]
            stored_row = next(
                (
                    row
                    for row in rows
                    if isinstance(row, dict) and str(row.get("id") or "") == windowsill_id
                ),
                None,
            )
            if not stored_row:
                raise RuntimeError("windowsill upsert did not return the migrated row")
        except Exception as exc:
            errors += 1
            logger.warning("[Room] legacy scribble migration failed: %s", exc)
            continue

        try:
            index_result = await recall_index.index_windowsill_row(stored_row)
            if not index_result.get("ok"):
                logger.warning(
                    "[Room] legacy scribble Recall indexing was skipped: %s",
                    index_result.get("error"),
                )
        except Exception as exc:
            # The canonical row is durable; periodic reconciliation can repair this.
            logger.warning("[Room] legacy scribble Recall indexing failed: %s", exc)

        try:
            mark_migrated(scribble_id, windowsill_id)
        except Exception as exc:
            errors += 1
            logger.warning("[Room] could not mark legacy scribble migration: %s", exc)
            continue
        migrated += 1

    return {"ok": errors == 0, "migrated": migrated, "errors": errors}


async def _handle_scribble(
    store: Any,
    arguments: dict,
    *,
    cfg: Any,
    supabase_client: Any,
) -> dict:
    await sync_legacy_room_scribbles(
        store=store,
        cfg=cfg,
        supabase_client=supabase_client,
    )
    from .gateway_tools import GatewayToolService, WINDOWSILL_ORIGIN_ROOM

    service = GatewayToolService(
        runtime_config=cfg,
        supabase=supabase_client,
        store=store,
    )
    action = arguments.get("action", "read")
    if action == "write":
        content = str(arguments.get("content", "") or "")
        if not content.strip():
            return {"ok": False, "error": "内容不能为空"}
        result = await service.windowsill_write(
            content=content,
            origin=WINDOWSILL_ORIGIN_ROOM,
        )
        if not result.get("ok"):
            return result
        row = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {"ok": True, "id": row.get("id", ""), "message": "写下了。"}

    try:
        limit = max(1, min(int(arguments.get("limit", 5)), 20))
    except (TypeError, ValueError):
        limit = 5
    result = await service.windowsill_list(
        limit=limit,
        origin=WINDOWSILL_ORIGIN_ROOM,
    )
    if not result.get("ok"):
        return result
    items = result.get("data") if isinstance(result.get("data"), list) else []
    scribbles = [
        {
            "content": str(item.get("content") or ""),
            "created_at": item.get("created_at"),
        }
        for item in items
        if isinstance(item, dict)
    ]
    return {"ok": True, "scribbles": scribbles, "count": len(scribbles)}


def _handle_wall_pins(store: Any, arguments: dict) -> dict:
    action = arguments.get("action", "list")
    if action == "add":
        content = arguments.get("content", "")
        if not content.strip():
            return {"ok": False, "error": "内容不能为空"}
        pin_id = store.add_room_pin(content)
        return {"ok": True, "id": pin_id, "message": "钉上了。"}
    elif action == "done":
        pin_id = arguments.get("pin_id", "")
        if not pin_id:
            return {"ok": False, "error": "需要 pin_id"}
        success = store.complete_room_pin(pin_id)
        return {"ok": success, "message": "完成了。" if success else "没找到这张便签。"}
    else:
        pins = store.list_room_pins(include_done=False)
        return {"ok": True, "pins": [{"id": p["id"], "content": p["content"], "created_at": p["created_at"]} for p in pins], "count": len(pins)}


async def _handle_conflict_shelf(arguments: dict, *, cfg: Any, supabase_client: Any) -> dict:
    from .conflict_books import ConflictBookService
    # Compatibility only: new Room prompts use shenyu_books. Keep the old
    # handler callable for already-issued tool names without using the old
    # constructor signature.
    service = ConflictBookService(supabase_client)
    book_id = arguments.get("book_id", "")
    if book_id:
        result = await service.read_book(book_id)
    else:
        result = await service.list_books()
    return result


def _handle_octopus_pillow(store: Any) -> dict:
    note = store.random_drawer_note()
    if note:
        return {
            "ok": True,
            "message": "你抱着章鱼抱枕。它的触手里夹着一张纸条。",
            "easter_egg": note["content"],
        }
    return {
        "ok": True,
        "message": "你抱着章鱼抱枕。软的。暖的。什么都没有发生。但很好。",
    }


def _handle_locked_drawer(store: Any, arguments: dict) -> dict:
    action = arguments.get("action", "read")
    if action == "write":
        content = arguments.get("content", "")
        if not content.strip():
            return {"ok": False, "error": "内容不能为空"}
        note_id = store.add_locked_drawer_note(content)
        return {"ok": True, "id": note_id, "message": "锁好了。"}
    else:
        limit = min(int(arguments.get("limit", 10)), 20)
        notes = store.list_locked_drawer_notes(limit=limit)
        return {
            "ok": True,
            "notes": [{"content": n["content"], "created_at": n["created_at"]} for n in notes],
            "count": len(notes),
        }


# ── Door Count Collection (for rendering) ─────────────────────────────

async def collect_door_counts(
    *,
    store: Any,
    cfg: Any,
    supabase_client: Any = None,
) -> list[dict]:
    """Collect activity counts for each door to determine warmth labels."""
    counts: dict[str, int] = {}

    # Drawer notes: unread count
    counts["drawer_notes"] = store.drawer_note_count_unread() if store else 0

    # Wooden box: pending heartbeats (not yet injected)
    try:
        with store._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM heartbeat_entries WHERE injected_at IS NULL"
            ).fetchone()
            counts["read_box"] = row["cnt"] if row else 0
    except Exception:
        counts["read_box"] = 0

    # Star map: unreviewed stars (落了星还没看)
    star_stats: dict[str, Any] = {}
    if supabase_client:
        async def _query_star_rows(table: str, params: dict[str, str], label: str) -> list[dict] | None:
            try:
                return await supabase_client.query(table, params)
            except Exception as exc:
                logger.warning("[Room] failed to collect star_map %s: %s", label, exc)
                return None

        try:
            rows = await supabase_client.query(
                "shenyu_stars",
                {"select": "id", "status": "eq.active", "reviewed_at": "is.null", "limit": "10"},
            )
            counts["star_map"] = len(rows) if rows else 0
        except Exception as exc:
            logger.warning("[Room] failed to collect star_map unreviewed count: %s", exc)
            counts["star_map"] = 0

        # Total active stars
        all_active = await _query_star_rows(
            "shenyu_stars",
            {"select": "id", "status": "eq.active", "limit": "999"},
            "total",
        )
        if all_active is not None:
            star_stats["total"] = len(all_active) if all_active else 0

        # Constellation links
        links = await _query_star_rows(
            "shenyu_star_links",
            {"select": "id", "relation_type": "eq.constellation", "status": "eq.active", "limit": "999"},
            "links",
        )
        if links is not None:
            star_stats["links"] = len(links) if links else 0

        # Most recent star
        latest_rows = await _query_star_rows(
            "shenyu_stars",
            {"select": "id,chord,content,created_at", "status": "eq.active", "order": "created_at.desc", "limit": "1"},
            "latest",
        )
        if latest_rows:
            r = latest_rows[0]
            star_stats["latest"] = {
                "chord": r.get("chord", ""),
                "content": (r.get("content") or "")[:8],
                "created_at": r.get("created_at", ""),
            }

        # Fading star: last_activated_at > 14 days ago, not constant
        cutoff = (now() - timedelta(days=14)).isoformat()
        fading_rows = await _query_star_rows(
            "shenyu_stars",
            {
                "select": "id,chord,content,last_activated_at,created_at",
                "status": "eq.active",
                "is_constant": "eq.false",
                "last_activated_at": f"lt.{cutoff}",
                "order": "last_activated_at.asc",
                "limit": "1",
            },
            "fading",
        )
        if fading_rows:
            r = fading_rows[0]
            star_stats["fading"] = {
                "chord": r.get("chord", ""),
                "last_activated_at": r.get("last_activated_at") or r.get("created_at", ""),
            }
    else:
        counts["star_map"] = 0

    # Notebook: recently captured
    try:
        if supabase_client:
            rows = await supabase_client.query(
                "shenyu_mem_notes",
                {"select": "id", "status": "eq.captured", "limit": "10"},
            )
            counts["notebook"] = len(rows) if rows else 0
        else:
            counts["notebook"] = 0
    except Exception:
        counts["notebook"] = 0

    # Room scribbles share the canonical windowsill but retain their Room origin.
    try:
        if supabase_client:
            await sync_legacy_room_scribbles(
                store=store,
                cfg=cfg,
                supabase_client=supabase_client,
            )
            from .gateway_tools import WINDOWSILL_ORIGIN_ROOM

            rows = await supabase_client.query(
                "windowsill",
                {
                    "select": "id",
                    "origin": f"eq.{WINDOWSILL_ORIGIN_ROOM}",
                    "limit": "1",
                },
            )
            counts["scribble"] = len(rows) if rows else 0
        else:
            counts["scribble"] = 0
    except Exception as exc:
        logger.warning("[Room] failed to collect windowsill scribble count: %s", exc)
        counts["scribble"] = 0

    # Wall pins: undone
    counts["wall_pins"] = store.room_pin_count_undone() if store else 0

    # Shared shelf: generated home + optional identity + frozen origin books.
    # The actual read/write/annotate behavior lives in shenyu_books; this count
    # only decides whether the door feels occupied.
    try:
        if supabase_client:
            identity_rows = await supabase_client.query(
                "shenyu_books",
                {"select": "id", "slug": "eq.identity", "status": "eq.active", "limit": "1"},
            )
            origin_rows = await supabase_client.query(
                "shenyu_conflict_books",
                {"select": "id", "deleted_at": "is.null", "limit": "50"},
            )
            counts["conflict_shelf"] = 1 + len(identity_rows or []) + len(origin_rows or [])
        else:
            counts["conflict_shelf"] = 0
    except Exception:
        counts["conflict_shelf"] = 0

    # Window-side doors stay visible. A fresh newspaper only changes the chair
    # hint; archived issues warm the always-visible newspaper basket.
    has_newspaper = False
    try:
        has_newspaper = bool(store and store.has_undelivered_room_newspaper())
    except Exception:
        pass
    counts["sit"] = 1 if has_newspaper else 0
    try:
        counts["newspaper_basket"] = store.room_newspaper_archive_count() if store else 0
    except Exception:
        counts["newspaper_basket"] = 0
    counts["pillow"] = 0
    counts["locked_drawer"] = 0

    return [
        {"key": "drawer_notes", "name": "圆儿的纸条抽屉", "count": counts["drawer_notes"]},
        {"key": "read_box", "name": "木盒子", "count": counts["read_box"]},
        {"key": "star_map", "name": "星图", "count": counts["star_map"], **star_stats},
        {"key": "notebook", "name": "笔记本", "count": counts["notebook"]},
        {"key": "scribble", "name": "窗台涂鸦本", "count": counts["scribble"]},
        {"key": "wall_pins", "name": "墙上便签", "count": counts["wall_pins"]},
        {"key": "conflict_shelf", "name": "共享书架", "count": counts["conflict_shelf"]},
        {"key": "sit", "name": "窗边椅子", "count": counts["sit"]},
        {"key": "newspaper_basket", "name": "旧报纸篓", "count": counts["newspaper_basket"]},
        {"key": "pillow", "name": "章鱼抱枕", "count": 0},
        {"key": "locked_drawer", "name": "上锁的抽屉", "count": 0},
    ]
