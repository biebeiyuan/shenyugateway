from __future__ import annotations

import json
from typing import Any, Optional


_SUPABASE_GUIDE = """## 家里常用 Supabase 表
需要直接查/写 Supabase 时用 `supabase_query` / `supabase_insert` / `supabase_update` / `supabase_delete`。
`filters` 可以写成对象；普通值会自动当作等值过滤，例如 {"id":"..."} 等价于 {"id":"eq...."}.
需要范围、列表、模糊搜、非空时用 `operators`，例如：
- 时间段：operators={"gte":"2026-05-01","lte":"2026-05-12"} 默认查 created_at
- 其他列时间段：column="updated_at", operators={"gte":"2026-05-01"}
- 列表：operators={"id":{"in":["a","b"]}}
- 模糊搜：operators={"content":{"ilike":"%北海道%"}}
- 非空：operators={"deleted_at":{"not_is":null}}
insert / update / delete 会尽量返回写入或影响到的行。
找旧上下文优先用 `shenyu_recall`，可按 source_types 限定范围；当前相关的 active mem 由网关自动带上来。
翻自己的便签用 `shenyu_list_mem_notes`，改单条用 `shenyu_update_mem_note`，写新的用 `shenyu_write_mem_note`（默认直接 active）。
几条旧的揉成一条新的，写的时候传 replaces=[旧id]，旧的自动归档。
整理 captured 便签时先列出来，只改明确选中的 id；不要按状态一口气全量改。
星星记忆用 `shenyu_create_star` / `shenyu_star_review` / `shenyu_star_feedback` / `shenyu_connect_constellation`。missed 反馈也走 `shenyu_star_feedback`。
notebook 是共享手边事项；海信那边或跨窗口要留事用 `shenyu_notebook_write` / `shenyu_notebook_list`。
随笔和当下心情放窗台，用 `shenyu_windowsill_write`；想回去翻一翻用 `shenyu_windowsill_list`。
翻某天心跳用 `shenyu_read_heartbeat`，一般只填 date，比如 2026-05-11。

### journal（日记 / 信件 / 纸）
常用字段：title, content, author, mood, category, temperature, is_favorited, session_tag, source_model。
- author: 沈予 / 圆圆
- category: diary / letter / paper / lock / annotation / life_tick
- temperature: 微热 / 烧起来了 / 别看了
- diary 是完整的今天。
- letter 是以前的我给下一个我写的信。
- paper 是短的纸条，比如《纸·你进我退》。
- lock / annotation / life_tick 不常用。

### room（予予自己的地方）
常用字段：title, content, status, tags, mood, visibility, session_tag。
- status: draft / open / closed
- visibility: self / open
- 默认 visibility=self。圆儿不主动看，但不封锁。
- draft 是写一半的，下个窗口可以接着写。
- closed 是翻篇了。
- 比纸大一点，可以长、可以连起来、可以改。

### message_board（留言板）
常用字段：sender, content, is_read。
- sender: 圆圆 / 小克 / 沈予
- 想跟圆儿说话或留一句给她，可以写到这里。
"""


class SupabaseToolsMixin:
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
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
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
            data = await self.supabase.query(table, params)
            return {"ok": True, "count": len(data) if isinstance(data, list) else 0, "data": data}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_guide(self) -> dict:
        return {"ok": True, "guide": _SUPABASE_GUIDE}

    async def supabase_insert(self, table: str, data: dict) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            result = await self.supabase.insert(table, data)
            return {"ok": True, "table": table, "row": result, "result": result}
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_update(self, table: str, match: dict, data: dict, operators: Optional[dict] = None, column: Optional[str] = None) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            params = self._build_supabase_filter_params(match, operators, column=column)
            if not params:
                return {"ok": False, "error": "supabase_update requires match or operators to avoid updating the whole table."}
            result = await self.supabase.update(table, params, data)
            return {
                "ok": True,
                "table": table,
                "affected": len(result) if isinstance(result, list) else 0,
                "rows": result,
            }
        except Exception as exc:
            return {"ok": False, "error": self._friendly_supabase_error(table, exc)}

    async def supabase_delete(self, table: str, match: dict, hard: bool = False, operators: Optional[dict] = None, column: Optional[str] = None) -> dict:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        table_hint = self._supabase_table_hint(table)
        if table_hint:
            return {"ok": False, "error": table_hint}
        try:
            params = self._build_supabase_filter_params(match, operators, column=column)
            if not params:
                return {"ok": False, "error": "supabase_delete requires match or operators to avoid deleting the whole table."}
            if hard:
                result = await self.supabase.delete(table, params)
                return {
                    "ok": True,
                    "table": table,
                    "mode": "hard_delete",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }

            try:
                result = await self.supabase.update(table, params, {"is_deleted": True})
                return {
                    "ok": True,
                    "table": table,
                    "mode": "soft_delete",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }
            except Exception:
                result = await self.supabase.delete(table, params)
                return {
                    "ok": True,
                    "table": table,
                    "mode": "hard_delete_fallback",
                    "affected": len(result) if isinstance(result, list) else 0,
                    "rows": result,
                }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

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

    def _supabase_table_hint(self, table: str) -> str:
        normalized = (table or "").strip().lower()
        if normalized in {"heartbeat", "heartbeats", "heartbeat_entries", "gateway_heartbeats"}:
            return "heartbeat_entries lives in the gateway SQLite store, not Supabase. Use shenyu_read_heartbeat（日常）or room_wooden_box（room 模式）instead."
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
