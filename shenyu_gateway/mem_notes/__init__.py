from __future__ import annotations

from ._helpers import (
    MEM_NOTE_BULK_UPDATE_MAX,
    MEM_NOTE_MEMORY_KIND_ALIASES,
    MEM_NOTE_MEMORY_KINDS,
    MEM_NOTE_PATCH_FIELDS,
    MEM_NOTE_STATUSES,
    MEM_NOTE_TYPES,
)
from ._validation import ValidationMixin
from ._suggestions import SuggestionsMixin
from ._search import SearchMixin
from ._crud import CrudMixin

# Re-export symbols that external code imports from shenyu_gateway.mem_notes
from ..mem_notes_relevance import (
    _clean_context_query,
    running_joke_serendipity_rate,
)


class MemNoteService(
    SearchMixin,
    CrudMixin,
    SuggestionsMixin,
    ValidationMixin,
):
    def __init__(self, cfg, supabase_client):
        self.cfg = cfg
        self.supabase = supabase_client


__all__ = [
    "MemNoteService",
    "MEM_NOTE_TYPES",
    "MEM_NOTE_STATUSES",
    "MEM_NOTE_MEMORY_KINDS",
    "MEM_NOTE_MEMORY_KIND_ALIASES",
    "MEM_NOTE_PATCH_FIELDS",
    "MEM_NOTE_BULK_UPDATE_MAX",
    # backward compat re-exports
    "_clean_context_query",
    "running_joke_serendipity_rate",
]
