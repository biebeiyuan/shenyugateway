from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Optional

from shenyu_gateway.memory_graph import MemoryGraphService
from shenyu_gateway.runtime import logger

from ._base import DEFAULT_RECALL_LIMIT, MAX_RECALL_LIMIT, RECALL_INDEX_TABLE
from ._documents import RecallDocument
from ._text import _QUOTED_TITLE_RE, _parse_date_bound, _parse_dt, _shorten, _vector_literal, classify_recall_mode, infer_recall_date, recall_terms


class QueryMixin:
    async def recall(
        self,
        query: str,
        *,
        source_types: Optional[list[str]] = None,
        mode: Optional[str] = None,
        session_tag: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_undated: bool = True,
        limit: int = DEFAULT_RECALL_LIMIT,
        auto_sync: Optional[bool] = None,
        include_trace: bool = False,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "error": "Supabase is not configured."}

        query_text = (query or "").strip()
        resolved_mode = classify_recall_mode(query_text, mode)
        if resolved_mode == "exact" and not date_from and not date_to:
            inferred_date = infer_recall_date(query_text)
            if inferred_date:
                date_from = inferred_date
                date_to = inferred_date
        tokens = recall_terms(query_text)
        should_auto_sync = self._auto_sync_enabled(auto_sync)
        sync_result = None
        try:
            keyword_rows = await self._query_index(source_types=source_types, query_text=query_text, tokens=tokens)
            title_rows = await self._query_title_candidates(source_types=source_types, query_text=query_text)
            date_rows = await self._query_date_candidates(
                source_types=source_types,
                date_from=date_from,
                date_to=date_to,
            )
            keyword_rows = self._merge_candidate_rows(title_rows + date_rows, keyword_rows)
        except Exception as exc:
            return {
                "ok": False,
                "query": query_text,
                "count": 0,
                "items": [],
                "error": f"recall index table is not ready: {exc}",
                "sync": sync_result,
            }

        graph_rows = await MemoryGraphService(self.supabase).recall_rows(
            query_text,
            source_types=self._source_type_filter(source_types),
            max_mentions=self._candidate_limit(),
        )
        vector_rows, _vector_meta = await self._vector_rows(query_text, source_types=source_types)
        rows = self._merge_candidate_rows(keyword_rows, graph_rows)
        rows = self._merge_candidate_rows(rows, vector_rows)
        if not rows and should_auto_sync:
            sync_result = sync_result or await self.rebuild(source_types=source_types, embed=False)
            if not sync_result.get("ok") and not sync_result.get("indexed"):
                return {
                    "ok": False,
                    "query": query_text,
                    "count": 0,
                    "items": [],
                    "error": sync_result.get("error") or sync_result.get("errors") or "recall index sync failed",
                    "sync": sync_result,
                }
            try:
                keyword_rows = await self._query_index(source_types=source_types, query_text=query_text, tokens=tokens)
                title_rows = await self._query_title_candidates(source_types=source_types, query_text=query_text)
                date_rows = await self._query_date_candidates(
                    source_types=source_types,
                    date_from=date_from,
                    date_to=date_to,
                )
                keyword_rows = self._merge_candidate_rows(title_rows + date_rows, keyword_rows)
            except Exception as exc:
                return {
                    "ok": False,
                    "query": query_text,
                    "count": 0,
                    "items": [],
                    "error": f"recall index table is not ready: {exc}",
                    "sync": sync_result,
                }
            graph_rows = await MemoryGraphService(self.supabase).recall_rows(
                query_text,
                source_types=self._source_type_filter(source_types),
                max_mentions=self._candidate_limit(),
            )
            vector_rows, _vector_meta = await self._vector_rows(query_text, source_types=source_types)
            rows = self._merge_candidate_rows(keyword_rows, graph_rows)
            rows = self._merge_candidate_rows(rows, vector_rows)

        start_dt = _parse_date_bound(date_from)
        end_dt = _parse_date_bound(date_to, end_of_day=True)
        has_date_filter = bool(start_dt or end_dt)
        scored = []
        filtered_by_visibility = 0
        for row in rows:
            if not self._row_visible_for_session(row, session_tag):
                filtered_by_visibility += 1
                continue
            row_dt = _parse_dt(row.get("event_date") or row.get("source_updated_at"))
            if has_date_filter and not row_dt and not include_undated:
                continue
            if start_dt and row_dt and row_dt < start_dt:
                continue
            if end_dt and row_dt and row_dt > end_dt:
                continue
            score, reasons = self._score_row(row, query_text, tokens)
            exact_date_candidate = bool(resolved_mode == "exact" and has_date_filter and row_dt)
            if (
                tokens
                and not self._has_direct_match(reasons)
                and not row.get("_vector_score")
                and not row.get("_graph_score")
                and not exact_date_candidate
            ):
                continue
            tier = self._match_tier(row, query_text, reasons)
            if exact_date_candidate:
                tier = max(tier, 3)
            scored.append((score + tier * 2.0, reasons, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        requested_limit = max(1, min(int(limit or DEFAULT_RECALL_LIMIT), MAX_RECALL_LIMIT))
        if resolved_mode == "exact":
            requested_limit = 1
        elif resolved_mode == "mood":
            requested_limit = min(requested_limit, 3)
        selected = self._dedupe(scored, requested_limit)
        items = await asyncio.gather(
            *(self._hydrate_selected_item(row, session_tag=session_tag) for _, _, row in selected)
        )
        if include_trace:
            for item, (_, reasons, row) in zip(items, selected):
                item["recall_match"] = self._public_recall_match(row, reasons)
        logger.info(
            "[RecallTrace] mode=%s candidates=%s scored=%s visibility_filtered=%s selected=%s",
            resolved_mode,
            len(rows),
            len(scored),
            filtered_by_visibility,
            [
                {
                    "source_type": row.get("source_type"),
                    "source_id": row.get("source_id"),
                    "title": _shorten(row.get("title") or "", 80),
                    "rank": round(rank_score, 4),
                    "reasons": reasons,
                }
                for rank_score, reasons, row in selected
            ],
        )
        return {
            "ok": True,
            "count": len(items),
            "items": items,
        }

    async def read_source(
        self,
        source_type: str,
        source_id: str,
        *,
        source_table: Optional[str] = None,
        session_tag: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}
        normalized_id = str(source_id or "").strip()
        normalized_type = str(source_type or "").strip()
        if not normalized_id:
            return {"ok": False, "error": "source_id is required."}
        allowed_types = self._source_type_filter([normalized_type]) if normalized_type else []
        if normalized_type and not allowed_types:
            return {"ok": False, "error": f"Unsupported recall source_type: {normalized_type}"}
        params: dict[str, str] = {
            "select": "*",
            "source_id": f"eq.{normalized_id}",
            "deleted_at": "is.null",
            "order": "chunk_index.asc",
            "limit": "1000",
        }
        if allowed_types:
            params["source_type"] = "in.(" + ",".join(allowed_types) + ")"
        normalized_table = str(source_table or "").strip()
        if normalized_table:
            params["source_table"] = f"eq.{normalized_table}"
        rows = await self.supabase.query(RECALL_INDEX_TABLE, params)
        rows = [
            row
            for row in rows
            if str(row.get("source_id") or "") == normalized_id
            and (not allowed_types or str(row.get("source_type") or "") in allowed_types)
            and (not normalized_table or str(row.get("source_table") or "") == normalized_table)
            and self._row_visible_for_session(row, session_tag)
        ]
        rows.sort(key=lambda item: int(item.get("chunk_index") or 0))
        if not rows:
            return {"ok": False, "error": "Recall source not found."}
        first = rows[0]
        item = self._public_item(first, self._rows_by_source(rows))
        item["content"] = "\n\n".join(
            str(row.get("body") or row.get("excerpt") or "").strip()
            for row in rows
            if str(row.get("body") or row.get("excerpt") or "").strip()
        )
        item["has_more"] = False
        return {"ok": True, "item": item}

    async def _vector_rows(
        self,
        query: str,
        source_types: Optional[list[str]] = None,
        *,
        allow_mem_note: bool = False,
    ) -> tuple[list[dict], dict[str, Any]]:
        if not query.strip():
            return [], {"enabled": False, "used": False, "reason": "empty query"}
        if not self.embedding_client or not self.embedding_client.enabled:
            return [], {"enabled": False, "used": False, "reason": "Embedding API is not configured."}
        vector, error = await self.embedding_client.embed(query)
        if error or vector is None:
            return [], {"enabled": True, "used": False, "error": error or "query embedding failed"}
        types = self._source_type_filter(source_types, allow_mem_note=allow_mem_note)
        if self._requested_source_types(source_types) and not types:
            return [], {"enabled": True, "used": False, "reason": "no valid source_types"}
        try:
            rows = await self.supabase.rpc(
                "match_shenyu_recall_index",
                {
                    "query_embedding": _vector_literal(vector),
                    "match_count": min(self._candidate_limit(), 100),
                    "source_types": types or None,
                },
            )
        except Exception as exc:
            return [], {"enabled": True, "used": False, "error": str(exc)[:500]}
        if not isinstance(rows, list):
            rows = []
        rows = self._filter_rows_by_source_types(rows, types)
        filtered_rows = []
        for row in rows:
            row["_vector_score"] = float(row.get("vector_score") or 0.0)
            if row["_vector_score"] >= self._vector_min_score():
                filtered_rows.append(row)
        rows = filtered_rows
        return rows, {"enabled": True, "used": True, "count": len(rows)}

    def _merge_candidate_rows(self, keyword_rows: list[dict], vector_rows: list[dict]) -> list[dict]:
        merged: dict[tuple[str, str, int], dict] = {}
        for row in keyword_rows:
            key = (str(row.get("source_table") or ""), str(row.get("source_id") or ""), int(row.get("chunk_index") or 0))
            merged[key] = dict(row)
        for row in vector_rows:
            key = (str(row.get("source_table") or ""), str(row.get("source_id") or ""), int(row.get("chunk_index") or 0))
            existing = merged.get(key)
            if existing:
                existing["_vector_score"] = max(float(existing.get("_vector_score") or 0.0), float(row.get("_vector_score") or 0.0))
                existing["_graph_score"] = max(float(existing.get("_graph_score") or 0.0), float(row.get("_graph_score") or 0.0))
                if row.get("_graph_reason") == "direct" or not existing.get("_graph_reason"):
                    existing["_graph_reason"] = row.get("_graph_reason")
                    if row.get("_graph_info"):
                        existing["_graph_info"] = row.get("_graph_info")
            else:
                merged[key] = dict(row)
        return list(merged.values())

    def _filter_rows_by_source_types(self, rows: list[dict], types: list[str]) -> list[dict]:
        if not types:
            return rows
        allowed = set(types)
        return [row for row in rows if str(row.get("source_type") or "").strip() in allowed]

    def _row_matches_tokens(self, row: dict, tokens: list[str], query_text: str) -> bool:
        if not tokens and not query_text.strip():
            return True
        search_text = (row.get("search_text") or "").lower()
        row_tokens = {str(item).lower() for item in row.get("search_tokens") or []}
        if any(token in row_tokens or token in search_text for token in tokens):
            return True
        compact_query = re.sub(r"\s+", "", query_text.lower())
        compact_text = re.sub(r"\s+", "", search_text)
        return bool(compact_query and compact_query in compact_text)

    async def _query_index(
        self,
        source_types: Optional[list[str]] = None,
        query_text: str = "",
        tokens: Optional[list[str]] = None,
        *,
        allow_mem_note: bool = False,
    ) -> list[dict]:
        types = self._source_type_filter(source_types, allow_mem_note=allow_mem_note)
        if self._requested_source_types(source_types) and not types:
            return []
        candidate_limit = self._candidate_limit()
        if hasattr(self.supabase, "rpc"):
            try:
                rows = await self.supabase.rpc(
                    "search_shenyu_recall_index",
                    {
                        "query_tokens": tokens or [],
                        "query_text": query_text or "",
                        "match_count": candidate_limit,
                        "source_types": types or None,
                    },
                )
                if isinstance(rows, list):
                    return self._filter_rows_by_source_types(rows, types)
            except Exception as exc:
                logger.warning("Recall index RPC search failed; falling back to table query: %s", exc)

        params: dict[str, str] = {
            "select": "*",
            "deleted_at": "is.null",
            "order": "importance.desc,event_date.desc,indexed_at.desc",
            "limit": str(candidate_limit),
        }
        if types:
            params["source_type"] = "in.(" + ",".join(types) + ")"
        rows = await self.supabase.query(RECALL_INDEX_TABLE, params)
        rows = self._filter_rows_by_source_types(rows, types)
        if tokens or query_text.strip():
            return [row for row in rows if self._row_matches_tokens(row, tokens or [], query_text)]
        return rows

    async def _query_title_candidates(
        self,
        source_types: Optional[list[str]],
        query_text: str,
    ) -> list[dict]:
        quoted = _QUOTED_TITLE_RE.search(query_text or "")
        needle = (quoted.group(1) if quoted else query_text or "").strip()
        if not needle or len(needle) > 80:
            return []
        types = self._source_type_filter(source_types)
        if self._requested_source_types(source_types) and not types:
            return []
        params: dict[str, str] = {
            "select": "*",
            "deleted_at": "is.null",
            "title": f"ilike.*{needle}*",
            "order": "importance.desc,event_date.desc,indexed_at.desc",
            "limit": "20",
        }
        if types:
            params["source_type"] = "in.(" + ",".join(types) + ")"
        try:
            rows = await self.supabase.query(RECALL_INDEX_TABLE, params)
        except Exception as exc:
            logger.warning("Recall title candidate query failed: %s", exc)
            return []
        return self._filter_rows_by_source_types(rows if isinstance(rows, list) else [], types)

    async def _query_date_candidates(
        self,
        source_types: Optional[list[str]],
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> list[dict]:
        start_dt = _parse_date_bound(date_from)
        end_dt = _parse_date_bound(date_to, end_of_day=True)
        if not start_dt and not end_dt:
            return []
        types = self._source_type_filter(source_types)
        if self._requested_source_types(source_types) and not types:
            return []
        params: dict[str, str] = {
            "select": "*",
            "deleted_at": "is.null",
            "order": "event_date.asc,indexed_at.asc",
            "limit": "1000",
        }
        if start_dt:
            params["event_date"] = f"gte.{start_dt.isoformat()}"
        elif end_dt:
            params["event_date"] = f"lte.{end_dt.isoformat()}"
        if types:
            params["source_type"] = "in.(" + ",".join(types) + ")"
        try:
            rows = await self.supabase.query(RECALL_INDEX_TABLE, params)
        except Exception as exc:
            logger.warning("Recall date candidate query failed: %s", exc)
            return []
        filtered = []
        for row in rows if isinstance(rows, list) else []:
            row_dt = _parse_dt(row.get("event_date") or row.get("source_updated_at"))
            if not row_dt:
                continue
            if start_dt and row_dt < start_dt:
                continue
            if end_dt and row_dt > end_dt:
                continue
            filtered.append(row)
        return self._filter_rows_by_source_types(filtered, types)

    async def _hydrate_selected_item(
        self,
        row: dict[str, Any],
        *,
        session_tag: Optional[str],
    ) -> dict[str, Any]:
        try:
            result = await self.read_source(
                str(row.get("source_type") or ""),
                str(row.get("source_id") or ""),
                source_table=str(row.get("source_table") or ""),
                session_tag=session_tag,
            )
            if result.get("ok") and isinstance(result.get("item"), dict):
                return result["item"]
            raise RuntimeError(result.get("error") or "source hydration failed")
        except Exception as exc:
            item = self._public_item(row, self._rows_by_source([row]))
            item["content_complete"] = False
            item["content_error"] = str(exc)[:300]
            return item

    async def _mark_stale_source_deleted(self, source_table: str, docs: list[RecallDocument]) -> None:
        live_keys = {(doc.source_id, doc.chunk_index) for doc in docs}
        existing_rows = await self._query_all_rows(
            RECALL_INDEX_TABLE,
            {
                "select": "source_id,chunk_index",
                "source_table": f"eq.{source_table}",
                "deleted_at": "is.null",
                "order": "source_id.asc,chunk_index.asc",
            },
        )
        deleted_at = datetime.now(timezone.utc).isoformat()
        for row in existing_rows:
            key = (str(row.get("source_id") or ""), int(row.get("chunk_index") or 0))
            if key in live_keys:
                continue
            await self.supabase.update(
                RECALL_INDEX_TABLE,
                {
                    "source_table": source_table,
                    "source_id": key[0],
                    "chunk_index": key[1],
                },
                {"deleted_at": deleted_at},
            )
