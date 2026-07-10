from __future__ import annotations

from ._base import (
    HEARTBEAT_ENTRIES_TABLE,
    HISENSE_HEARTBEAT_TABLE,
    NEXT_REQUEST_COLD_START_TAG,
    BaseStoreMixin,
)
from ._sessions import SessionsMixin
from ._messages import MessagesMixin
from ._pending import PendingTurnsMixin
from ._snapshots import SnapshotsMixin
from ._window_state import WindowStateMixin
from ._cold_start import ColdStartMixin
from ._heartbeats import HeartbeatsMixin
from ._cache import CacheMixin
from ._room import RoomMixin
from ._admin import AdminMixin


class GatewayStore(
    SessionsMixin,
    MessagesMixin,
    PendingTurnsMixin,
    SnapshotsMixin,
    WindowStateMixin,
    ColdStartMixin,
    HeartbeatsMixin,
    CacheMixin,
    RoomMixin,
    AdminMixin,
    BaseStoreMixin,
):
    pass


__all__ = [
    "GatewayStore",
    "NEXT_REQUEST_COLD_START_TAG",
    "HEARTBEAT_ENTRIES_TABLE",
    "HISENSE_HEARTBEAT_TABLE",
]
