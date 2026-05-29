from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from shenyu_gateway.embeddings import EmbeddingClient


RECALL_INDEX_TABLE = "shenyu_recall_index"
RECALL_CHUNK_MIN_CHARS = 140
RECALL_CHUNK_MAX_CHARS = 900
EMBEDDING_TEXT_MAX_CHARS = 1600
DEFAULT_RECALL_CANDIDATE_LIMIT = 160


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return " ".join(_normalize_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _shorten(text: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"value": text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": value}


def recall_terms(text: str) -> list[str]:
    raw = (text or "").replace("\n", " ")
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str):
        normalized = term.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)

    for token in re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]+", raw):
        add(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            for size in (2, 3):
                if len(token) < size:
                    continue
                for idx in range(0, len(token) - size + 1):
                    add(token[idx : idx + size])
    return terms


def split_recall_chunks(text: str, min_chars: int = RECALL_CHUNK_MIN_CHARS, max_chars: int = RECALL_CHUNK_MAX_CHARS) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return []

    parts = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    if not parts:
        parts = [clean]

    chunks: list[str] = []
    buffer = ""
    for part in parts:
        candidate = f"{buffer}\n\n{part}".strip() if buffer else part
        if len(candidate) <= max_chars:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
            buffer = ""

        if len(part) <= max_chars:
            buffer = part
            continue

        sentences = [item.strip() for item in re.split(r"(?<=[。！？!?；;])", part) if item.strip()]
        if not sentences:
            sentences = [part]
        sentence_buffer = ""
        for sentence in sentences:
            sentence_candidate = f"{sentence_buffer}{sentence}".strip() if sentence_buffer else sentence
            if len(sentence_candidate) <= max_chars:
                sentence_buffer = sentence_candidate
                continue
            if sentence_buffer:
                chunks.append(sentence_buffer)
                sentence_buffer = ""
            start = 0
            while start < len(sentence):
                piece = sentence[start : start + max_chars].strip()
                if piece:
                    chunks.append(piece)
                start += max_chars
        if sentence_buffer:
            buffer = sentence_buffer

    if buffer:
        chunks.append(buffer)

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) < min_chars and len(merged[-1]) + len(chunk) + 2 <= max_chars:
            merged[-1] = f"{merged[-1]}\n\n{chunk}"
        else:
            merged.append(chunk)
    return merged


def build_embedding_text(title: str, tags: list[Any], body: str, max_chars: int = EMBEDDING_TEXT_MAX_CHARS) -> str:
    tag_text = " ".join(str(tag) for tag in tags[:24] if str(tag).strip())
    prefix_parts = []
    if title:
        prefix_parts.append(f"标题：{title.strip()}")
    if tag_text:
        prefix_parts.append(f"标签：{tag_text}")
    prefix = "\n".join(prefix_parts).strip()
    body_label = "正文："
    available = max_chars - len(prefix) - len(body_label) - (2 if prefix else 0)
    available = max(160, available)
    clean_body = (body or "").strip()
    if len(clean_body) > available:
        clean_body = clean_body[:available].rstrip()
    parts = [part for part in [prefix, body_label + clean_body if clean_body else ""] if part]
    return "\n\n".join(parts)[:max_chars].strip()


def _content_hash(parts: list[Any]) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            text += "T00:00:00+00:00"
        text = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_dt(value: Any) -> Optional[str]:
    dt = _parse_dt(value)
    return dt.isoformat() if dt else None


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in vector) + "]"


def _recency_score(value: Any) -> float:
    dt = _parse_dt(value)
    if not dt:
        return 0.3
    days = max((datetime.now(timezone.utc) - dt).days, 0)
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.75
    if days <= 180:
        return 0.55
    if days <= 365:
        return 0.4
    return 0.3


@dataclass
class RecallDocument:
    source_table: str
    source_id: str
    source_type: str
    chunk_index: int
    session_tag: Optional[str]
    title: str
    body: str
    excerpt: str
    search_text: str
    search_tokens: list[str]
    embedding_text: str
    tags_json: list[Any]
    entities_json: list[Any]
    metadata_json: dict[str, Any]
    event_date: Optional[str]
    source_created_at: Optional[str]
    source_updated_at: Optional[str]
    status: Optional[str]
    visibility: Optional[str]
    importance: float
    content_hash: str

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["deleted_at"] = None
        if not row.get("embedding_text"):
            row["embedding_status"] = "skipped"
        return row


