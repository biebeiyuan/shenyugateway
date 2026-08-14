from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_UNSET = object()


WINDOWSILL_TABLE = "windowsill"
WINDOWSILL_ORIGIN_NORMAL = "normal"
WINDOWSILL_ORIGIN_ROOM = "room"
WINDOWSILL_ORIGINS = frozenset({WINDOWSILL_ORIGIN_NORMAL, WINDOWSILL_ORIGIN_ROOM})


@dataclass
class GatewayToolRuntime:
    cfg: Any = None
    supabase_client: Any = None
    session_store: Any = None


_runtime = GatewayToolRuntime()


def configure_gateway_tools(*, runtime_config: Any = _UNSET, supabase: Any = _UNSET, store: Any = _UNSET) -> None:
    """Inject gateway runtime dependencies without importing gateway.py back into this module."""
    if runtime_config is not _UNSET:
        _runtime.cfg = runtime_config
    if supabase is not _UNSET:
        _runtime.supabase_client = supabase
    if store is not _UNSET:
        _runtime.session_store = store


def get_runtime() -> GatewayToolRuntime:
    """Public accessor for the shared runtime singleton (do not re-instantiate it)."""
    return _runtime
