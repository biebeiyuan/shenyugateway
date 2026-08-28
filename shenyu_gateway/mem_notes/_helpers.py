from __future__ import annotations

import re
from typing import Any

from shenyu_gateway.utils import normalize_text as _normalize_text

MEM_NOTE_TYPES = ("她为我做的事", "我为她做的事", "关于她的事实", "关于我的事", "心里那一档", "承诺")
MEM_NOTE_STATUSES = ("captured", "active", "paused", "archived")
MEM_NOTE_MEMORY_KINDS = (
    "event", "person_fact", "social", "trip", "object", "preference",
    "routine", "promise", "running_joke", "thread",
)
MEM_NOTE_MEMORY_KIND_ALIASES: dict[str, str] = {
    # 中文 → English
    "事件": "event", "活动": "event",
    "人": "person_fact", "人物": "person_fact", "事实": "person_fact",
    "社交": "social", "聚会": "social",
    "旅行": "trip", "出行": "trip", "travel": "trip",
    "物品": "object", "东西": "object", "item": "object", "thing": "object",
    "偏好": "preference", "喜好": "preference", "pref": "preference",
    "习惯": "routine", "作息": "routine", "habit": "routine",
    "承诺": "promise", "约定": "promise",
    "梗": "running_joke", "笑话": "running_joke", "joke": "running_joke",
    "话题": "thread", "讨论": "thread", "conversation": "thread",
    # English aliases / typos
    "fact": "person_fact", "person": "person_fact", "personal_fact": "person_fact",
    "travel": "trip", "journey": "trip",
    "item": "object", "thing": "object",
    "pref": "preference", "like": "preference",
    "habit": "routine", "pattern": "routine",
    "joke": "running_joke", "meme": "running_joke",
    "topic": "thread", "conversation": "thread", "chat": "thread",
}
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
MEM_NOTE_PATCH_FIELDS = {
    "content",
    "mem_type",
    "trigger_text",
    "trigger_keywords",
    "entities",
    "status",
    "cooldown_hours",
    "review_note",
    # v2 structured fields
    "summary",
    "memory_kind",
    "people",
    "places",
    "objects",
    "keywords",
    "event_time",
    "importance",
    "mention_count",
    "promotion_score",
    "decay_after",
    # 日期提醒
    "remind_on",
    "reminded_at",
    # promise
    "promise_text",
    "trigger_scenarios",
    "due_hint",
    "resolved",
    "resolved_at",
    "next_action",
    "privacy_level",
    # running_joke
    "joke_text",
    "scene_tags",
    "last_used_at",
    # routine
    "routine_domain",
    "pattern",
    "phase",
    "constraints",
    "last_confirmed_at",
    # thread
    "topic",
    "last_position",
    "open_questions",
    "next_prompt",
    "thread_resolved",
}
MEM_NOTE_BULK_UPDATE_MAX = 200


def _normalize_note_id(value: Any) -> str:
    raw = _normalize_text(value).strip()
    match = _UUID_RE.search(raw)
    return match.group(0) if match else raw


_MEM_NOTE_SELECT_FIELDS = (
    "id,session_tag,content,mem_type,trigger_text,trigger_keywords,entities,status,"
    "cooldown_hours,last_triggered_at,trigger_count,source_model,source_session_id,"
    "source_excerpt,review_note,reviewed_at,created_at,updated_at,"
    "summary,memory_kind,people,places,objects,keywords,event_time,"
    "importance,confidence,mention_count,promotion_score,decay_after,"
    "remind_on,reminded_at,"
    "promise_text,trigger_scenarios,due_hint,resolved,resolved_at,next_action,privacy_level,"
    "joke_text,scene_tags,last_used_at,"
    "routine_domain,pattern,phase,constraints,last_confirmed_at,"
    "topic,last_position,open_questions,next_prompt,thread_resolved"
)

_MEM_NOTE_SELECT_FIELDS_LIGHT = (
    "id,session_tag,content,mem_type,trigger_text,trigger_keywords,entities,status,"
    "cooldown_hours,last_triggered_at,trigger_count,source_model,created_at,updated_at,"
    "summary,memory_kind,people,places,objects,keywords,event_time,"
    "importance,mention_count,promotion_score,remind_on,reminded_at,"
    "promise_text,resolved,joke_text,scene_tags,last_used_at,"
    "routine_domain,pattern,topic,thread_resolved"
)
