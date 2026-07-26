from __future__ import annotations

from ._base import GatewayToolServiceBase
from ._books import BooksToolsMixin
from ._calendar import CalendarToolsMixin
from ._compat import CompatToolsMixin
from ._mem_notes import MemNoteToolsMixin
from ._notebook import NotebookToolsMixin
from ._recall import RecallToolsMixin
from ._runtime import (
    WINDOWSILL_TABLE,
    GatewayToolRuntime,
    _UNSET,
    _is_hisense_client,
    _is_hisense_session,
    _runtime,
    configure_gateway_tools,
    get_runtime,
)
from ._sessions import SessionToolsMixin
from ._stars import StarToolsMixin
from ._supabase import SupabaseToolsMixin
from ._windowsill import WindowsillToolsMixin


class GatewayToolService(
    SupabaseToolsMixin,
    RecallToolsMixin,
    MemNoteToolsMixin,
    StarToolsMixin,
    BooksToolsMixin,
    CalendarToolsMixin,
    SessionToolsMixin,
    WindowsillToolsMixin,
    NotebookToolsMixin,
    CompatToolsMixin,
    GatewayToolServiceBase,
):
    pass


__all__ = [
    "GatewayToolRuntime",
    "GatewayToolService",
    "WINDOWSILL_TABLE",
    "configure_gateway_tools",
    "get_runtime",
]