def _make_documents(
    *,
    source_table: str,
    source_id: Any,
    source_type: str,
    title: Any,
    body: Any,
    session_tag: Any = None,
    tags: Any = None,
    entities: Any = None,
    metadata: Any = None,
    event_date: Any = None,
    created_at: Any = None,
    updated_at: Any = None,
    status: Any = None,
    visibility: Any = None,
    importance: float = 0.5,
    chunk: bool = True,
) -> list[RecallDocument]:
    title_text = _normalize_text(title).strip()
    body_text = _normalize_text(body).strip()
    if not body_text and not title_text:
        return []

    tag_items = [str(item).strip() for item in _json_list(tags) if item is not None and str(item).strip()]
    entity_items = [str(item).strip() for item in _json_list(entities) if item is not None and str(item).strip()]
    metadata_obj = _json_dict(metadata)
    chunks = split_recall_chunks(body_text) if chunk else [body_text]
    if not chunks:
        chunks = [body_text or title_text]

    docs = []
    for index, chunk_text in enumerate(chunks):
        search_text = "\n".join(
            part
            for part in [
                title_text,
                chunk_text,
                " ".join(tag_items),
                " ".join(entity_items),
                _normalize_text(metadata_obj),
            ]
            if part
        )
        tokens = recall_terms(search_text)
        docs.append(
            RecallDocument(
                source_table=source_table,
                source_id=str(source_id),
                source_type=source_type,
                chunk_index=index,
                session_tag=_normalize_text(session_tag).strip() or None,
                title=title_text,
                body=chunk_text,
                excerpt=_shorten(chunk_text or title_text, 360),
                search_text=search_text,
                search_tokens=tokens,
                embedding_text=build_embedding_text(title_text, tag_items + entity_items, chunk_text),
                tags_json=tag_items,
                entities_json=entity_items,
                metadata_json=metadata_obj,
                event_date=_iso_dt(event_date),
                source_created_at=_iso_dt(created_at),
                source_updated_at=_iso_dt(updated_at or created_at),
                status=_normalize_text(status).strip() or None,
                visibility=_normalize_text(visibility).strip() or None,
                importance=max(0.0, min(float(importance or 0.5), 1.0)),
                content_hash=_content_hash(
                    [
                        source_table,
                        source_id,
                        index,
                        title_text,
                        chunk_text,
                        tag_items,
                        entity_items,
                        metadata_obj,
                        status,
                        visibility,
                    ]
                ),
            )
        )
    return docs


