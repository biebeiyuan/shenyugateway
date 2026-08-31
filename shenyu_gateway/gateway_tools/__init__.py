from __future__ import annotations

from ._album import ALBUM_NOTES_TABLE, AlbumToolsMixin, latest_turn_images
from ._base import GatewayToolServiceBase
from ._books import BooksToolsMixin
from ._calendar import CalendarToolsMixin
from ._mem_notes import MemNoteToolsMixin
from ._notebook import NotebookToolsMixin
from ._orchard import OrchardToolsMixin
from ._recall import RecallToolsMixin

# Re-exporting the `_runtime` singleton shadows the `._runtime` submodule as a
# package attribute, and each mixin module holds its own binding of these names,
# so string-path monkeypatching "shenyu_gateway.gateway_tools.<name>" does not
# reach the implementations. Patch the defining submodule (via sys.modules) or
# inject dependencies through configure_gateway_tools / constructor arguments.
from ._runtime import (
    WINDOWSILL_ORIGIN_NORMAL,
    WINDOWSILL_ORIGIN_ROOM,
    WINDOWSILL_TABLE,
    GatewayToolRuntime,
    _UNSET,
    _runtime,
    configure_gateway_tools,
    get_runtime,
)
from ._sessions import SessionToolsMixin
from ._stars import StarToolsMixin
from ._supabase import SupabaseToolsMixin
from ._web import WebToolsMixin
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
    AlbumToolsMixin,
    OrchardToolsMixin,
    WebToolsMixin,
    GatewayToolServiceBase,
):
    pass


__all__ = [
    "ALBUM_NOTES_TABLE",
    "GatewayToolRuntime",
    "GatewayToolService",
    "OrchardToolsMixin",
    "latest_turn_images",
    "WINDOWSILL_ORIGIN_NORMAL",
    "WINDOWSILL_ORIGIN_ROOM",
    "WINDOWSILL_TABLE",
    "configure_gateway_tools",
    "get_runtime",
]
