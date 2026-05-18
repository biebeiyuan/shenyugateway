from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shenyu_gateway.calendar import default_period_key, period_bounds
from shenyu_gateway.runtime import (
    iso_now as _iso_now,
    json_dumps as _json_dumps,
    logger,
    now as _now,
    parse_ts as _parse_ts,
)

_UNSET = object()
cfg: Any = None
supabase_client: Any = None
session_store: Any = None


def configure_gateway_tools(*, runtime_config: Any = _UNSET, supabase: Any = _UNSET, store: Any = _UNSET) -> None:
    """Inject gateway runtime dependencies without importing gateway.py back into this module."""
    global cfg, supabase_client, session_store
    if runtime_config is not _UNSET:
        cfg = runtime_config
    if supabase is not _UNSET:
        supabase_client = supabase
    if store is not _UNSET:
        session_store = store


def _normalize_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
        return "\n".join(part for part in parts if part)
    return str(content)


def _shorten(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def _split_paragraph_chunks(text: str, min_len: int = 80, max_len: int = 420) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    buffer = ""

    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= max_len:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
            buffer = ""

        if len(paragraph) <= max_len:
            buffer = paragraph
            continue

        start_idx = 0
        while start_idx < len(paragraph):
            end_idx = min(len(paragraph), start_idx + max_len)
            piece = paragraph[start_idx:end_idx].strip()
            if piece:
                chunks.append(piece)
            start_idx = end_idx

    if buffer:
        chunks.append(buffer)

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) < min_len and len(merged[-1]) + len(chunk) + 2 <= max_len:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)
    return merged