class RecallIndexService:
    def __init__(self, supabase: Any, cfg: Any = None, embedding_client: Optional[EmbeddingClient] = None):
        self.supabase = supabase
        self.cfg = cfg
        self.embedding_client = embedding_client or self._embedding_client_from_config(cfg)

    def _embedding_client_from_config(self, cfg: Any) -> Optional[EmbeddingClient]:
        if not cfg or not getattr(cfg, "enable_recall_embeddings", False):
            return None
        return EmbeddingClient(
            base_url=getattr(cfg, "embedding_base_url", ""),
            api_key=getattr(cfg, "embedding_api_key", ""),
            model=getattr(cfg, "embedding_model", ""),
            expected_dim=int(getattr(cfg, "embedding_dim", 1024) or 1024),
        )

    def _candidate_limit(self) -> int:
        raw_limit = getattr(self.cfg, "recall_candidate_limit", DEFAULT_RECALL_CANDIDATE_LIMIT)
        try:
            limit = int(raw_limit or DEFAULT_RECALL_CANDIDATE_LIMIT)
        except (TypeError, ValueError):
            limit = DEFAULT_RECALL_CANDIDATE_LIMIT
        return max(20, min(limit, 1000))

    def _requested_source_types(self, source_types: Optional[list[str]]) -> list[str]:
        types = []
        for item in source_types or []:
            if item is None:
                continue
            source_type = str(item).strip()
            if source_type and source_type != "all":
                types.append(source_type)
        return types

    def _source_type_filter(self, source_types: Optional[list[str]]) -> list[str]:
        types = []
        for source_type in self._requested_source_types(source_types):
            if source_type in {"note", "mem_note"}:
                for alias in ("mem_note", "note"):
                    if alias not in types:
                        types.append(alias)
                continue
            if source_type in {"atomic", "meta"}:
                continue
            types.append(source_type)
        return types

    def _auto_sync_enabled(self, auto_sync: Optional[bool]) -> bool:
        if auto_sync is not None:
            return bool(auto_sync)
        return bool(getattr(self.cfg, "enable_recall_auto_sync", False))

    async def rebuild(self, source_types: Optional[list[str]] = None, *, embed: bool = True) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "error": "Supabase is not configured."}

        adapters = self._adapter_names(source_types)
        total_docs = 0
        source_counts: dict[str, int] = {}
        errors: dict[str, str] = {}
        for name in adapters:
            try:
                docs = await self._load_documents(name)
                await self._upsert_documents(docs)
                await self._mark_stale_source_deleted(name, docs)
                total_docs += len(docs)
                source_counts[name] = len(docs)
            except Exception as exc:
                errors[name] = str(exc)
        result = {
            "ok": not errors,
            "indexed": total_docs,
            "sources": source_counts,
            "errors": errors,
        }
        if embed and not errors:
            result["embedding"] = await self.embed_pending(limit=500)
        return result

    async def embed_pending(self, limit: int = 200) -> dict[str, Any]:
        if not self.embedding_client or not self.embedding_client.enabled:
            return {"ok": False, "enabled": False, "embedded": 0, "error": "Embedding API is not configured."}
        rows = await self.supabase.query(
            RECALL_INDEX_TABLE,
            {
                "select": "id,embedding_text,embedding_status",
                "deleted_at": "is.null",
                "embedding_status": "in.(pending,failed)",
                "order": "indexed_at.asc",
                "limit": str(max(1, min(int(limit or 200), 1000))),
            },
        )
        embedded = 0
        failed = 0
        for row in rows:
            text = row.get("embedding_text") or ""
            if not text.strip():
                await self.supabase.update(
                    RECALL_INDEX_TABLE,
                    {"id": row.get("id")},
                    {"embedding_status": "skipped", "embedding_error": "empty embedding_text"},
                )
                continue
            vector, error = await self.embedding_client.embed(text)
            if error or vector is None:
                failed += 1
                await self.supabase.update(
                    RECALL_INDEX_TABLE,
                    {"id": row.get("id")},
                    {"embedding_status": "failed", "embedding_error": error or "embedding failed"},
                )
                continue
            embedded += 1
            await self.supabase.update(
                RECALL_INDEX_TABLE,
                {"id": row.get("id")},
                {
                    "embedding": _vector_literal(vector),
                    "embedding_model": self.embedding_client.model,
                    "embedding_status": "ready",
                    "embedding_error": None,
                    "embedded_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return {"ok": failed == 0, "enabled": True, "seen": len(rows), "embedded": embedded, "failed": failed}

    async def _mark_source_deleted(self, source_table: str) -> None:
        await self.supabase.update(
            RECALL_INDEX_TABLE,
            {"source_table": source_table},
            {"deleted_at": datetime.now(timezone.utc).isoformat()},
        )

    async def recall(
        self,
        query: str,
        *,
        source_types: Optional[list[str]] = None,
        session_tag: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_undated: bool = True,
        limit: int = 8,
        auto_sync: Optional[bool] = None,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "query": query, "count": 0, "items": [], "error": "Supabase is not configured."}

        query_text = (query or "").strip()
        tokens = recall_terms(query_text)
        should_auto_sync = self._auto_sync_enabled(auto_sync)
        sync_result = None
        try:
            keyword_rows = await self._query_index(source_types=source_types, query_text=query_text, tokens=tokens)
        except Exception as exc:
            return {
                "ok": False,
                "query": query_text,
                "count": 0,
                "items": [],
                "error": f"recall index table is not ready: {exc}",
                "sync": sync_result,
            }

        vector_rows, _vector_meta = await self._vector_rows(query_text, source_types=source_types)
        rows = self._merge_candidate_rows(keyword_rows, vector_rows)
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
            except Exception as exc:
                return {
                    "ok": False,
                    "query": query_text,
                    "count": 0,
                    "items": [],
                    "error": f"recall index table is not ready: {exc}",
                    "sync": sync_result,
                }
            vector_rows, _vector_meta = await self._vector_rows(query_text, source_types=source_types)
            rows = self._merge_candidate_rows(keyword_rows, vector_rows)

        start_dt = _parse_dt(date_from)
        end_dt = _parse_dt(date_to)
        has_date_filter = bool(start_dt or end_dt)
        scored = []
        for row in rows:
            if not self._row_visible_for_session(row, session_tag):
                continue
            row_dt = _parse_dt(row.get("event_date") or row.get("source_updated_at"))
            if has_date_filter and not row_dt and not include_undated:
                continue
            if start_dt and row_dt and row_dt < start_dt:
                continue
            if end_dt and row_dt and row_dt > end_dt:
                continue
            score, reasons = self._score_row(row, query_text, tokens)
            if tokens and not self._has_direct_match(reasons) and not row.get("_vector_score"):
                continue
            scored.append((score, reasons, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = self._dedupe(scored, max(1, min(int(limit or 8), 30)))
        rows_by_source = self._rows_by_source(rows)
        items = [self._public_item(row, rows_by_source) for _, _, row in selected]
        return {
            "ok": True,
            "count": len(items),
            "items": items,
        }

    async def _vector_rows(self, query: str, source_types: Optional[list[str]] = None) -> tuple[list[dict], dict[str, Any]]:
        if not query.strip():
            return [], {"enabled": False, "used": False, "reason": "empty query"}
        if not self.embedding_client or not self.embedding_client.enabled:
            return [], {"enabled": False, "used": False, "reason": "Embedding API is not configured."}
        vector, error = await self.embedding_client.embed(query)
        if error or vector is None:
            return [], {"enabled": True, "used": False, "error": error or "query embedding failed"}
        types = self._source_type_filter(source_types)
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
        for row in rows:
            row["_vector_score"] = float(row.get("vector_score") or 0.0)
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
            else:
                merged[key] = dict(row)
        return list(merged.values())

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
    ) -> list[dict]:
        types = self._source_type_filter(source_types)
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
                    return rows
            except Exception:
                pass

        params: dict[str, str] = {
            "select": "*",
            "deleted_at": "is.null",
            "order": "importance.desc,event_date.desc,indexed_at.desc",
            "limit": str(candidate_limit),
        }
        if types:
            params["source_type"] = "in.(" + ",".join(types) + ")"
        rows = await self.supabase.query(RECALL_INDEX_TABLE, params)
        if tokens or query_text.strip():
            matched = [row for row in rows if self._row_matches_tokens(row, tokens or [], query_text)]
            return matched or rows
        return rows

    def _score_row(self, row: dict, query: str, tokens: list[str]) -> tuple[float, list[str]]:
        title = (row.get("title") or "").lower()
        search_text = (row.get("search_text") or "").lower()
        row_tokens = {str(item).lower() for item in row.get("search_tokens") or []}
        token_hits = [token for token in tokens if token in row_tokens or token in search_text]
        token_score = len(token_hits) / max(len(tokens), 1) if tokens else 0.15
        title_hits = [token for token in tokens if token in title]
        title_score = min(1.0, len(title_hits) / max(len(tokens), 1) * 1.5) if tokens else 0.0
        tag_text = " ".join(str(item).lower() for item in (row.get("tags_json") or []) + (row.get("entities_json") or []))
        tag_hits = [token for token in tokens if token in tag_text]
        tag_score = min(1.0, len(tag_hits) / max(len(tokens), 1) * 1.4) if tokens else 0.0
        phrase_bonus = 0.18 if query and query.lower() in search_text else 0.0
        keyword_score = min(1.0, token_score + phrase_bonus)
        field_score = min(1.0, title_score * 0.62 + tag_score * 0.38)
        vector_score = max(0.0, min(float(row.get("_vector_score") or 0.0), 1.0))
        importance = self._importance_score(row.get("importance"))
        recency = _recency_score(row.get("event_date") or row.get("source_updated_at"))
        if vector_score > 0:
            score = keyword_score * 0.40 + vector_score * 0.35 + field_score * 0.12 + importance * 0.08 + recency * 0.05
        else:
            score = keyword_score * 0.58 + field_score * 0.22 + importance * 0.10 + recency * 0.10
        reasons = []
        if token_hits:
            reasons.append("keyword:" + ",".join(token_hits[:6]))
        if title_hits:
            reasons.append("title")
        if tag_hits:
            reasons.append("tag/entity")
        if phrase_bonus:
            reasons.append("phrase")
        if vector_score > 0:
            reasons.append("semantic")
        if importance >= 0.75:
            reasons.append("important")
        return min(score, 1.0), reasons or ["soft-recall"]

    def _importance_score(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.5
        if number <= 0:
            return 0.5
        return max(0.0, min(number, 1.0))

    def _has_direct_match(self, reasons: list[str]) -> bool:
        return any(reason.startswith("keyword:") or reason in {"title", "tag/entity", "phrase"} for reason in reasons)

    def _public_item(self, row: dict, rows_by_source: dict[tuple[str, str], list[dict]]) -> dict[str, Any]:
        key = (str(row.get("source_table") or ""), str(row.get("source_id") or ""))
        source_rows = rows_by_source.get(key) or [row]
        content_parts = [item.get("body") or item.get("excerpt") or "" for item in source_rows]
        content = "\n\n".join(part for part in content_parts if part)
        item = {"content": content}
        if row.get("title"):
            item["title"] = row.get("title") or ""
        item["source_type"] = row.get("source_type") or ""
        item["source_table"] = row.get("source_table") or ""
        item["event_date"] = row.get("event_date") or row.get("source_updated_at") or ""
        return item

    async def _mark_stale_source_deleted(self, source_table: str, docs: list[RecallDocument]) -> None:
        live_keys = {(doc.source_id, doc.chunk_index) for doc in docs}
        existing_rows = await self.supabase.query(
            RECALL_INDEX_TABLE,
            {
                "select": "source_id,chunk_index",
                "source_table": f"eq.{source_table}",
                "deleted_at": "is.null",
                "limit": "10000",
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

    def _dedupe(self, scored: list[tuple[float, list[str], dict]], limit: int) -> list[tuple[float, list[str], dict]]:
        selected = []
        counts: dict[tuple[str, str], int] = {}
        for score, reasons, row in scored:
            key = (str(row.get("source_table") or ""), str(row.get("source_id") or ""))
            if counts.get(key, 0) >= 1:
                continue
            counts[key] = counts.get(key, 0) + 1
            selected.append((score, reasons, row))
            if len(selected) >= limit:
                break
        return selected

    def _rows_by_source(self, rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            key = (str(row.get("source_table") or ""), str(row.get("source_id") or ""))
            grouped.setdefault(key, []).append(row)
        for group in grouped.values():
            group.sort(key=lambda item: int(item.get("chunk_index") or 0))
        return grouped

    def _row_visible_for_session(self, row: dict, session_tag: Optional[str]) -> bool:
        visibility = (row.get("visibility") or "").strip().lower()
        row_session = (row.get("session_tag") or "").strip()
        if visibility in {"private", "hidden"}:
            return bool(session_tag and row_session == session_tag)
        if not session_tag:
            return True
        return not row_session or row_session in {session_tag, "default", "shared", "unknown"}

    def _source_weight(self, source_type: str) -> float:
        return {
            "room": 0.92,
            "memory": 0.88,
            "journal": 0.82,
            "calendar": 0.76,
            "mem_note": 0.74,
            "note": 0.74,
            "notebook": 0.68,
            "board": 0.58,
        }.get(source_type or "", 0.5)

    async def _upsert_documents(self, docs: list[RecallDocument]) -> None:
        if not docs:
            return
        existing_hashes = await self._existing_content_hashes(docs[0].source_table)
        rows = []
        for doc in docs:
            row = doc.to_row()
            key = (doc.source_id, doc.chunk_index)
            if existing_hashes.get(key) != doc.content_hash:
                row.update(
                    {
                        "embedding": None,
                        "embedding_model": None,
                        "embedding_status": "pending" if doc.embedding_text else "skipped",
                        "embedding_error": None,
                        "embedded_at": None,
                    }
                )
            rows.append(row)
        if hasattr(self.supabase, "upsert"):
            for start in range(0, len(rows), 100):
                await self.supabase.upsert(
                    RECALL_INDEX_TABLE,
                    rows[start : start + 100],
                    on_conflict="source_table,source_id,chunk_index",
                )
            return

        for row in rows:
            match = {
                "source_table": row["source_table"],
                "source_id": row["source_id"],
                "chunk_index": row["chunk_index"],
            }
            updated = await self.supabase.update(RECALL_INDEX_TABLE, match, row)
            if not updated:
                await self.supabase.insert(RECALL_INDEX_TABLE, row)

    async def _existing_content_hashes(self, source_table: str) -> dict[tuple[str, int], str]:
        rows = await self.supabase.query(
            RECALL_INDEX_TABLE,
            {
                "select": "source_id,chunk_index,content_hash",
                "source_table": f"eq.{source_table}",
                "limit": "5000",
            },
        )
        hashes: dict[tuple[str, int], str] = {}
        for row in rows:
            hashes[(str(row.get("source_id") or ""), int(row.get("chunk_index") or 0))] = str(row.get("content_hash") or "")
        return hashes

    def _adapter_names(self, source_types: Optional[list[str]] = None) -> list[str]:
        mapping = {
            "journal": "journal",
            "room": "room",
            "board": "message_board",
            "message_board": "message_board",
            "memory": "memories",
            "memories": "memories",
            "calendar": "calendar_pages",
            "mem_note": "shenyu_mem_notes",
            "notebook": "shenyu_notebook",
        }
        requested = self._requested_source_types(source_types)
        if not requested:
            return [
                "journal",
                "room",
                "message_board",
                "memories",
                "calendar_pages",
                "shenyu_mem_notes",
                "shenyu_notebook",
            ]
        names = []
        for source_type in requested:
            mapped = mapping.get(str(source_type).strip())
            if mapped and mapped not in names:
                names.append(mapped)
        return names

    async def _load_documents(self, source_table: str) -> list[RecallDocument]:
        loaders = {
            "journal": self._load_journal,
            "room": self._load_room,
            "message_board": self._load_message_board,
            "memories": self._load_memories,
            "calendar_pages": self._load_calendar_pages,
            "shenyu_mem_notes": self._load_mem_notes,
            "atomic_memories": self._load_atomic_memories,
            "shenyu_notebook": self._load_notebook,
            "meta_summaries": self._load_meta_summaries,
        }
        return await loaders[source_table]()

    async def _load_journal(self) -> list[RecallDocument]:
        rows = await self.supabase.query(
            "journal",
            {"select": "*", "order": "updated_at.desc", "limit": "1000"},
        )
        docs = []
        for row in rows:
            tags = [row.get("category"), row.get("mood"), row.get("author"), "favorited" if row.get("is_favorited") else ""]
            docs.extend(
                _make_documents(
                    source_table="journal",
                    source_id=row.get("id"),
                    source_type="journal",
                    title=row.get("title"),
                    body=row.get("content"),
                    session_tag=row.get("session_tag"),
                    tags=tags,
                    metadata={"category": row.get("category"), "mood": row.get("mood"), "temperature": row.get("temperature")},
                    event_date=row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status="active",
                    importance=0.85 if row.get("is_favorited") else 0.65,
                )
            )
        return docs

    async def _load_room(self) -> list[RecallDocument]:
        rows = await self.supabase.query("room", {"select": "*", "order": "updated_at.desc", "limit": "1000"})
        docs = []
        for row in rows:
            tags = _json_list(row.get("tags")) + [row.get("mood")]
            docs.extend(
                _make_documents(
                    source_table="room",
                    source_id=row.get("id"),
                    source_type="room",
                    title=row.get("title") or "room",
                    body=row.get("content"),
                    session_tag=row.get("session_tag"),
                    tags=tags,
                    metadata={"mood": row.get("mood")},
                    event_date=row.get("updated_at") or row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    visibility=row.get("visibility"),
                    importance=0.9,
                )
            )
        return docs

    async def _load_message_board(self) -> list[RecallDocument]:
        rows = await self.supabase.query("message_board", {"select": "*", "order": "created_at.desc", "limit": "1000"})
        docs = []
        for row in rows:
            docs.extend(
                _make_documents(
                    source_table="message_board",
                    source_id=row.get("id"),
                    source_type="board",
                    title=f"Message from {row.get('sender') or 'unknown'}",
                    body=row.get("content"),
                    tags=[row.get("sender")],
                    event_date=row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("created_at"),
                    status="active",
                    importance=0.55,
                    chunk=False,
                )
            )
        return docs

    async def _load_memories(self) -> list[RecallDocument]:
        rows = await self.supabase.query(
            "memories",
            {"select": "*", "is_deleted": "eq.false", "order": "weight.desc,date.desc", "limit": "1000"},
        )
        tag_rows = await self.supabase.query("memory_tags", {"select": "memory_id,tag,tag_type", "limit": "5000"})
        tags_by_memory: dict[str, list[str]] = {}
        entities_by_memory: dict[str, list[str]] = {}
        for tag in tag_rows:
            memory_id = str(tag.get("memory_id"))
            target = entities_by_memory if str(tag.get("tag_type") or "").lower() == "entity" else tags_by_memory
            target.setdefault(memory_id, []).append(tag.get("tag"))
        docs = []
        for row in rows:
            memory_id = str(row.get("id"))
            body = "\n\n".join(
                part
                for part in [
                    row.get("summary"),
                    row.get("facts"),
                    row.get("emotional_context"),
                    row.get("detailed_content"),
                ]
                if part
            )
            tags = _json_list(row.get("emotions")) + _json_list(row.get("type")) + tags_by_memory.get(memory_id, [])
            weight = float(row.get("weight") or 1.0)
            importance = min(1.0, (float(row.get("importance") or 3) / 5.0) * 0.65 + min(weight / 2.0, 0.35))
            docs.extend(
                _make_documents(
                    source_table="memories",
                    source_id=memory_id,
                    source_type="memory",
                    title=row.get("title"),
                    body=body,
                    session_tag=row.get("session_tag"),
                    tags=tags,
                    entities=entities_by_memory.get(memory_id, []),
                    metadata={"type": row.get("type"), "emotions": row.get("emotions"), "source_model": row.get("source_model")},
                    event_date=row.get("date"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at") or row.get("last_activated"),
                    status="active",
                    importance=importance,
                )
            )
        return docs

    async def _load_calendar_pages(self) -> list[RecallDocument]:
        rows = await self.supabase.query(
            "calendar_pages",
            {"select": "*", "is_latest": "eq.true", "status": "eq.final", "order": "period_start.desc", "limit": "1000"},
        )
        docs = []
        for row in rows:
            body = "\n\n".join(part for part in [row.get("summary"), row.get("digest"), row.get("content")] if part)
            docs.extend(
                _make_documents(
                    source_table="calendar_pages",
                    source_id=row.get("id"),
                    source_type="calendar",
                    title=row.get("title") or row.get("period_key"),
                    body=body,
                    tags=[row.get("period_type"), row.get("period_key"), row.get("author")],
                    metadata={
                        "period_type": row.get("period_type"),
                        "period_key": row.get("period_key"),
                        "period_end": row.get("period_end"),
                        "source_refs": row.get("source_refs"),
                        "session_tags": row.get("session_tags"),
                    },
                    event_date=row.get("period_start"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    importance=0.76,
                )
            )
        return docs

    async def _load_mem_notes(self) -> list[RecallDocument]:
        rows = await self.supabase.query("shenyu_mem_notes", {"select": "*", "order": "updated_at.desc", "limit": "1000"})
        status_weight = {"active": 0.82, "captured": 0.64, "paused": 0.42, "archived": 0.25}
        docs = []
        for row in rows:
            keywords = _json_list(row.get("trigger_keywords"))
            body = "\n\n".join(part for part in [row.get("content"), row.get("trigger_text"), " ".join(keywords), row.get("review_note")] if part)
            docs.extend(
                _make_documents(
                    source_table="shenyu_mem_notes",
                    source_id=row.get("id"),
                    source_type="mem_note",
                    title=row.get("mem_type") or _shorten(row.get("content") or "", 60),
                    body=body,
                    session_tag=row.get("session_tag"),
                    tags=[row.get("mem_type")] + keywords,
                    metadata={"trigger_count": row.get("trigger_count"), "source_model": row.get("source_model")},
                    event_date=row.get("updated_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    importance=status_weight.get(row.get("status"), 0.5),
                    chunk=False,
                )
            )
        return docs

    async def _load_atomic_memories(self) -> list[RecallDocument]:
        rows = await self.supabase.query(
            "atomic_memories",
            {"select": "*", "status": "eq.active", "order": "heat.desc,importance.desc,updated_at.desc", "limit": "1000"},
        )
        docs = []
        for row in rows:
            tags = _json_list(row.get("tags_json")) + [row.get("memory_type"), row.get("owner"), row.get("applies_to")]
            body = "\n\n".join(part for part in [row.get("content_surface"), row.get("quote"), row.get("source_excerpt")] if part)
            importance = min(1.0, float(row.get("importance") or 3) / 5.0 * 0.55 + float(row.get("heat") or 0.5) * 0.45)
            docs.extend(
                _make_documents(
                    source_table="atomic_memories",
                    source_id=row.get("id"),
                    source_type="atomic",
                    title=" ".join(part for part in [row.get("subject"), row.get("memory_type"), row.get("time_hint")] if part),
                    body=body,
                    session_tag=row.get("session_tag"),
                    tags=tags,
                    entities=_json_list(row.get("entities_json")),
                    metadata={"tier": row.get("tier"), "speaker_perspective": row.get("speaker_perspective")},
                    event_date=row.get("valid_from") or row.get("created_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    importance=importance,
                    chunk=False,
                )
            )
        return docs

    async def _load_notebook(self) -> list[RecallDocument]:
        rows = await self.supabase.query("shenyu_notebook", {"select": "*", "order": "updated_at.desc", "limit": "1000"})
        docs = []
        for row in rows:
            docs.extend(
                _make_documents(
                    source_table="shenyu_notebook",
                    source_id=row.get("id"),
                    source_type="notebook",
                    title=f"{row.get('type') or 'note'}{' pinned' if row.get('pinned') else ''}",
                    body=row.get("content"),
                    session_tag=row.get("session_tag"),
                    tags=_json_list(row.get("tags")) + [row.get("type")],
                    metadata=row.get("metadata"),
                    event_date=row.get("updated_at"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    status=row.get("status"),
                    importance=0.9 if row.get("pinned") else 0.65,
                )
            )
        return docs

    async def _load_meta_summaries(self) -> list[RecallDocument]:
        rows = await self.supabase.query(
            "meta_summaries",
            {"select": "*", "is_active": "eq.true", "order": "priority.desc,last_updated.desc", "limit": "1000"},
        )
        docs = []
        for row in rows:
            docs.extend(
                _make_documents(
                    source_table="meta_summaries",
                    source_id=row.get("id"),
                    source_type="meta",
                    title=row.get("title"),
                    body=row.get("content"),
                    session_tag=row.get("session_tag"),
                    tags=[row.get("category")],
                    metadata={"category": row.get("category"), "source_model": row.get("source_model")},
                    event_date=row.get("last_updated"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("last_updated"),
                    status="active" if row.get("is_active") else "inactive",
                    importance=min(1.0, float(row.get("priority") or 1) / 5.0),
                )
            )
        return docs
