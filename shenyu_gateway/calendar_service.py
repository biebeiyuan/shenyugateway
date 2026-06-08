from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, Request

from .calendar import (
    default_period_key,
    extract_json_object,
    fill_template,
    latest_page_by_key,
    month_grid,
    period_bounds,
    rows_to_prompt_configs,
)
from .calendar_sources import CalendarSourceCollector
from .gateway_tools import GatewayToolService
from .runtime import (
    iso_now as _iso_now,
    json_dumps as _json_dumps,
    parse_ts as _parse_ts,
)
from .schemas import CalendarGenerateRequest, CalendarPromptUpdate
from .upstream_adapter import _anthropic_to_openai_completion, _openai_to_anthropic


def _shorten(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _today_utc_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _safe_json_loads(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


class CalendarService:
    def __init__(
        self,
        *,
        cfg: Any,
        supabase_client: Any,
        session_store: Any,
        call_upstream_json_at: Callable[[Request, str, dict, dict], Awaitable[dict]],
        detect_protocol_for: Callable[[str, str], str],
        chat_url_for: Callable[[str, str], str],
        request: Optional[Request] = None,
    ):
        self.cfg = cfg
        self.supabase_client = supabase_client
        self.session_store = session_store
        self.call_upstream_json_at = call_upstream_json_at
        self.detect_protocol_for = detect_protocol_for
        self.chat_url_for = chat_url_for
        self.request = request

    def _source_collector(self) -> CalendarSourceCollector:
        async def query_calendar_pages(params: dict[str, str]) -> list[dict[str, Any]]:
            return await self._safe_supabase_query("calendar_pages", params)

        async def surface_passages(query: str, session_tag: Optional[str], limit: int) -> dict[str, Any]:
            return await GatewayToolService().surface_passages(query, session_tag=session_tag, limit=limit)

        return CalendarSourceCollector(
            session_store=self.session_store,
            calendar_page_query=query_calendar_pages,
            surface_passages=surface_passages,
            default_surface_limit=self.cfg.default_surface_limit,
        )

    def _require_supabase(self):
        if not self.supabase_client:
            raise HTTPException(status_code=400, detail="Supabase is not configured.")

    async def _safe_supabase_query(self, table: str, params: dict) -> list[dict]:
        try:
            return await self.supabase_client.query(table, params)
        except Exception:
            return []

    async def list_prompt_configs(self) -> dict[str, Any]:
        self._require_supabase()
        rows = await self.supabase_client.query(
            "calendar_prompt_configs",
            {"select": "*", "order": "prompt_type.asc,updated_at.desc", "limit": "50"},
        )
        configs = rows_to_prompt_configs(rows)
        grouped: dict[str, list[dict[str, Any]]] = {"day": [], "week": [], "month": []}
        active: dict[str, Optional[dict[str, Any]]] = {"day": None, "week": None, "month": None}
        for config in configs:
            item = {
                "id": config.id,
                "prompt_type": config.prompt_type,
                "name": config.name,
                "content": config.content,
                "version": config.version,
                "is_default": config.is_default,
                "is_active": config.is_active,
                "note": config.note,
                "updated_at": config.updated_at,
            }
            if config.prompt_type in grouped:
                grouped[config.prompt_type].append(item)
                if config.is_active:
                    active[config.prompt_type] = item
        return {"items": grouped, "active": active}

    async def save_prompt_config(self, body: CalendarPromptUpdate) -> dict[str, Any]:
        self._require_supabase()
        prompt_type = body.prompt_type.strip().lower()
        if prompt_type not in {"day", "week", "month"}:
            raise HTTPException(status_code=400, detail="Unsupported prompt_type.")
        rows = await self._safe_supabase_query(
            "calendar_prompt_configs",
            {
                "prompt_type": f"eq.{prompt_type}",
                "select": "version",
                "order": "version.desc",
                "limit": "1",
            },
        )
        next_version = int(rows[0]["version"]) + 1 if rows else 1
        if body.is_active:
            active_rows = await self._safe_supabase_query(
                "calendar_prompt_configs",
                {
                    "prompt_type": f"eq.{prompt_type}",
                    "is_active": "eq.true",
                    "select": "id",
                    "limit": "20",
                },
            )
            for row in active_rows:
                await self.supabase_client.update(
                    "calendar_prompt_configs",
                    {"id": row.get("id")},
                    {"is_active": False},
                )

        created = await self.supabase_client.insert(
            "calendar_prompt_configs",
            {
                "prompt_type": prompt_type,
                "name": body.name or f"{prompt_type.title()} Prompt v{next_version}",
                "content": body.content,
                "note": body.note or "",
                "version": next_version,
                "is_default": False,
                "is_active": bool(body.is_active),
            },
        )
        return {"ok": True, "item": created}

    async def activate_prompt_config(self, prompt_id: str) -> dict[str, Any]:
        self._require_supabase()
        rows = await self._safe_supabase_query(
            "calendar_prompt_configs",
            {"id": f"eq.{prompt_id}", "select": "*", "limit": "1"},
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Prompt config not found.")
        prompt = rows[0]
        prompt_type = prompt.get("prompt_type") or ""
        active_rows = await self._safe_supabase_query(
            "calendar_prompt_configs",
            {
                "prompt_type": f"eq.{prompt_type}",
                "is_active": "eq.true",
                "select": "id",
                "limit": "20",
            },
        )
        for row in active_rows:
            await self.supabase_client.update(
                "calendar_prompt_configs",
                {"id": row.get("id")},
                {"is_active": False},
            )
        updated = await self.supabase_client.update("calendar_prompt_configs", {"id": prompt_id}, {"is_active": True})
        return {"ok": True, "item": updated[0] if updated else prompt}

    async def month_status(self, month_key: Optional[str]) -> dict[str, Any]:
        self._require_supabase()
        month_key = month_key or default_period_key("month")
        rows = await self._safe_supabase_query(
            "calendar_pages",
            {"select": "*", "limit": "500", "order": "period_start.asc,updated_at.desc"},
        )
        latest = latest_page_by_key(rows)
        pages = list(latest.values())
        days_by_key = {row["period_key"]: row for row in pages if row.get("period_type") == "day"}
        weeks_by_key = {row["period_key"]: row for row in pages if row.get("period_type") == "week"}
        months_by_key = {row["period_key"]: row for row in pages if row.get("period_type") == "month"}

        grid = month_grid(month_key)
        for item in grid:
            item["has_day"] = item["date"] in days_by_key
            item["has_week"] = item["week_key"] in weeks_by_key
            item["has_month"] = month_key in months_by_key
            if item["has_day"]:
                row = days_by_key[item["date"]]
                item["day_page"] = {
                    "id": row.get("id"),
                    "title": row.get("title") or "",
                    "summary": row.get("summary") or "",
                    "status": row.get("status") or "final",
                }
        return {
            "month_key": month_key,
            "grid": grid,
            "pages": {
                "day": [
                    {
                        "id": row.get("id"),
                        "period_key": row.get("period_key"),
                        "title": row.get("title") or "",
                        "summary": row.get("summary") or "",
                        "updated_at": row.get("updated_at") or row.get("created_at"),
                    }
                    for row in sorted(days_by_key.values(), key=lambda item: item.get("period_key", ""), reverse=True)
                    if (row.get("period_key") or "").startswith(month_key)
                ],
                "week": [
                    {
                        "id": row.get("id"),
                        "period_key": row.get("period_key"),
                        "title": row.get("title") or "",
                        "summary": row.get("summary") or "",
                        "updated_at": row.get("updated_at") or row.get("created_at"),
                    }
                    for row in sorted(weeks_by_key.values(), key=lambda item: item.get("period_key", ""), reverse=True)
                ],
                "month": [
                    {
                        "id": row.get("id"),
                        "period_key": row.get("period_key"),
                        "title": row.get("title") or "",
                        "summary": row.get("summary") or "",
                        "updated_at": row.get("updated_at") or row.get("created_at"),
                    }
                    for row in sorted(months_by_key.values(), key=lambda item: item.get("period_key", ""), reverse=True)
                ],
            },
        }

    async def page_detail(self, page_id: str) -> dict[str, Any]:
        self._require_supabase()
        rows = await self._safe_supabase_query("calendar_pages", {"id": f"eq.{page_id}", "select": "*", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="Calendar page not found.")
        row = rows[0]
        row["source_refs"] = _safe_json_loads(row.get("source_refs"), [])
        row["session_tags"] = _safe_json_loads(row.get("session_tags"), [])
        row["meta"] = _safe_json_loads(row.get("meta"), {})
        return row

    async def preview_sources(
        self,
        period_type: str,
        period_key: Optional[str],
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        self._require_supabase()
        period_type = (period_type or "").strip().lower()
        if period_type not in {"day", "week", "month"}:
            raise HTTPException(status_code=400, detail="Unsupported period_type.")
        period_key = period_key or default_period_key(period_type)
        return await self._collect_sources(period_type, period_key, session_tag=session_tag)

    async def send_preview(
        self,
        period_type: str,
        period_key: Optional[str],
        model_override: Optional[str] = None,
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        self._require_supabase()
        period_type = (period_type or "").strip().lower()
        if period_type not in {"day", "week", "month"}:
            raise HTTPException(status_code=400, detail="Unsupported period_type.")
        period_key = period_key or default_period_key(period_type)
        prompt_row = await self._active_prompt(period_type)
        sources = await self._collect_sources(period_type, period_key, session_tag=session_tag)
        prompt_pack = await self._build_generation_prompt(period_type, period_key, prompt_row, sources)
        upstream = self._calendar_upstream(model_override)
        return {
            "period_type": period_type,
            "period_key": period_key,
            "protocol": upstream["protocol"],
            "model": upstream["model"],
            "upstream_url": upstream["chat_url"],
            "prompt_name": prompt_row.get("name") or "",
            "prompt_version": prompt_row.get("version"),
            "system_prompt": prompt_pack["system_prompt"],
            "user_prompt": prompt_pack["user_prompt"],
            "source_block": prompt_pack["source_block"],
            "source_counts": CalendarSourceCollector.source_counts(sources),
        }

    async def generate_page(self, body: CalendarGenerateRequest) -> dict[str, Any]:
        self._require_supabase()
        if not self.request:
            raise HTTPException(status_code=500, detail="Calendar generation requires request context.")
        period_type = (body.period_type or "").strip().lower()
        if period_type not in {"day", "week", "month"}:
            raise HTTPException(status_code=400, detail="Unsupported period_type.")
        period_key = body.period_key or default_period_key(period_type)
        prompt_row = await self._active_prompt(period_type)
        sources = await self._collect_sources(period_type, period_key, session_tag=body.session_tag)
        run = await self.supabase_client.insert(
            "calendar_generation_runs",
            {
                "period_type": period_type,
                "period_key": period_key,
                "status": "running",
                "initiated_by": "manual_ui",
                "source_model": body.model or getattr(self.cfg, "calendar_model", "") or "",
                "source_refs": _json_dumps(sources.get("source_refs") or []),
                "started_at": _iso_now(),
            },
        )
        try:
            generated = await self._run_generation_model(
                period_type=period_type,
                period_key=period_key,
                prompt_row=prompt_row,
                sources=sources,
                model_override=body.model,
            )
            page = await self._upsert_page(
                period_type=period_type,
                period_key=period_key,
                prompt_row=prompt_row,
                sources=sources,
                generated=generated,
                source_model=body.model or getattr(self.cfg, "calendar_model", "") or "manual",
            )
            await self.supabase_client.update(
                "calendar_generation_runs",
                {"id": run.get("id")},
                {"status": "done", "page_id": page.get("id"), "finished_at": _iso_now()},
            )
            return {"ok": True, "run": run, "page": page}
        except Exception as exc:
            await self.supabase_client.update(
                "calendar_generation_runs",
                {"id": run.get("id")},
                {"status": "failed", "error_message": str(exc)[:1000], "finished_at": _iso_now()},
            )
            raise

    async def _active_prompt(self, period_type: str) -> dict[str, Any]:
        rows = await self._safe_supabase_query(
            "calendar_prompt_configs",
            {
                "prompt_type": f"eq.{period_type}",
                "is_active": "eq.true",
                "select": "*",
                "limit": "1",
            },
        )
        if rows:
            return rows[0]
        rows = await self._safe_supabase_query(
            "calendar_prompt_configs",
            {
                "prompt_type": f"eq.{period_type}",
                "is_default": "eq.true",
                "select": "*",
                "limit": "1",
            },
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"No prompt config found for {period_type}.")
        return rows[0]

    async def _collect_sources(
        self,
        period_type: str,
        period_key: str,
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        return await self._source_collector().collect_sources(period_type, period_key, session_tag=session_tag)

    def _context_snapshots(
        self,
        limit: int = 5,
        session_tag: Optional[str] = None,
        message_limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        return self._source_collector().context_snapshots(
            limit=limit,
            session_tag=session_tag,
            message_limit=message_limit,
        )

    async def _build_generation_prompt(
        self,
        period_type: str,
        period_key: str,
        prompt_row: dict[str, Any],
        sources: dict[str, Any],
    ) -> dict[str, Any]:
        rows = await self._safe_supabase_query(
            "calendar_pages",
            {
                "select": "period_end",
                "period_type": f"eq.{period_type}",
                "is_latest": "eq.true",
                "order": "period_end.desc",
                "limit": "1",
            },
        )
        days_since_last = 0
        if rows:
            last_end = _parse_ts(rows[0].get("period_end"))
            current_start = _parse_ts(sources.get("period_start"))
            if last_end and current_start:
                days_since_last = max((current_start.date() - last_end.date()).days, 0)

        today_date = period_key if period_type == "day" else _today_utc_key()
        user_prompt = fill_template(
            prompt_row.get("content") or "",
            today_date=today_date,
            days_since_last=days_since_last,
        )
        system_prompt = (
            "You are write a private calendar memory page in Chinese.\n"
            "It may be intimate, partial, tender, blunt, playful, or quiet; do not make it sound like a product report.\n"
            "Return exactly one valid JSON object with string keys: title, content, summary, digest.\n"
            "The JSON object is only a storage envelope; content must be the actual page text, not another JSON string, not markdown, and not an array.\n"
            "Use Chinese corner quotes like 「」 inside strings when quoting speech, so the JSON stays valid.\n"
            "content can be short or long as needed, usually around 0-300 Chinese characters but flexible.\n"
            "summary is one concise line for calendar listing.\n"
            "digest is a short, tender memory snippet under 180 Chinese characters to help us recall and revisit our moments later.\n"
        )
        source_block = CalendarSourceCollector.render_source_block(period_type, sources)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + "\n\n我们刚刚聊了这些：\n\n" + source_block},
        ]
        return {
            "days_since_last": days_since_last,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "source_block": source_block,
            "messages": messages,
        }

    def _calendar_upstream(self, model_override: Optional[str] = None) -> dict[str, str]:
        calendar_url = (getattr(self.cfg, "calendar_upstream_url", "") or "").strip()
        base_url = calendar_url or self.cfg.upstream_url.strip()
        configured_protocol = getattr(self.cfg, "calendar_protocol", "auto") or "auto"
        if not calendar_url and configured_protocol == "auto":
            configured_protocol = self.cfg.upstream_protocol
        protocol = self.detect_protocol_for(base_url, configured_protocol)
        model = (model_override or getattr(self.cfg, "calendar_model", "") or "default").strip()
        api_key = (getattr(self.cfg, "calendar_api_key", "") or self.cfg.upstream_api_key).strip()
        return {
            "base_url": base_url,
            "chat_url": self.chat_url_for(base_url, protocol),
            "protocol": protocol,
            "model": model,
            "api_key": api_key,
        }

    async def _run_generation_model(
        self,
        *,
        period_type: str,
        period_key: str,
        prompt_row: dict[str, Any],
        sources: dict[str, Any],
        model_override: Optional[str],
    ) -> dict[str, Any]:
        prompt_pack = await self._build_generation_prompt(period_type, period_key, prompt_row, sources)
        upstream = self._calendar_upstream(model_override)
        if not upstream["base_url"] or not upstream["api_key"]:
            raise HTTPException(status_code=400, detail="Calendar upstream URL/API key is not configured.")

        if upstream["protocol"] == "anthropic":
            system, messages = _openai_to_anthropic(prompt_pack["messages"], cache_layers={}, cache_paths=[])
            payload: dict[str, Any] = {
                "model": upstream["model"],
                "messages": messages,
                "max_tokens": 700,
                "temperature": 0.9,
            }
            if system:
                payload["system"] = system
            headers = {
                "x-api-key": upstream["api_key"],
                "anthropic-version": self.cfg.upstream_version,
                "content-type": "application/json",
            }
            raw_response = await self.call_upstream_json_at(self.request, upstream["chat_url"], payload, headers)
            raw = _anthropic_to_openai_completion(upstream["model"], raw_response)
        else:
            payload = {
                "model": upstream["model"],
                "messages": prompt_pack["messages"],
                "max_tokens": 700,
                "temperature": 0.9,
            }
            headers = {"Authorization": f"Bearer {upstream['api_key']}", "content-type": "application/json"}
            raw = await self.call_upstream_json_at(self.request, upstream["chat_url"], payload, headers)

        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        generated = extract_json_object(content)
        if not (generated.get("content") or "").strip():
            generated["content"] = content.strip() or "No concrete content was written today."
        if not (generated.get("digest") or "").strip():
            generated["digest"] = _shorten(generated.get("content") or "", 180)
        return generated

    async def _upsert_page(
        self,
        *,
        period_type: str,
        period_key: str,
        prompt_row: dict[str, Any],
        sources: dict[str, Any],
        generated: dict[str, Any],
        source_model: str,
    ) -> dict[str, Any]:
        start, end = period_bounds(period_type, period_key)
        rows = await self._safe_supabase_query(
            "calendar_pages",
            {
                "select": "*",
                "period_type": f"eq.{period_type}",
                "period_key": f"eq.{period_key}",
                "is_latest": "eq.true",
                "limit": "1",
            },
        )
        version = 1
        if rows:
            version = int(rows[0].get("version") or 1) + 1
            await self.supabase_client.update("calendar_pages", {"id": rows[0].get("id")}, {"is_latest": False})

        page = await self.supabase_client.insert(
            "calendar_pages",
            {
                "period_type": period_type,
                "period_key": period_key,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "version": version,
                "is_latest": True,
                "title": (generated.get("title") or "").strip(),
                "content": (generated.get("content") or "").strip(),
                "summary": (generated.get("summary") or "").strip(),
                "digest": (generated.get("digest") or generated.get("summary") or "").strip(),
                "author": "沈予",
                "source_model": source_model,
                "source_refs": _json_dumps(sources.get("source_refs") or []),
                "session_tags": _json_dumps(sources.get("session_tags") or []),
                "meta": _json_dumps({"source_counts": CalendarSourceCollector.source_counts(sources)}),
                "status": "final",
                "prompt_snapshot": prompt_row.get("content") or "",
                "generated_by": "manual",
            },
        )
        page["source_refs"] = sources.get("source_refs") or []
        page["session_tags"] = sources.get("session_tags") or []
        page["meta"] = {"source_counts": CalendarSourceCollector.source_counts(sources)}
        return page
