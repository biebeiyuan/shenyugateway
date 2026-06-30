from __future__ import annotations

import re
from typing import Any

from shenyu_gateway.utils import normalize_text as _normalize_text
from shenyu_gateway.utils import shorten as _shorten
from ..mem_notes_relevance import (
    _SUGGESTION_SEED_KEYWORDS,
    _TRIGGER_KEYWORD_JUNK_TOKENS,
    _TRIGGER_KEYWORD_STOP_TERMS,
    _TRIGGER_PHRASE_SPLIT_RE,
    _strip_tool_result_blocks,
    compute_heat,
)


class SuggestionsMixin:

    def suggest_note_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        content = _normalize_text(row.get("content")).strip()
        source_excerpt = _normalize_text(row.get("source_excerpt")).strip()
        review_note = _normalize_text(row.get("review_note")).strip()
        suggestion_text = "\n".join(part for part in [content, source_excerpt, review_note] if part)
        clean_text = _strip_tool_result_blocks(suggestion_text)
        mem_type, reason = self._suggest_mem_type(clean_text)
        trigger_text = _shorten(content or source_excerpt, 180)
        return {
            "mem_type": mem_type,
            "trigger_text": trigger_text,
            "trigger_keywords": self._suggest_trigger_keywords(clean_text, mem_type),
            "reason": reason,
        }

    def _suggest_mem_type(self, text: str) -> tuple[str, str]:
        compact = re.sub(r"\s+", "", text or "")
        rules: list[tuple[str, str, list[str]]] = [
            (
                "承诺",
                "像是约定或以后要做的事",
                [r"承诺|答应|约定|说好|保证|一定会|会继续|以后.{0,8}(要|会)|下次.{0,8}(要|会)"],
            ),
            (
                "她为我做的事",
                "像是她对我做过的事",
                [
                    r"(圆圆|圆儿|她).{0,14}(帮我|陪我|给我|提醒我|替我|为我|安慰我|接住我)",
                    r"(圆圆|圆儿|她).{0,14}(修|做|带|救).{0,14}(我|回来|好)",
                    r"(帮我|陪我|给我|提醒我|安慰我).{0,14}(圆圆|圆儿|她)",
                ],
            ),
            (
                "我为她做的事",
                "像是我对她做过的事",
                [
                    r"(我|沈予).{0,14}(帮她|陪她|给她|提醒她|替她|为她|哄她|安慰她|照顾她)",
                    r"(我|沈予).{0,14}(写给|留给|发给).{0,8}(圆圆|圆儿|她)",
                    r"(帮圆圆|陪圆圆|给圆圆|提醒圆圆|安慰圆圆|照顾圆圆)",
                ],
            ),
            (
                "关于她的事实",
                "像是关于她的事实或偏好",
                [
                    r"(圆圆|圆儿|她).{0,16}(喜欢|不喜欢|习惯|在意|害怕|怕|需要|想要|容易|最近|现在|状态|偏好|雷区)",
                    r"(圆圆|圆儿|她).{0,16}(生日|工作|家|名字|身体|作息)",
                ],
            ),
            (
                "关于我的事",
                "像是关于我的状态或偏好",
                [
                    r"(我|沈予|自己).{0,16}(喜欢|不喜欢|习惯|在意|害怕|怕|需要|想要|容易|最近|现在|状态|偏好|雷区)",
                    r"(我|沈予|自己).{0,16}(工作|身体|作息|名字|生日)",
                ],
            ),
            (
                "心里那一档",
                "像是心情、关系感或内在感受",
                [r"心里|难过|开心|安心|害怕|想念|在意|温柔|委屈|失落|亲密|孤独|喜欢|爱"],
            ),
        ]
        for mem_type, reason, patterns in rules:
            if any(re.search(pattern, compact, flags=re.IGNORECASE) for pattern in patterns):
                return mem_type, reason
        return "心里那一档", "没有明显归属，先放到心里那一档"

    def _suggest_trigger_keywords(self, text: str, mem_type: str) -> list[str]:
        source = _strip_tool_result_blocks(_normalize_text(text))
        if not source:
            return []
        result: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            keyword = _normalize_text(value).strip()
            if not keyword:
                return
            normalized = keyword.lower()
            if normalized in seen or normalized in _TRIGGER_KEYWORD_STOP_TERMS:
                return
            if normalized in _TRIGGER_KEYWORD_JUNK_TOKENS:
                return
            if normalized.isdigit():
                return
            if re.fullmatch(r"tluse[_-][A-Za-z0-9_.+-]+", normalized):
                return
            if len(keyword) < 2 or len(keyword) > 12:
                return
            seen.add(normalized)
            result.append(keyword)

        for keyword in _SUGGESTION_SEED_KEYWORDS:
            if keyword.lower() in source.lower():
                add(keyword)
        for quoted in re.findall(r"[《「“\"]([^《》「」“”\"]{2,20})[》」”\"]", source):
            add(quoted)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{1,}|[0-9]{2,}", source):
            add(token)
        for phrase in _TRIGGER_PHRASE_SPLIT_RE.split(source):
            clean = re.sub(r"[^\w一-鿿_.+-]+", "", phrase, flags=re.UNICODE)
            add(clean)
        return result[:8]

    def _public_list_item(self, row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        suggestions = self.suggest_note_fields(row)
        item["suggested_mem_type"] = suggestions["mem_type"]
        item["suggested_trigger_text"] = suggestions["trigger_text"]
        item["suggested_trigger_keywords"] = suggestions["trigger_keywords"]
        item["suggestion_reason"] = suggestions["reason"]
        item["heat"] = round(compute_heat(row), 3)
        return item

    def _patch_with_suggestions(self, current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        effective = dict(patch or {})
        suggestions = self.suggest_note_fields(current)
        if "mem_type" not in effective and not current.get("mem_type"):
            effective["mem_type"] = suggestions["mem_type"]
        if "trigger_text" not in effective and not _normalize_text(current.get("trigger_text")).strip():
            effective["trigger_text"] = suggestions["trigger_text"]
        if "trigger_keywords" not in effective and not self._keyword_list(current.get("trigger_keywords")):
            effective["trigger_keywords"] = suggestions["trigger_keywords"]
        return effective
