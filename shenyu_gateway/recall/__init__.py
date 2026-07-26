from __future__ import annotations

from ._base import (
    DEFAULT_RECALL_CANDIDATE_LIMIT,
    DEFAULT_RECALL_LIMIT,
    MAX_RECALL_LIMIT,
    PUBLIC_RECALL_SOURCE_TYPES,
    RECALL_INDEX_TABLE,
    RECALL_SYNC_PAGE_SIZE,
    RecallServiceBase,
)
from ._documents import RecallDocument
from ._embedding import EmbeddingMixin
from ._query import QueryMixin
from ._ranking import RankingMixin
from ._sources import SourcesMixin
from ._text import (
    EMBEDDING_TEXT_MAX_CHARS,
    RECALL_CHUNK_MAX_CHARS,
    RECALL_CHUNK_MIN_CHARS,
    RECALL_EXCERPT_MAX_CHARS,
    RECALL_MODES,
    _mem_note_keyword_anchor_is_specific,
    _recency_score,
    _vector_literal,
    build_embedding_text,
    classify_recall_mode,
    infer_recall_date,
    is_generic_chinese_fragment,
    normalize_recall_title,
    recall_terms,
    split_recall_chunks,
)


class RecallIndexService(
    QueryMixin,
    RankingMixin,
    SourcesMixin,
    EmbeddingMixin,
    RecallServiceBase,
):
    pass


__all__ = [
    "DEFAULT_RECALL_CANDIDATE_LIMIT",
    "DEFAULT_RECALL_LIMIT",
    "EMBEDDING_TEXT_MAX_CHARS",
    "MAX_RECALL_LIMIT",
    "PUBLIC_RECALL_SOURCE_TYPES",
    "RECALL_CHUNK_MAX_CHARS",
    "RECALL_CHUNK_MIN_CHARS",
    "RECALL_EXCERPT_MAX_CHARS",
    "RECALL_INDEX_TABLE",
    "RECALL_MODES",
    "RECALL_SYNC_PAGE_SIZE",
    "RecallDocument",
    "RecallIndexService",
    "build_embedding_text",
    "classify_recall_mode",
    "infer_recall_date",
    "is_generic_chinese_fragment",
    "normalize_recall_title",
    "recall_terms",
    "split_recall_chunks",
]
