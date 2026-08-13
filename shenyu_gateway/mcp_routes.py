from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from .mcp_registry import registry, validate_mcp_servers
from .runtime import mask


@dataclass(frozen=True)
class McpRouteDeps:
    cfg: Any
    persist_env: Callable[[dict[str, Any]], None]


def _masked_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**server, "headers": {key: mask(value) for key, value in (server.get("headers") or {}).items()}}
        for server in servers
    ]


def _is_masked(value: str) -> bool:
    return "****" in value


def _restore_masked_headers(
    servers: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """A header value that still carries the mask placeholder means the admin
    UI echoed the masked read-back; keep the stored secret for that key."""
    current_by_name = {s.get("name"): s for s in current if isinstance(s, dict)}
    for server in servers:
        old = current_by_name.get(server["name"])
        if not old:
            continue
        old_headers = old.get("headers") or {}
        for key, value in list(server["headers"].items()):
            if _is_masked(value) and key in old_headers:
                server["headers"][key] = old_headers[key]
    return servers


def build_mcp_router(deps: McpRouteDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/mcp/servers")
    async def list_servers():
        return {
            "servers": _masked_servers(deps.cfg.mcp_servers),
            "status": registry.status(),
            "tools": registry.tool_summaries(),
        }

    @router.post("/api/mcp/servers")
    async def replace_servers(body: list[dict[str, Any]]):
        try:
            servers = validate_mcp_servers(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        servers = _restore_masked_headers(servers, deps.cfg.mcp_servers)
        deps.cfg.mcp_servers = servers
        deps.persist_env({"MCP_SERVERS": json.dumps(servers, ensure_ascii=False)})
        registry.invalidate()
        return {"ok": True, "servers": _masked_servers(servers)}

    @router.post("/api/mcp/refresh")
    async def refresh_tools():
        status = await registry.refresh(deps.cfg)
        return {"ok": True, "status": status, "tools": registry.tool_summaries()}

    @router.post("/api/mcp/test")
    async def test_server(body: dict[str, Any]):
        try:
            servers = validate_mcp_servers([body])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        server = _restore_masked_headers(servers, deps.cfg.mcp_servers)[0]
        return await registry.test_server(server, cfg=deps.cfg)

    return router
