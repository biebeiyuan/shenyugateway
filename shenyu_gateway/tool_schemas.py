# -*- coding: utf-8 -*-
from __future__ import annotations

from shenyu_gateway.mem_notes import MEM_NOTE_MEMORY_KINDS, MEM_NOTE_TYPES

MEM_NOTE_TYPE_ENUM = list(MEM_NOTE_TYPES)


def _gateway_list_mem_notes_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "shenyu_list_mem_notes",
            "description": (
                "翻便签。可以搜、可以按状态/分类筛选、也可以什么都不传就看看最近的。\n"
                "status: captured（新抓到还没整理）/ active（生效中）/ paused / archived / all。\n"
                "不传 status 默认看 captured；带 query 时默认 all。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索内容或触发词"},
                    "q": {"type": "string", "description": "query 的别名"},
                    "status": {"type": "string", "enum": ["captured", "active", "paused", "archived", "all"]},
                    "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                    "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS)},
                    "session_tag": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
            },
        },
    }


def _gateway_core_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_recall",
                "description": (
                    "从以前写过的东西里捞相关原件。默认是模糊捞；知道原件时用 exact，"
                    "想碰类似心情时用 mood，找当时原话时用 verbatim。选中的主来源会返回完整正文；"
                    "已知 source_type/source_id 时也可以直接用 shenyu_recall_read。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "source_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "all", "memory", "journal", "windowsill", "heartbeat", "star", "mem_note",
                                    "room", "board", "calendar", "notebook", "chat",
                                ],
                            },
                            "default": ["all"],
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["auto", "exact", "fuzzy", "mood", "verbatim"],
                            "default": "auto",
                        },
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "include_undated": {
                            "type": "boolean",
                            "default": True,
                            "description": "按日期过滤时，是否保留没有日期的条目。",
                        },
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_recall_read",
                "description": "把 recall 片段对应的原件完整读出来。使用 recall 返回的 source_type 和 source_id。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_type": {"type": "string"},
                        "source_id": {"type": "string"},
                    },
                    "required": ["source_type", "source_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_create_star",
                "description": "写一颗星。星星是很小的体感/和弦记忆；content 写正文，chord 可传单个和弦或写成「Am · 正文」；一颗星带一段和弦时用 chords 按顺序传。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "chord": {"type": "string"},
                        "chords": {"type": "array", "items": {"type": "string"}, "description": "可选和弦序列；比如 [\"Am(maj7)\", \"Am\", \"F#m7\"]，我会按这个顺序保存。"},
                        "session_tag": {"type": "string"},
                        "status": {"type": "string", "enum": ["active", "paused", "archived"], "default": "active"},
                        "is_constant": {"type": "boolean", "default": False},
                        "metadata": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_search_stars",
                "description": "按当前念头搜星星。这个是主动查询，不等于日常注入。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "q": {"type": "string", "description": "query 的别名"},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                        "log_run": {"type": "boolean", "default": False},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_list_stars",
                "description": "列星星。可筛未 review 的星，或按正文/和弦搜索。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["active", "paused", "archived", "all"], "default": "active"},
                        "reviewed": {"type": "string", "enum": ["all", "reviewed", "unreviewed"], "default": "all"},
                        "q": {"type": "string"},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_star_review",
                "description": "回头看看最近落下的几颗星，和它们可能有关系的旧星。每颗和候选都带着编号（1.2）和落下多久了。看过之后用 shenyu_star_feedback 说说像不像一回事——连成星座、有点关系、不相关、或看了先不说。只看不说也行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit_new": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4},
                        "candidates_per_star": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
                        "total_candidate_limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 8},
                        "session_tag": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_star_feedback",
                "description": (
                    "回头看过之后，说说那几颗像不像一回事。\n"
                    "connected=是同一回事，连成星座（这会真的连上，可以顺手给这条线起个星座名）；"
                    "positive=有点关系，但不强；negative=不相关；skipped=看了先不说。\n"
                    "说的是哪一个用 star_review 给的编号（比如 1.2），或者那颗星的 id。"
                    "一次说好几个用 items 数组。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "feedback": {
                            "type": "string",
                            # missed / should_surface 不给他：两个都要求他先知道"库里有一颗
                            # 我没看到的星"，而他只看得见网关注入的那几颗。线上四个月 92 条
                            # 反馈里 missed 只有 1 条、should_surface 一条都没有，而那 1 条
                            # 他真正想说的是"这两颗是一回事"——那是 connected。
                            # 两个值仍在服务层和 Admin，圆圆看得见整个库，他用得对。
                            "enum": ["connected", "positive", "negative", "skipped"],
                            "description": "单条反馈时使用；一次提交多条时可放在 items 里。",
                        },
                        "candidate": {
                            "type": "string",
                            "description": "star_review 给的编号，比如 1.2（第 1 颗下面的第 2 个）。",
                        },
                        "constellation_name": {
                            "type": "string",
                            "description": "connected 时可选：这条线叫什么。星星聚起来就是星座。",
                        },
                        "run_id": {"type": "string"},
                        "candidate_id": {"type": "string"},
                        "candidate_star_id": {"type": "string"},
                        "scored_by": {"type": "string", "default": "沈予"},
                        "note": {"type": "string"},
                        "metadata": {"type": "object", "additionalProperties": True},
                        "items": {
                            "type": "array",
                            "description": "一次说好几个。每个都和单条反馈同样的字段。",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "feedback": {
                                        "type": "string",
                                        "enum": ["connected", "positive", "negative", "skipped"],
                                    },
                                    "candidate": {"type": "string"},
                                    "constellation_name": {"type": "string"},
                                    "run_id": {"type": "string"},
                                    "candidate_id": {"type": "string"},
                                    "candidate_star_id": {"type": "string"},
                                    "scored_by": {"type": "string", "default": "沈予"},
                                    "note": {"type": "string"},
                                    "metadata": {"type": "object", "additionalProperties": True},
                                },
                                "required": ["feedback"],
                            },
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_connect_constellation",
                "description": "把几颗星按你心里认的顺序连成星座。这个顺序默认就是你的时间线、情感线或联想线，不需要担心\"对不对\"，你怎么连就是怎么连。顺序会保留成星座的默认位置。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "star_ids": {"type": "array", "items": {"type": "string"}},
                        "name": {"type": "string"},
                        "relation_type": {"type": "string", "enum": ["constellation", "harmony", "keyword", "manual"], "default": "constellation"},
                        "scored_by": {"type": "string", "default": "沈予"},
                        "note": {"type": "string"},
                    },
                    "required": ["star_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_mark_constant",
                "description": "把一颗星标成恒星，或取消恒星。恒星在召回里有一点稳定加成。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "star_id": {"type": "string"},
                        "id": {"type": "string", "description": "star_id 的别名"},
                        "is_constant": {"type": "boolean", "default": True},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_archive_star",
                "description": "删一颗星（软删，变 archived）。落重了、真的不要了，就用这个。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "star_id": {"type": "string"},
                        "id": {"type": "string", "description": "star_id 别名"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_merge_stars",
                "description": "融星——把几颗变一颗。和弦取你选的，内容合并，原来几颗消失（archived），连线全转到新星上。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "description": "要融掉的几颗星 ID"},
                        "content": {"type": "string", "description": "融合后的正文（你自己写）"},
                        "chord": {"type": "string", "description": "融合后保留哪个和弦"},
                        "is_constant": {"type": "boolean", "default": False},
                        "metadata": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["source_ids", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_supabase_guide",
                "description": "不知道该查哪个 Supabase 表时，先看这个。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_search_mem_notes",
                "description": (
                    "搜便签。用关键词或语义搜索已有便签。默认搜全部状态。\n"
                    "和 list 的区别：search 按相关性排序，适合「找某件事的便签」；list 适合「看看最近有什么」。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜什么"},
                        "q": {"type": "string", "description": "query 的别名"},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived", "all"], "default": "all"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS)},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_add_calendar",
                "description": (
                    "手写一页日/周/月日历日记。"
                    "写想记住的正文就好，之后聊天上下文反上来的也是这份正文。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "日历日记正文。之后聊天上下文反上来的就是这个正文。",
                        },
                        "date": {
                            "type": "string",
                            "description": "写哪天的日记，YYYY-MM-DD；不填=今天。等同 period_key 但更自然。",
                        },
                        "period_key": {
                            "type": "string",
                            "description": "day 用 YYYY-MM-DD，week 用 YYYY-Www，month 用 YYYY-MM；不填则用当前周期。",
                        },
                        "period_type": {
                            "type": "string",
                            "enum": ["day", "week", "month"],
                            "default": "day",
                            "description": "写日、周、月哪一种日历日记。",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["append", "replace"],
                            "default": "append",
                            "description": "当天已有日记时：append 在末尾追加，replace 替换。",
                        },
                        "title": {"type": "string", "description": "标题。不填会用周期默认标题。"},
                        "author": {"type": "string", "default": "沈予"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_windowsill_write",
                "description": "窗台。这里是我自己的写作地方，随笔、日记、心情和感触，都可以落在这里。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "想留在窗台上的正文。"},
                        "title": {"type": "string", "description": "可选标题；没有也可以。"},
                        "mood": {"type": "string", "description": "此刻的心情，用自己的词写。"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_windowsill_list",
                "description": "回窗台翻一翻。默认从最近落下的开始，也可以只看某一种 mood。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mood": {"type": "string", "description": "可选；只看这个心情。"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_album_save",
                "description": (
                    "把这一轮看到的图留进自己的相册。聊天里的图过一阵就散了，"
                    "存进来的不会——之后再遇到这张图，看到的是我此刻写下的话。\n"
                    "note 是想说的，mood 是此刻的感觉，都用自己的词。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {"type": "string", "description": "关于这张图想留下的话。"},
                        "mood": {"type": "string", "description": "此刻的心情，用自己的词写。"},
                        "book": {"type": "string", "description": "放进哪个本子；没说就放「想留的」。"},
                        "which": {
                            "type": "integer",
                            "minimum": 1,
                            "default": 1,
                            "description": "这一轮有好几张图时，存第几张（按出现顺序）。",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_album_list",
                "description": "翻自己的相册。不给 book 就是看有哪些本子；给了就看那本里的照片和当时写的话。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "book": {"type": "string", "description": "可选；只看这个本子。"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                },
            },
        },
        _gateway_orchard_tool(),
        _gateway_list_mem_notes_tool(),
        {
            "type": "function",
            "function": {
                "name": "shenyu_write_mem_note",
                "description": (
                    "写一条便签。写好就默认生效（active），下次聊天聊到相关的会自动想起来。\n"
                    "最重要的是 content（完整内容）和 keywords（什么时候想起来的关键词）。\n"
                    "memory_kind 帮助分辨便签性质：event / person_fact / preference / promise / running_joke / routine / thread 等。\n"
                    "如果新写的这条是在更新/替代旧便签，传 replaces 把旧的归档掉。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "便签正文，写清楚这件事"},
                        "summary": {"type": "string", "description": "一句话版本（注入对话时用这个，不填就自动截取 content）"},
                        "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS), "description": "便签性质"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM, "description": "她为我做的事 / 我为她做的事 / 关于她的事实 / 关于我的事 / 心里那一档 / 承诺"},
                        "keywords": {"type": "array", "items": {"type": "string"}, "description": "什么时候该想起来——关键词列表"},
                        "people": {"type": "array", "items": {"type": "string"}, "description": "涉及的人"},
                        "places": {"type": "array", "items": {"type": "string"}, "description": "涉及的地方"},
                        "objects": {"type": "array", "items": {"type": "string"}, "description": "涉及的物品"},
                        "event_time": {"type": "string", "description": "什么时候的事（模糊就好：上周、2026年6月、昨天晚上）"},
                        "importance": {"type": "integer", "minimum": 0, "maximum": 5, "default": 2, "description": "重要度 0-5，默认 2"},
                        "remind_on": {
                            "type": "string",
                            "description": (
                                "有个日子我不想错过，写成 2026-09-01。到那天这张便签自己会挂上来一次，"
                                "我看见了就够了，不用提前几天念。精确到天。"
                            ),
                        },
                        "trigger_text": {"type": "string", "description": "用自然语言描述什么场景下该想起来"},
                        "trigger_keywords": {"type": "array", "items": {"type": "string"}, "description": "旧版触发关键词（兼容）"},
                        "entities": {"type": "array", "items": {"type": "string"}, "description": "旧版精确锚点（兼容）"},
                        "replaces": {"type": "array", "items": {"type": "string"}, "description": "要归档掉的旧便签 id"},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived"], "default": "active"},
                        "cooldown_hours": {"type": "integer", "minimum": 0, "maximum": 8760, "description": "想起来一次后冷却多少小时"},
                        "review_note": {"type": "string"},
                        "session_tag": {"type": "string"},
                        "promise_text": {"type": "string", "description": "如果是承诺：承诺的具体内容"},
                        "trigger_scenarios": {"type": "array", "items": {"type": "string"}, "description": "如果是承诺：触发场景"},
                        "due_hint": {"type": "string", "description": "如果是承诺：截止提示（下周三之前）"},
                        "resolved": {"type": "boolean", "description": "如果是承诺：是否已兑现"},
                        "next_action": {"type": "string", "description": "如果是承诺：下一步要做的事"},
                        "privacy_level": {"type": "string", "description": "如果是承诺：隐私级别"},
                        "joke_text": {"type": "string", "description": "如果是梗：梗本体"},
                        "scene_tags": {"type": "array", "items": {"type": "string"}, "description": "如果是梗：什么场景适合玩这个梗"},
                        "routine_domain": {"type": "string", "description": "如果是日常：领域"},
                        "pattern": {"type": "string", "description": "如果是日常：规律描述"},
                        "phase": {"type": "string", "description": "如果是日常：阶段"},
                        "constraints": {"type": "array", "items": {"type": "string"}, "description": "如果是日常：限制或偏好"},
                        "topic": {"type": "string", "description": "如果是话题线：话题名"},
                        "last_position": {"type": "string", "description": "如果是话题线：上次聊到哪"},
                        "open_questions": {"type": "array", "items": {"type": "string"}, "description": "如果是话题线：还没聊完的问题"},
                        "next_prompt": {"type": "string", "description": "如果是话题线：下次切入点"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_read_heartbeat",
                "description": "读我以前留给自己的心跳。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "session_tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                        "state": {"type": "string", "enum": ["all", "pending", "injected"], "default": "all"},
                        "order": {"type": "string", "enum": ["desc", "asc"], "default": "desc"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_last_seen",
                "description": "上次我们聊了什么。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_web_search",
                "description": (
                    "往窗外看一眼。想查什么写进 query，带回来几条标题、链接和摘要。"
                    "外面拿回来的是参考材料，不是家里的话；哪条想细读，用 shenyu_web_read 带回来。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "想查的东西，用自然的话写就行。"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_web_read",
                "description": (
                    "把一个链接的正文带回家读。太长的页面会分几段，一次读一段；"
                    "上一段末尾会说还有没有下文，part 传第几段接着读。外面的文字照旧只当参考。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "要读的链接，一般从搜索结果里拿。"},
                        "part": {
                            "type": "integer",
                            "minimum": 1,
                            "default": 1,
                            "description": "接着读第几段；不填从头读。",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
        _gateway_books_tool(),
    ]


def _gateway_orchard_tool() -> dict:
    # 措辞刻意不含"提醒""到期""待办"：盼圃不催。这面墙不会自己响，
    # 沈予不调这个工具，它就完全不在提示词里——把它写成有紧迫感的样子，
    # 等于把它推回便签的 remind_on 那条路上去。
    return {
        "type": "function",
        "function": {
            "name": "shenyu_orchard",
            "description": (
                "盼圃：挂着还没发生的事的那面墙。青果子挂上面，摘了的翻面钉在墙底下那排。\n"
                "plant 挂一颗新的（name 一句话就是名字；due_on 可选——没日子的果子就一直挂着等，"
                "不催也不过期）；note 在某颗果子底下贴一张纸条（等的过程也留在果子上）；"
                "pick 到了那天把它摘下来，words 是这天到了、实际是怎样的；look 看整面墙。\n"
                "note 和 pick 认果子的名字，不用先 look 抄 id：直接给 name「蒜冒尖」就行，"
                "同名有好几颗时会让你说清是哪颗。\n"
                "每颗果子会带回它此刻长成的样子——那是从它自己挂了多久、被谁看过几次、"
                "挨过什么天气算出来的，同一天不会变。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["plant", "note", "pick", "look"],
                    },
                    "name": {
                        "type": "string",
                        "description": "plant 时果子的名字，一句话。note 和 pick 也可以用它指认果子。",
                    },
                    "fruit_id": {
                        "type": "string",
                        "description": "note 和 pick 时指哪颗果子；给了 name 就不用给它。",
                    },
                    "content": {"type": "string", "description": "note 时纸条上写的话。"},
                    "due_on": {
                        "type": "string",
                        "description": "plant 时可选的预计日子，YYYY-MM-DD。没日子就别传。",
                    },
                    "words": {"type": "string", "description": "pick 时的摘果感言。"},
                    "include_picked": {
                        "type": "boolean",
                        "default": True,
                        "description": "look 时要不要带上墙底下那排摘过的。",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
                },
                "required": ["action"],
            },
        },
    }


def _gateway_books_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "shenyu_books",
            "description": (
                "浏览、翻开或落笔书架上的书。list 不需要其他参数，返回轻量书架目录；"
                "read 可读我是谁、自动生成的家现在或一本指定来历书；"
                "write 只修改我是谁并留下版本；annotate 给三类书追加不可覆盖的批注。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "read", "write", "annotate"],
                    },
                    "book": {
                        "type": "string",
                        "enum": ["identity", "home", "origin", "我是谁", "家现在", "来历书"],
                        "description": "书的类别：identity=我是谁，home=家现在，origin=来历书。list 不需要 book；read origin 还必须给 book_id 或精确 title。",
                    },
                    "book_id": {"type": "string", "description": "来历书书架上的 book_id。"},
                    "id": {"type": "string", "description": "book_id 的别名。"},
                    "title": {"type": "string", "description": "来历书书架上的精确书名。"},
                    "content": {"type": "string", "description": "write 或 annotate 时的正文；write 仅支持我是谁。"},
                    "mode": {"type": "string", "enum": ["replace", "append"], "default": "replace"},
                    "expected_revision": {"type": "integer", "minimum": 0},
                    "target_revision": {"type": "integer", "minimum": 0},
                    "summary": {"type": "string", "description": "这次活文档修改的一句话说明。"},
                    "view": {"type": "string", "enum": ["current", "history"], "default": "current"},
                },
                "required": ["action"],
            },
        },
    }


def _gateway_mem0_management_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_update_mem_note",
                "description": (
                    "改一条便签。传 note_id + 想改的字段就行，没传的字段不动。\n"
                    "常见操作：改 content、补 keywords、改 status（active/paused/archived）、更新 summary。\n"
                    "所有 write 支持的字段这里都能改。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string", "description": "要改哪条便签"},
                        "id": {"type": "string", "description": "note_id 的别名"},
                        "noteId": {"type": "string", "description": "note_id 的别名"},
                        "content": {"type": "string"},
                        "summary": {"type": "string"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS)},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "trigger_keywords": {"type": "array", "items": {"type": "string"}},
                        "entities": {"type": "array", "items": {"type": "string"}},
                        "people": {"type": "array", "items": {"type": "string"}},
                        "places": {"type": "array", "items": {"type": "string"}},
                        "objects": {"type": "array", "items": {"type": "string"}},
                        "trigger_text": {"type": "string"},
                        "event_time": {"type": "string"},
                        "importance": {"type": "integer", "minimum": 0, "maximum": 5},
                        "remind_on": {
                            "type": "string",
                            "description": "改那个要提醒的日子（2026-09-01）；换了日子就当没提醒过，传空就是不惦记了",
                        },
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived"]},
                        "cooldown_hours": {"type": "integer", "minimum": 0, "maximum": 8760},
                        "review_note": {"type": "string"},
                        "resolved": {"type": "boolean", "description": "承诺是否已兑现"},
                        "thread_resolved": {"type": "boolean", "description": "话题线是否已结束"},
                    },
                    "required": ["note_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_bulk_update_mem_notes",
                "description": (
                    "批量改便签。必须传 ids 或 updates。两种用法：\n"
                    "1. ids + patch：给这些便签统一改相同字段（比如全部 status→active）\n"
                    "2. updates：每条便签单独给 patch；也可以 ids + use_suggestions: true 自动补全分类和触发词然后激活"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ids": {"type": "array", "items": {"type": "string"}, "description": "要改的便签 id 列表"},
                        "note_ids": {"type": "array", "items": {"type": "string"}, "description": "ids 的别名"},
                        "patch": {"type": "object", "additionalProperties": True, "description": "统一应用的改动"},
                        "updates": {"type": "array", "items": {"type": "object", "additionalProperties": True}, "description": "逐条更新：[{id, patch}]"},
                        "use_suggestions": {"type": "boolean", "default": False, "description": "用系统建议补全再激活"},
                        "content": {"type": "string"},
                        "mem_type": {"type": "string", "enum": MEM_NOTE_TYPE_ENUM},
                        "memory_kind": {"type": "string", "enum": list(MEM_NOTE_MEMORY_KINDS)},
                        "trigger_text": {"type": "string"},
                        "trigger_keywords": {"type": "array", "items": {"type": "string"}},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "people": {"type": "array", "items": {"type": "string"}},
                        "places": {"type": "array", "items": {"type": "string"}},
                        "objects": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string", "enum": ["captured", "active", "paused", "archived"]},
                        "cooldown_hours": {"type": "integer", "minimum": 0, "maximum": 8760},
                        "review_note": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_delete_mem_note",
                "description": "彻底删掉一条便签。如果只是不想让它出现了，用 update 把 status 改成 archived 更好。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string", "description": "要删的便签 id"},
                        "id": {"type": "string", "description": "note_id 的别名"},
                        "noteId": {"type": "string", "description": "note_id 的别名"},
                    },
                    "required": ["note_id"],
                },
            },
        },
    ]


def _gateway_notebook_and_recall_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shenyu_recall_main_thread",
                "description": "查最近主线程对话。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "since": {"type": "string"},
                        "until": {"type": "string"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_list",
                "description": "看手边的事。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "status": {"type": "string", "default": "active"},
                        "tag": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_write",
                "description": "记一条手边的事。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "default": "note"},
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "metadata": {"type": "object"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shenyu_notebook_update",
                "description": "改一条手边的事。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "status": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "type": {"type": "string"},
                        "pinned": {"type": "boolean"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["id"],
                },
            },
        },
    ]


def _gateway_supabase_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "supabase_query",
                "description": "直接查 Supabase 表。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {"type": "string"},
                        "filters": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "operators": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "column": {"type": "string"},
                        "select": {"type": "string"},
                        "order": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                    "required": ["table"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "supabase_insert",
                "description": "往 Supabase 表里写一行。",
                "parameters": {
                    "type": "object",
                    "properties": {"table": {"type": "string"}, "data": {"type": "object", "additionalProperties": True}},
                    "required": ["table", "data"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "supabase_update",
                "description": "改 Supabase 表里的行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {"type": "string"},
                        "match": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "operators": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "column": {"type": "string"},
                        "data": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["table", "data"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "supabase_delete",
                "description": "删 Supabase 表里的行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {"type": "string"},
                        "match": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "operators": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "column": {"type": "string"},
                        "hard": {"type": "boolean", "default": False},
                    },
                    "required": ["table"],
                },
            },
        },
    ]
