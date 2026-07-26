from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


_UNSET = object()


WINDOWSILL_TABLE = "windowsill"


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


def _is_hisense_client(client_name: Optional[str], runtime_config: Any = None) -> bool:
    active_cfg = runtime_config or _runtime.cfg
    target = (getattr(active_cfg, "hisense_client_name", "") or "").strip()
    name = (client_name or "").strip()
    if not target or not name:
        return False
    if name.casefold() == target.casefold():
        return True
    return target.casefold() == "hisense" and name == "海信"


def _is_hisense_session(session: Optional[dict], runtime_config: Any = None) -> bool:
    return bool(session) and _is_hisense_client(session.get("client_name"), runtime_config=runtime_config)
