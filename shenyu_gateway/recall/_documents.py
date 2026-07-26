from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Optional

from shenyu_gateway.utils import normalize_text as _normalize_text

from ._text import _iso_dt, _json_dict, _json_list, _shorten, build_embedding_text, recall_terms, split_recall_chunks


def _content_hash(parts: list[Any]) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    metadata_text = _normalize_text(metadata_obj) if metadata_obj else ""
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
                metadata_text,
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