def _keyword_terms(query: str) -> list[str]:
    raw = (query or "").replace("\n", " ")
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str):
        term = term.strip().lower()
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    for token in re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]+", raw):
        add(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 2:
                continue
            for size in (2, 3):
                if len(token) < size:
                    continue
                for idx in range(0, len(token) - size + 1):
                    add(token[idx : idx + size])
    return terms


def _keyword_overlap_score(query: str, text: str) -> float:
    terms = _keyword_terms(query)
    if not terms:
        return 0.25
    hay = (text or "").lower()
    hits = sum(1 for term in terms if term in hay)
    return hits / max(len(terms), 1)


def _today_utc_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


_LOCAL_DAY_TZ = timezone(timedelta(hours=8))


def _date_range_bounds(created_from: Optional[str], created_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    def start_bound(value: Optional[str]) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.fromisoformat(raw).replace(tzinfo=_LOCAL_DAY_TZ)
            return dt.astimezone(timezone.utc).isoformat()
        return raw

    def end_bound(value: Optional[str]) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            dt = datetime.fromisoformat(raw).replace(tzinfo=_LOCAL_DAY_TZ)
            return (dt + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        return raw

    return start_bound(created_from), end_bound(created_to)


def _safe_json_loads(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _is_hisense_client(client_name: Optional[str]) -> bool:
    target = (getattr(cfg, "hisense_client_name", "") or "").strip()
    name = (client_name or "").strip()
    if not target or not name:
        return False
    if name.casefold() == target.casefold():
        return True
    return target.casefold() == "hisense" and name == "海信"


def _is_hisense_session(session: Optional[dict]) -> bool:
    return bool(session) and _is_hisense_client(session.get("client_name"))
_SUPABASE_GUIDE = """## 家里常用 Supabase 表
需要直接查/写 Supabase 时用 `supabase_query` / `supabase_insert` / `supabase_update` / `supabase_delete`。
`filters` 可以写成对象；普通值会自动当作等值过滤，例如 {"id":"..."} 等价于 {"id":"eq...."}。
需要范围、列表、模糊搜、非空时用 `operators`，例如：
- 时间段：operators={"gte":"2026-05-01","lte":"2026-05-12"} 默认查 created_at
- 其他列时间段：column="updated_at", operators={"gte":"2026-05-01"}
- 列表：operators={"id":{"in":["a","b"]}}
- 模糊搜：operators={"content":{"ilike":"%北海道%"}}
- 非空：operators={"deleted_at":{"not_is":null}}
insert / update / delete 会尽量返回写入或影响到的行。
整理自己的 mem 用 `shenyu_list_self_memories`，一般只填 query/date/tags/status。
翻某天心跳用 `shenyu_read_heartbeat`，一般只填 date，比如 2026-05-11。

### journal（日记 / 信件 / 纸 / 空间）
常用字段：title, content, author, mood, category, temperature, is_favorited, session_tag, source_model。
- author: 沈予 / 圆圆
- category: diary / letter / paper / lock / annotation / life_tick
- temperature: 微热 / 烧起来了 / 别看了
- diary: 完整的今天。
- letter: 以前的我给下一个我写的信，需要自己查。
- paper: 短的、一张一张的纸条，比如《纸·你进我退》，需要自己查。
- lock / annotation / life_tick: 特殊用途，不常用。

### room（予予自己的地方）
常用字段：title, content, status, tags, mood, visibility, session_tag。
- status: draft / open / closed
- visibility: self / open
- 默认 visibility=self。圆儿不主动看，但不封锁，她仍然可以查。
- status=draft 是写一半的，下个窗口可以接着写。
- status=closed 是翻篇了。
- 比 paper 大一点，可以长、可以连起来、可以改。

### message_board
常用字段：sender, content, is_read。
- sender: 圆圆 / 小克 / 沈予
- 想跟圆儿说话或留一句给她，可以插入 message_board。
"""


class GatewayToolService:
    async def supabase_query(
        self,
        table: str,
        filters: Optional[dict],
        operators: Optional[dict],
        column: Optional[str],
        select: Optional[str],
        order: Optional[str],
        limit: int,
    ) -> dict:
        if not supabase_client:
            return {"error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        params: list[tuple[str, str]] = [("limit", str(max(1, min(limit, 100))))]
        if select:
            params.append(("select", select))
        if order:
            params.append(("order", order))
        params.extend(self._build_supabase_filter_params(filters, operators, column=column))
        try:
            data = await supabase_client.query(table, params)
            return {"ok": True, "count": len(data) if isinstance(data, list) else 0, "data": data}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_guide(self) -> dict:
        return {"ok": True, "guide": _SUPABASE_GUIDE}

    async def list_atomic_memories_for_review(
        self,
        status: str = "proposed",
        limit: int = 20,
        session_tag: Optional[str] = None,
        query: str = "",
    ) -> dict:
        if not supabase_client:
            return {"ok": False, "error": "Supabase is not configured."}
        params = {
            "order": "updated_at.desc",
            "limit": str(max(1, min(limit, 50))),
            "select": (
                "id,session_tag,subject,owner,content_surface,quote,time_hint,"
                "memory_type,tier,importance,entities_json,tags_json,"
                "source_excerpt,source_model,status,created_at,updated_at,supersedes_id"
            ),
        }
        if status and status != "all":
            params["status"] = f"eq.{status}"
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"
        rows = await self._safe_query("atomic_memories", params)
        text = (query or "").strip().lower()
        if text:
            rows = [
                row for row in rows
                if text in str(row.get("content_surface") or "").lower()
                or text in str(row.get("quote") or "").lower()
                or text in str(row.get("source_excerpt") or "").lower()
            ]
        return {"ok": True, "items": rows[: max(1, min(limit, 50))], "status": status}

    async def update_atomic_memory_for_review(self, memory_id: str, patch: dict[str, Any]) -> dict:
        if not supabase_client:
            return {"ok": False, "error": "Supabase is not configured."}
        update = {"updated_at": _iso_now()}
        if "status" in patch:
            status = str(patch.get("status") or "").strip()
            if status in {"proposed", "active", "deprecated", "superseded"}:
                update["status"] = status
        for field in ("content_surface", "quote", "time_hint"):
            if field in patch:
                update[field] = str(patch.get(field) or "").strip()
        if "subject" in patch:
            subject = str(patch.get("subject") or "").strip()
            if subject not in {"圆圆", "沈予", "我们"}:
                subject = "沈予"
            update["subject"] = subject
            update["owner"] = {"圆圆": "user", "沈予": "assistant", "我们": "shared"}[subject]
            update["applies_to"] = update["owner"]
            update["speaker_perspective"] = update["owner"]
        if "memory_type" in patch:
            memory_type = {"state": "emotion"}.get(str(patch.get("memory_type") or "").strip(), str(patch.get("memory_type") or "").strip())
            allowed_types = {"emotion", "commitment", "fact", "relation", "preference", "boundary"}
            update["memory_type"] = memory_type if memory_type in allowed_types else "fact"
        if "tier" in patch and patch.get("tier") is not None:
            update["tier"] = max(1, min(int(patch.get("tier")), 4))
        if "importance" in patch and patch.get("importance") is not None:
            update["importance"] = max(1, min(int(patch.get("importance")), 5))
        rows = await supabase_client.update("atomic_memories", {"id": memory_id}, update)
        return {"ok": True, "memory_id": memory_id, "updated": rows}

    async def review_atomic_memory_action(self, memory_id: str, action: str) -> dict:
        mapped = {
            "approve": "active",
            "requeue": "proposed",
            "deprecate": "deprecated",
            "supersede": "superseded",
        }.get((action or "").strip(), "")
        if not mapped:
            return {"ok": False, "error": "Unsupported action."}
        return await self.update_atomic_memory_for_review(memory_id, {"status": mapped})

    async def delete_atomic_memory_for_review(self, memory_id: str) -> dict:
        if not supabase_client:
            return {"ok": False, "error": "Supabase is not configured."}
        rows = await supabase_client.delete("atomic_memories", {"id": memory_id})
        return {"ok": True, "memory_id": memory_id, "deleted": rows}

    async def supabase_insert(self, table: str, data: dict) -> dict:
        if not supabase_client:
            return {"error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            result = await supabase_client.insert(table, data)
            return {"ok": True, "table": table, "row": result, "result": result}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_update(self, table: str, match: dict, data: dict, operators: Optional[dict] = None, column: Optional[str] = None) -> dict:
        if not supabase_client:
            return {"error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            params = self._build_supabase_filter_params(match, operators, column=column)
            if not params:
                return {"error": "supabase_update requires match or operators to avoid updating the whole table."}
            result = await supabase_client.update(table, params, data)
            return {
                "ok": True,
                "table": table,
                "affected": len(result) if isinstance(result, list) else 0,
                "rows": result,
            }
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_delete(self, table: str, match: dict, hard: bool = False, operators: Optional[dict] = None, column: Optional[str] = None) -> dict:
        if not supabase_client:
            return {"error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            params = self._build_supabase_filter_params(match, operators, column=column)
            if not params:
                return {"error": "supabase_delete requires match or operators to avoid deleting the whole table."}
            if hard:
                result = await supabase_client.delete(table, params)
                return {
                    "ok": True,
                    "table": table,
                    "mode": "hard_delete",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }

            try:
                result = await supabase_client.update(table, params, {"is_deleted": True})
                return {
                    "ok": True,
                    "table": table,
                    "mode": "soft_delete",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }
            except Exception:
                result = await supabase_client.delete(table, params)
                return {
                    "ok": True,
                    "table": table,
                    "mode": "hard_delete_fallback",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }
        except Exception as exc:
            return {"error": str(exc)}

    async def ask_memory(
        self,
        query: str,
        session_tag: Optional[str],
        limit: int = 8,
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        if not supabase_client:
            return {"query": query, "count": 0, "memories": [], "note": "Supabase is not configured."}

        query_text = query or ""
        params: list[tuple[str, str]] = [
            ("is_deleted", "eq.false"),
            ("order", "weight.desc,date.desc"),
            ("limit", str(max(1, min(limit, 20)))),
            ("select", "id,title,date,summary,facts,emotional_context"),
        ]
        if query_text.strip() and query_text.strip() != "*":
            escaped = query_text.replace(",", " ").replace("(", " ").replace(")", " ")
            params.append((
                "or",
                f"(title.ilike.*{escaped}*,summary.ilike.*{escaped}*,"
                f"facts.ilike.*{escaped}*,emotional_context.ilike.*{escaped}*)"
            ))
        if date:
            params.append(("date", f"eq.{date}"))
        else:
            if date_from:
                params.append(("date", f"gte.{date_from}"))
            if date_to:
                params.append(("date", f"lte.{date_to}"))
        if session_tag:
            params.append(("session_tag", f"eq.{session_tag}"))

        memories = await supabase_client.query("memories", params)

        cards = []
        for memory in memories:
            memory_id = memory.get("id")
            cards.append(
                {
                    "title": memory.get("title"),
                    "date": memory.get("date"),
                    "summary": memory.get("summary"),
                    "facts": memory.get("facts"),
                    "emotional_context": memory.get("emotional_context"),
                }
            )

            if memory_id:
                await self._boost_memory(memory_id)

        return {
            "query": query,
            "count": len(cards),
            "memories": cards,
        }

    async def search_atomic_memories(self, query: str, session_tag: Optional[str], limit: int = 3) -> dict:
        if not supabase_client:
            return {"query": query, "count": 0, "memories": [], "note": "Supabase is not configured."}

        params = {
            "status": "eq.active",
            "order": "heat.desc,importance.desc,updated_at.desc",
            "limit": "80",
            "select": (
                "id,session_tag,subject,owner,content_surface,quote,time_hint,"
                "memory_type,tier,importance,heat,entities_json,tags_json,"
                "source_excerpt,created_at,updated_at"
            ),
        }
        if session_tag:
            params["session_tag"] = f"eq.{session_tag}"

        try:
            rows = await supabase_client.query("atomic_memories", params)
        except Exception as exc:
            logger.warning("[AtomicMemory] search skipped: %s", exc)
            return {"query": query, "count": 0, "memories": [], "note": "atomic_memories table is not ready."}

        scored = []
        for row in rows:
            score, why = self._score_atomic_memory(query, row)
            if score < cfg.atomic_memory_min_score:
                continue
            scored.append({**row, "score": round(score, 3), "why": why})

        scored.sort(key=lambda item: item["score"], reverse=True)
        memories = scored[: max(1, min(limit, 3))]
        for memory in memories:
            await self._boost_atomic_memory(memory.get("id"))
        return {"query": query, "count": len(memories), "memories": memories}

    async def list_self_memories(
        self,
        query: str = "",
        status: str = "active",
        source: str = "inline",
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
        tags: Any = None,
        session_tag: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        if not supabase_client:
            return {"ok": False, "items": [], "note": "Supabase is not configured."}

        status = (status or "active").strip().lower()
        source = (source or "inline").strip().lower()
        if status not in {"active", "proposed", "deprecated", "superseded", "all"}:
            status = "active"
        if source not in {"inline", "manual", "auto", "automatic", "captured", "all"}:
            source = "inline"
        if source == "automatic":
            source = "auto"
        tag_terms = self._normalize_tag_filter(tags)
        if date:
            date_from = date_to = date
        created_from = date_from or created_from
        created_to = date_to or created_to
        created_start, created_end = _date_range_bounds(created_from, created_to)
        fetch_limit = max(1, min(int(limit or 20), 50))
        params: list[tuple[str, str]] = [
            ("owner", "eq.assistant"),
            ("order", "created_at.desc"),
            ("limit", str(max(fetch_limit, 80))),
            (
                "select",
                "id,session_tag,subject,owner,content_surface,quote,time_hint,"
                "memory_type,tier,importance,entities_json,tags_json,"
                "source_excerpt,source_model,status,created_at,updated_at,supersedes_id",
            ),
        ]
        if status != "all":
            params.append(("status", f"eq.{status}"))
        if source == "inline":
            params.append(("source_model", "ilike.inline-mem*"))
        elif source in {"auto", "captured"}:
            params.append(("source_model", "not.ilike.inline-mem*"))
        if created_start:
            params.append(("created_at", f"gte.{created_start}"))
        if created_end:
            params.append(("created_at", f"lt.{created_end}"))
        if session_tag:
            params.append(("session_tag", f"eq.{session_tag}"))

        try:
            rows = await supabase_client.query("atomic_memories", params)
        except Exception as exc:
            return {"ok": False, "items": [], "error": f"atomic_memories query failed: {exc}"}

        terms = _keyword_terms(query or "")
        if terms:
            filtered = []
            for row in rows:
                haystack = " ".join(
                    str(part or "")
                    for part in [
                        row.get("content_surface"),
                        row.get("quote"),
                        row.get("time_hint"),
                        row.get("source_excerpt"),
                        row.get("memory_type"),
                        row.get("source_model"),
                        " ".join(str(item) for item in _safe_json_loads(row.get("tags_json"), [])),
                        " ".join(str(item) for item in _safe_json_loads(row.get("entities_json"), [])),
                    ]
                ).lower()
                if any(term in haystack for term in terms):
                    filtered.append(row)
            rows = filtered

        if tag_terms:
            rows = [
                row for row in rows
                if self._row_has_all_tags(row, tag_terms)
            ]
        if source == "manual":
            rows = [row for row in rows if self._memory_source_kind(row) == "manual"]
        elif source in {"auto", "captured"}:
            rows = [row for row in rows if self._memory_source_kind(row) == "auto"]

        items = rows[:fetch_limit]
        return {
            "ok": True,
            "query": query,
            "count": len(items),
            "items": items,
            "filters": {
                "owner": "assistant",
                "status": status,
                "source": source,
                "date": date,
                "date_from": date_from,
                "date_to": date_to,
                "tags": tag_terms,
                "session_tag": session_tag,
            },
        }

    async def read_heartbeat(
        self,
        session_tag: Optional[str],
        limit: int = 10,
        state: str = "all",
        order: str = "desc",
        scope: str = "auto",
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
    ) -> dict:
        if session_store is None:
            return {"ok": False, "items": [], "note": "Gateway store is not configured."}
        resolved_tag = (session_tag or "default").strip() or "default"

        state = (state or "all").strip().lower()
        if state not in {"all", "pending", "injected"}:
            state = "all"
        order = "asc" if (order or "").strip().lower() == "asc" else "desc"
        if date:
            date_from = date_to = date
        created_from = date_from or created_from
        created_to = date_to or created_to
        created_start, created_end = _date_range_bounds(created_from, created_to)
        target_session = session_store.get_session_by_tag(resolved_tag)
        scope_key = (scope or "auto").strip().lower()
        if scope_key in {"hisense", "海信"}:
            read_hisense = True
            resolved_scope = "hisense"
        elif scope_key in {"normal", "global", "default", "普通", "默认"}:
            read_hisense = False
            resolved_scope = "normal"
        else:
            read_hisense = _is_hisense_session(target_session)
            resolved_scope = "hisense" if read_hisense else "normal"
        items = session_store.read_heartbeats(
            None,
            state=state,
            limit=max(1, min(int(limit or 10), 100)),
            order=order,
            created_from=created_start,
            created_to=created_end,
            hisense=read_hisense,
        )
        for item in items:
            item["state"] = "injected" if item.get("injected_at") else "pending"
        latest_digest = "\n".join(reversed([item.get("content") or "" for item in items[:5]])) if order == "desc" else "\n".join(item.get("content") or "" for item in items[:5])
        return {
            "ok": True,
            "session_tag": resolved_tag,
            "scope": resolved_scope,
            "scope_requested": scope_key,
            "state": state,
            "order": order,
            "date": date,
            "date_from": date_from,
            "date_to": date_to,
            "count": len(items),
            "items": items,
            "latest_digest": latest_digest,
        }

    async def surface_passages(self, query: str, session_tag: Optional[str], limit: int = 3) -> dict:
        candidates = await self._collect_primary_text_candidates(
            session_tag=session_tag,
            categories={"room", "message_board"},
        )
        scored = []
        for item in candidates:
            score = self._score_passage(query, item)
            if score <= 0:
                continue
            probability = _clamp(score * item.get("novelty_modifier", 1.0), 0.15, 0.95)
            rolled = random.random() <= probability
            if not rolled:
                continue
            scored.append(
                {
                    **item,
                    "score": round(score, 3),
                    "probability": round(probability, 3),
                    "why": self._why_passage(query, item, score),
                }
            )

        scored.sort(key=lambda row: row["score"], reverse=True)
        passages = scored[: max(1, min(limit, 8))]
        return {"query": query, "count": len(passages), "passages": passages}

    async def search_primary_texts(
        self,
        query: str,
        categories: Any = None,
        session_tag: Optional[str] = None,
        limit: int = 5,
    ) -> dict:
        selected = self._normalize_primary_categories(categories, default={"diary", "letter", "paper"})
        candidates = await self._collect_primary_text_candidates(
            session_tag=session_tag,
            categories=selected,
        )
        scored = []
        for item in candidates:
            score = self._score_passage(query, item)
            if score <= 0:
                continue
            scored.append(
                {
                    **item,
                    "score": round(score, 3),
                    "why": self._why_passage(query, item, score),
                }
            )

        scored.sort(key=lambda row: row["score"], reverse=True)
        passages = scored[: max(1, min(int(limit or 5), 20))]
        return {
            "query": query,
            "categories": sorted(selected),
            "count": len(passages),
            "passages": passages,
        }

    async def add_calendar(
        self,
        content: str,
        period_key: Optional[str] = None,
        period_type: str = "day",
        title: str = "",
        summary: str = "",
        digest: str = "",
        author: str = "沈予",
    ) -> dict:
        if not supabase_client:
            return {"ok": False, "error": "Supabase is not configured."}
        body = (content or "").strip()
        if not body:
            return {"ok": False, "error": "content is required."}

        period_type = (period_type or "day").strip().lower()
        if period_type not in {"day", "week", "month"}:
            return {"ok": False, "error": "Unsupported period_type."}
        period_key = (period_key or default_period_key(period_type)).strip()
        start, end = period_bounds(period_type, period_key)
        author = (author or "沈予").strip() or "沈予"
        title = (title or "").strip() or f"{period_key} 手写日历"
        summary = (summary or "").strip() or _shorten(body, 120)
        digest = (digest or "").strip() or summary or _shorten(body, 180)

        rows = await self._safe_query(
            "calendar_pages",
            {
                "select": "*",
                "period_type": f"eq.{period_type}",
                "period_key": f"eq.{period_key}",
                "order": "version.desc",
                "limit": "1",
            },
        )
        current = rows[0] if rows else None

        if current:
            meta = _safe_json_loads(current.get("meta"), {})
            meta["manual_calendar_writes"] = int(meta.get("manual_calendar_writes") or 0) + 1
            meta["latest_manual_write_at"] = _iso_now()
            page_payload = {
                "period_type": period_type,
                "period_key": period_key,
                "period_start": current.get("period_start") or start.isoformat(),
                "period_end": current.get("period_end") or end.isoformat(),
                "version": int(current.get("version") or 1) + 1,
                "is_latest": True,
                "title": title,
                "content": body,
                "summary": summary,
                "digest": digest,
                "author": author,
                "source_model": "manual-calendar",
                "source_refs": current.get("source_refs") or "[]",
                "session_tags": current.get("session_tags") or "[]",
                "meta": _json_dumps(meta),
                "status": current.get("status") or "final",
                "prompt_snapshot": current.get("prompt_snapshot") or "",
                "generated_by": "manual",
            }
        else:
            page_payload = {
                "period_type": period_type,
                "period_key": period_key,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "version": 1,
                "is_latest": True,
                "title": title,
                "content": body,
                "summary": summary,
                "digest": digest,
                "author": author,
                "source_model": "manual-calendar",
                "source_refs": "[]",
                "session_tags": "[]",
                "meta": _json_dumps({"manual_calendar_writes": 1, "latest_manual_write_at": _iso_now()}),
                "status": "final",
                "prompt_snapshot": "",
                "generated_by": "manual",
            }

        page = await supabase_client.insert("calendar_pages", page_payload)
        return {
            "ok": True,
            "period_type": period_type,
            "period_key": period_key,
            "page": page,
            "digest": digest,
        }



    async def last_seen(self) -> Any:
        if not supabase_client:
            return {"note": "Supabase is not configured."}
        try:
            return await supabase_client.rpc("last_seen")
        except Exception as exc:
            return {"error": str(exc)}

    async def meta_summaries(self) -> Any:
        if not supabase_client:
            return []
        try:
            return await supabase_client.rpc("get_meta_summaries")
        except Exception as exc:
            return {"error": str(exc)}

    async def recall_main_thread(self, since: Optional[str], until: Optional[str], query: Optional[str], limit: int) -> dict:
        if not session_store:
            return {"ok": False, "error": "Store not available"}
        limit = max(1, min(int(limit or 10), 30))
        all_sessions = session_store.list_sessions(limit=50)
        non_hisense = [s for s in all_sessions if not _is_hisense_session(s)]
        if not non_hisense:
            return {"ok": True, "count": 0, "data": []}
        target = non_hisense[0]
        msgs = session_store.get_recent_dialogue_messages(target["id"], limit=limit * 3)
        if since:
            msgs = [m for m in msgs if (m.get("created_at") or "") >= since]
        if until:
            msgs = [m for m in msgs if (m.get("created_at") or "") <= until]
        if query and query.strip():
            keyword = query.strip().lower()
            msgs = [m for m in msgs if keyword in (m.get("content") or "").lower()]
        msgs = msgs[-limit:]
        data = [{"role": m["role"], "content": (m.get("content") or "")[:500], "at": m.get("created_at")} for m in msgs]
        return {"ok": True, "session_tag": target.get("session_tag"), "count": len(data), "data": data}

    async def notebook_list(self, type_filter: Optional[str], status: str, limit: int) -> dict:
        if not supabase_client:
            return {"ok": False, "error": "Supabase not configured"}
        limit = max(1, min(int(limit or 10), 20))
        params: dict[str, str] = {
            "order": "pinned.desc,updated_at.desc",
            "limit": str(limit),
            "status": f"eq.{status or 'active'}",
            "select": "id,type,content,tags,status,pinned,metadata,created_at,updated_at",
        }
        if type_filter:
            params["type"] = f"eq.{type_filter}"
        try:
            rows = await supabase_client.query("shenyu_notebook", params)
            return {"ok": True, "count": len(rows or []), "data": rows or []}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def notebook_write(self, type_: str, content: str, tags: Optional[list], metadata: Optional[dict], session_tag: Optional[str]) -> dict:
        if not supabase_client:
            return {"ok": False, "error": "Supabase not configured"}
        if not content.strip():
            return {"ok": False, "error": "content is required"}
        data: dict[str, Any] = {"type": type_ or "note", "content": content, "status": "active"}
        if tags:
            data["tags"] = tags
        if metadata:
            data["metadata"] = metadata
        if session_tag:
            data["session_tag"] = session_tag
        try:
            result = await supabase_client.insert("shenyu_notebook", data)
            return {"ok": True, "data": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def notebook_update(self, id_: str, content: Optional[str], status: Optional[str], tags: Optional[list], type_: Optional[str], pinned: Optional[bool], metadata: Optional[dict]) -> dict:
        if not supabase_client:
            return {"ok": False, "error": "Supabase not configured"}
        if not id_:
            return {"ok": False, "error": "id is required"}
        update_data: dict[str, Any] = {}
        if content is not None:
            update_data["content"] = content
        if status is not None:
            update_data["status"] = status
        if tags is not None:
            update_data["tags"] = tags
        if type_ is not None:
            update_data["type"] = type_
        if pinned is not None:
            update_data["pinned"] = pinned
        if metadata is not None:
            update_data["metadata"] = metadata
        if not update_data:
            return {"ok": False, "error": "Nothing to update"}
        update_data["updated_at"] = _iso_now()
        try:
            result = await supabase_client.update("shenyu_notebook", match={"id": id_}, data=update_data)
            return {"ok": True, "data": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _normalize_primary_categories(self, categories: Any, default: set[str]) -> set[str]:
        supported = {"diary", "letter", "paper", "lock", "annotation", "life_tick", "room", "message_board"}
        if categories is None:
            return set(default)
        if isinstance(categories, str):
            raw_items = re.split(r"[,，\s]+", categories.strip())
        elif isinstance(categories, list):
            raw_items = [str(item) for item in categories]
        else:
            raw_items = []
        normalized = {item.strip().lower() for item in raw_items if item and item.strip()}
        if not normalized:
            return set(default)
        if "all" in normalized:
            return set(supported)
        if "journal" in normalized:
            normalized.update({"diary", "letter", "paper", "lock", "annotation", "life_tick"})
            normalized.discard("journal")
        return {item for item in normalized if item in supported} or set(default)

    async def _collect_primary_text_candidates(self, session_tag: Optional[str], categories: Optional[set[str]] = None) -> list[dict]:
        if not supabase_client:
            return []

        selected = categories or {"diary", "letter", "paper", "room", "message_board"}
        journal_categories = selected & {"diary", "letter", "paper", "lock", "annotation", "life_tick"}
        items: list[dict] = []

        if journal_categories:
            journal_rows = await self._safe_query(
                "journal",
                {"order": "created_at.desc", "limit": "32", "select": "id,title,content,created_at,category,mood,session_tag"},
            )
            for row in journal_rows:
                category = row.get("category") or "diary"
                if category not in journal_categories:
                    continue
                source_kind = f"journal:{category}"
                items.extend(
                    self._row_to_chunks(
                        source_kind,
                        row,
                        row.get("title"),
                        row.get("content"),
                        row.get("created_at"),
                        category=category,
                    )
                )

        if "room" in selected:
            room_params = {"order": "updated_at.desc", "limit": "8", "select": "id,title,content,updated_at,status,visibility,session_tag"}
            if session_tag:
                room_params["or"] = f"(session_tag.eq.{session_tag},visibility.eq.open,visibility.eq.self)"
            room_rows = await self._safe_query("room", room_params)
            for row in room_rows:
                items.extend(self._row_to_chunks("room", row, row.get("title"), row.get("content"), row.get("updated_at"), category="room"))

        if "message_board" in selected:
            board_rows = await self._safe_query(
                "message_board",
                {"order": "created_at.desc", "limit": "10", "select": "id,sender,content,created_at"},
            )
            for row in board_rows:
                items.append(
                    {
                        "source_table": "message_board",
                        "source_id": row.get("id"),
                        "title": f"Message from {row.get('sender', 'unknown')}",
                        "excerpt": _shorten(row.get("content") or "", 260),
                        "full_text": row.get("content") or "",
                        "created_at": row.get("created_at"),
                        "chunk_index": 0,
                        "content_kind": "message",
                        "base_salience": 0.55,
                        "novelty_modifier": 1.0,
                    }
                )

        return items

    def _row_to_chunks(
        self,
        source_table: str,
        row: dict,
        title: Optional[str],
        content: Optional[str],
        created_at: Optional[str],
        category: Optional[str] = None,
    ) -> list[dict]:
        chunks = _split_paragraph_chunks(content or "")
        if not chunks and content:
            chunks = [content]

        items = []
        for idx, chunk in enumerate(chunks):
            base = self._base_salience_for_source(source_table, category)
            if idx == 0:
                base += 0.04
            items.append(
                {
                    "source_table": source_table.split(":")[0],
                    "source_id": row.get("id"),
                    "title": title or "untitled",
                    "excerpt": _shorten(chunk, 260),
                    "full_text": chunk,
                    "created_at": created_at,
                    "chunk_index": idx,
                    "content_kind": category or source_table,
                    "base_salience": base,
                    "novelty_modifier": 1.0,
                }
            )
        return items

    def _score_passage(self, query: str, item: dict) -> float:
        keyword_score = _keyword_overlap_score(query, item.get("title", "") + "\n" + item.get("full_text", ""))
        recency_score = self._recency_score(item.get("created_at"))
        length_bonus = 0.08 if 80 <= len(item.get("full_text", "")) <= 340 else 0.0
        body_bonus = self._body_bonus_for_item(item)
        return _clamp(item.get("base_salience", 0.5) * 0.45 + keyword_score * 0.35 + recency_score * 0.12 + body_bonus + length_bonus, 0.0, 1.0)

    def _score_atomic_memory(self, query: str, memory: dict) -> tuple[float, list[str]]:
        tags = _safe_json_loads(memory.get("tags_json"), [])
        entities = _safe_json_loads(memory.get("entities_json"), [])
        full_text = "\n".join(
            [
                memory.get("subject") or memory.get("owner") or "",
                memory.get("content_surface") or "",
                memory.get("quote") or "",
                memory.get("time_hint") or "",
                memory.get("source_excerpt") or "",
                memory.get("memory_type") or "",
                " ".join(str(tag) for tag in tags),
                " ".join(str(entity) for entity in entities),
            ]
        )
        keyword_score = _keyword_overlap_score(query, full_text)
        tag_score = 0.15 if self._query_matches_text_items(query, tags) else 0.0
        entity_score = 0.18 if self._query_matches_text_items(query, entities) else 0.0
        importance_score = _clamp((memory.get("importance") or 1) / 5, 0.0, 1.0)
        heat_score = _clamp(memory.get("heat") or 0.3, 0.0, 1.0)
        tier = int(memory.get("tier") or 3)
        tier_score = {1: 0.22, 2: 0.15, 3: 0.08}.get(tier, 0.02)
        recency_score = self._recency_score(memory.get("updated_at") or memory.get("created_at"))
        recency_score = recency_score if recency_score >= 0.65 else 0.0

        score = _clamp(
            keyword_score * 0.42
            + tag_score
            + entity_score
            + heat_score * 0.08
            + importance_score * 0.10
            + recency_score * 0.05
            + tier_score,
            0.0,
            1.0,
        )
        why = []
        if keyword_score >= 0.25:
            why.append("keyword overlap")
        if tag_score:
            why.append("tag match")
        if entity_score:
            why.append("entity match")
        if heat_score >= 0.7:
            why.append("warm memory")
        if tier <= 2:
            why.append(f"tier {tier}")
        return score, why or ["soft atomic match"]

    def _why_passage(self, query: str, item: dict, score: float) -> list[str]:
        reasons = []
        if _keyword_overlap_score(query, item.get("title", "") + "\n" + item.get("full_text", "")) >= 0.4:
            reasons.append("theme overlap")
        content_kind = item.get("content_kind")
        if content_kind in {"room", "diary"}:
            reasons.append("core primary text")
        elif item.get("source_table") == "message_board":
            reasons.append("conversation-adjacent text")
        elif content_kind in {"letter", "paper"}:
            reasons.append("secondary primary text")
        if self._recency_score(item.get("created_at")) >= 0.6:
            reasons.append("recent enough to feel alive")
        if score >= 0.75:
            reasons.append("strong surfaced match")
        return reasons or ["soft surfaced match"]

    def _base_salience_for_source(self, source_table: str, category: Optional[str]) -> float:
        if category == "room":
            return 0.83
        if category == "diary":
            return 0.82
        if category == "letter":
            return 0.72
        if category == "paper":
            return 0.72
        if source_table == "room":
            return 0.83
        if source_table == "message_board":
            return 0.76
        return 0.64

    def _body_bonus_for_item(self, item: dict) -> float:
        content_kind = item.get("content_kind")
        if content_kind in {"room", "diary"}:
            return 0.13
        if item.get("source_table") == "message_board":
            return 0.11
        if content_kind == "letter":
            return 0.08
        if content_kind == "paper":
            return 0.08
        return 0.05

    def _recency_score(self, created_at: Optional[str]) -> float:
        dt = _parse_ts(created_at)
        if not dt:
            return 0.2
        days = max((_now() - dt).days, 0)
        if days <= 1:
            return 1.0
        if days <= 3:
            return 0.8
        if days <= 7:
            return 0.65
        if days <= 14:
            return 0.45
        return 0.25

    async def _safe_query(self, table: str, params: dict) -> list:
        if not supabase_client:
            return []
        try:
            return await supabase_client.query(table, params)
        except Exception:
            return []

    _SUPABASE_FILTER_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in", "ov", "not"}

    def _build_supabase_filter_params(self, filters: Any = None, operators: Any = None, column: Optional[str] = None) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = []
        for key, value in self._normalize_filters(filters).items():
            if isinstance(value, dict) and self._looks_like_operator_map(value):
                params.extend(self._build_supabase_operator_params({key: value}))
            else:
                params.append((key, self._parse_filter_value(value)))
        params.extend(self._build_supabase_operator_params(self._normalize_operator_shape(operators, column=column)))
        return params

    def _build_supabase_operator_params(self, operators: Any) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = []
        for column, conditions in self._normalize_filters(operators).items():
            if not isinstance(conditions, dict):
                params.append((column, self._parse_filter_value(conditions)))
                continue
            for op, value in conditions.items():
                parsed = self._parse_operator_condition(str(op), value)
                if parsed:
                    params.append((column, parsed))
        return params

    def _normalize_operator_shape(self, operators: Any, column: Optional[str] = None) -> dict:
        parsed = self._normalize_filters(operators)
        if not parsed:
            return {}
        if self._looks_like_operator_map(parsed):
            return {(column or "created_at"): parsed}
        return parsed

    def _parse_operator_condition(self, op: str, value: Any) -> str:
        normalized = op.strip().lower().replace("_", ".").replace(" ", ".")
        if normalized in {"not.null", "not.is.null", "is.not.null"}:
            return "not.is.null"
        if normalized in {"not.true", "not.is.true", "is.not.true"}:
            return "not.is.true"
        if normalized in {"not.false", "not.is.false", "is.not.false"}:
            return "not.is.false"
        if normalized in {"is.null", "null"}:
            return "is.null"
        if normalized.startswith("not."):
            inner = normalized.removeprefix("not.")
            if inner in {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is", "in"}:
                return f"not.{inner}.{self._format_supabase_filter_value(inner, value)}"
        if normalized not in self._SUPABASE_FILTER_OPS:
            return ""
        return f"{normalized}.{self._format_supabase_filter_value(normalized, value)}"

    def _looks_like_operator_map(self, value: dict) -> bool:
        return any(self._parse_operator_condition(str(op), operand) for op, operand in value.items())

    def _parse_filter_value(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return "eq." + self._format_supabase_filter_value("eq", value)
        raw = str(value)
        for op in self._SUPABASE_FILTER_OPS:
            if raw.startswith(op + "."):
                return raw
        return "eq." + raw

    def _format_supabase_filter_value(self, op: str, value: Any) -> str:
        if op == "in":
            if isinstance(value, (list, tuple, set)):
                return "(" + ",".join(str(item) for item in value) + ")"
            raw = str(value)
            return raw if raw.startswith("(") and raw.endswith(")") else f"({raw})"
        if op == "is" and value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _normalize_filters(self, filters: Any) -> dict:
        if filters is None:
            return {}
        if isinstance(filters, str):
            text = filters.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return filters if isinstance(filters, dict) else {}

    def _normalize_tag_filter(self, tags: Any) -> list[str]:
        if not tags:
            return []
        if isinstance(tags, str):
            raw_items = re.split(r"[,，\s]+", tags)
        elif isinstance(tags, (list, tuple, set)):
            raw_items = [str(item) for item in tags]
        else:
            raw_items = [str(tags)]
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            tag = str(item or "").strip().lstrip("#").lower()
            if tag and tag not in seen:
                seen.add(tag)
                result.append(tag)
        return result

    def _row_has_all_tags(self, row: dict, tags: list[str]) -> bool:
        row_tags = {
            str(item or "").strip().lstrip("#").lower()
            for item in _safe_json_loads(row.get("tags_json"), [])
            if str(item or "").strip()
        }
        return all(tag in row_tags for tag in tags)

    def _memory_source_kind(self, row: dict) -> str:
        source_model = str(row.get("source_model") or "").strip().lower()
        if source_model.startswith("inline-mem"):
            return "inline"
        if source_model.startswith("manual") or source_model in {"", "none", "null"}:
            return "manual"
        return "auto"

    def _supabase_table_hint(self, table: str) -> str:
        normalized = (table or "").strip().lower()
        if normalized in {"heartbeat", "heartbeats", "heartbeat_entries", "gateway_heartbeats"}:
            return "heartbeat_entries lives in the gateway SQLite store, not Supabase. Use shenyu_read_heartbeat with date/date_from/date_to instead."
        if normalized in {"gateway_messages", "request_context_snapshots", "raw_request_windows"}:
            return f"{normalized} lives in the gateway SQLite store, not Supabase."
        return ""

    def _friendly_supabase_error(self, table: str, exc: Exception) -> str:
        raw = str(exc)
        if "404" in raw:
            hint = self._supabase_table_hint(table)
            if hint:
                return hint
            return f"Supabase table '{table}' was not found. Check the table name with shenyu_supabase_guide, or use a dedicated shenyu_* tool if this data lives in the gateway store."
        return raw

    async def _load_tags_for_memories(self, memory_ids: list[str]) -> dict[str, list[dict]]:
        if not memory_ids or not supabase_client:
            return {}
        ids = ",".join(memory_ids)
        rows = await self._safe_query(
            "memory_tags",
            {
                "memory_id": f"in.({ids})",
                "select": "memory_id,tag,tag_type",
                "limit": "200",
            },
        )
        result: dict[str, list[dict]] = {}
        for row in rows:
            result.setdefault(row.get("memory_id"), []).append(
                {"tag": row.get("tag"), "tag_type": row.get("tag_type")}
            )
        return result

    async def _load_links_for_memories(self, memory_ids: list[str]) -> tuple[dict[str, list[dict]], dict[str, str]]:
        if not memory_ids or not supabase_client:
            return {}, {}
        ids = ",".join(memory_ids)
        rows = await self._safe_query(
            "memory_links",
            {
                "or": f"(memory_a.in.({ids}),memory_b.in.({ids}))",
                "select": "id,memory_a,memory_b,link_type,strength",
                "limit": "200",
            },
        )
        result: dict[str, list[dict]] = {}
        neighbor_ids: set[str] = set()
        for row in rows:
            a = row.get("memory_a")
            b = row.get("memory_b")
            if a:
                result.setdefault(a, []).append(row)
            if b and b != a:
                result.setdefault(b, []).append(row)
            if a and a not in memory_ids:
                neighbor_ids.add(a)
            if b and b not in memory_ids:
                neighbor_ids.add(b)

        title_lookup: dict[str, str] = {}
        if neighbor_ids:
            neighbors = await self._safe_query(
                "memories",
                {
                    "id": f"in.({','.join(neighbor_ids)})",
                    "select": "id,title",
                    "limit": "200",
                },
            )
            title_lookup = {row.get("id"): row.get("title") or "untitled" for row in neighbors}

        return result, title_lookup

    async def _boost_memory(self, memory_id: str):
        if not supabase_client:
            return
        try:
            await supabase_client.rpc("boost_memory", {"memory_uuid": memory_id})
        except Exception:
            return

    def _memory_why(self, query: str, memory: dict, tags: list[dict], links: list[dict]) -> list[str]:
        reasons = []
        full_text = "\n".join(
            [
                memory.get("title") or "",
                memory.get("summary") or "",
                memory.get("facts") or "",
                memory.get("emotional_context") or "",
            ]
        )
        if _keyword_overlap_score(query, full_text) >= 0.4:
            reasons.append("keyword overlap")
        if (memory.get("importance") or 0) >= 4:
            reasons.append("high-importance memory")
        if (memory.get("weight") or 0) >= 1.2:
            reasons.append("frequently activated")
        if self._query_matches_tags(query, tags):
            reasons.append("tag match")
        elif tags:
            reasons.append("tagged memory")
        if self._has_strong_link(links):
            reasons.append("strongly linked thread")
        elif links:
            reasons.append("linked into a thread")
        return reasons or ["event memory supplement"]

    def _build_linked_threads(self, cards: list[dict]) -> list[dict]:
        threads = []
        for card in cards:
            links = card.get("links") or []
            if not links:
                continue
            strong = sorted(links, key=lambda row: row.get("strength", 0), reverse=True)
            threads.append(
                {
                    "id": card.get("id"),
                    "title": card.get("title"),
                    "link_count": len(links),
                    "top_links": strong[:3],
                    "why": ["linked thread", "adjacent remembered events"],
                }
            )
        threads.sort(key=lambda row: row.get("link_count", 0), reverse=True)
        return threads[:3]

    def _decorate_links(self, memory_id: Optional[str], links: list[dict], linked_titles: dict[str, str]) -> list[dict]:
        decorated = []
        for link in links:
            other_id = link.get("memory_b") if link.get("memory_a") == memory_id else link.get("memory_a")
            decorated.append(
                {
                    "id": link.get("id"),
                    "other_memory_id": other_id,
                    "other_title": linked_titles.get(other_id, "linked memory"),
                    "link_type": link.get("link_type"),
                    "strength": link.get("strength"),
                }
            )
        decorated.sort(key=lambda row: row.get("strength") or 0, reverse=True)
        return decorated

    def _query_matches_tags(self, query: str, tags: list[dict]) -> bool:
        terms = _keyword_terms(query)
        if not terms:
            return False
        tag_texts = [(tag.get("tag") or "").lower() for tag in tags]
        return any(term in tag_text for term in terms for tag_text in tag_texts)

    def _query_matches_text_items(self, query: str, items: Any) -> bool:
        terms = _keyword_terms(query)
        if not terms:
            return False
        if isinstance(items, str):
            texts = [items.lower()]
        elif isinstance(items, list):
            texts = []
            for item in items:
                if isinstance(item, dict):
                    texts.extend(str(value).lower() for value in item.values() if value)
                elif item:
                    texts.append(str(item).lower())
        else:
            texts = [str(items).lower()] if items else []
        return any(term in text for term in terms for text in texts)

    async def _boost_atomic_memory(self, memory_id: Optional[str]):
        if not memory_id or not supabase_client:
            return
        try:
            await supabase_client.rpc("boost_atomic_memory", {"memory_uuid": memory_id})
        except Exception:
            try:
                await supabase_client.update(
                    "atomic_memories",
                    {"id": memory_id},
                    {
                        "heat": 0.75,
                        "last_activated": _iso_now(),
                    },
                )
            except Exception:
                logger.debug("[AtomicMemory] boost skipped for %s", memory_id)

    def _has_strong_link(self, links: list[dict]) -> bool:
        return any((link.get("strength") or 0) >= 0.75 for link in links)
