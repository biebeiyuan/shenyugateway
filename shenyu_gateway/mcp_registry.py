"""Gateway-side MCP client registry.

The gateway acts as an MCP *client* toward a configurable list of external
MCP servers (streamable HTTP or SSE). Remote tools are exposed to the model
as top-level function tools named ``mcp_<server>_<tool>`` and executed inside
the internal tool loop like gateway-native tools.

Design constraints (docs/history/MCP_INTEGRATION_2026-08-13.md):

- The chat path must never 500 because an MCP server is down. Every network
  operation is bounded by a timeout and failures degrade to an error tool
  result or a stale/empty tool list.
- ``merge_tools`` is synchronous, so it only reads an in-memory snapshot.
  The async refresh happens in ``prepare_messages`` (first load awaited,
  stale snapshots refreshed in the background).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from .runtime import iso_now, logger

MCP_TOOL_PREFIX = "mcp_"

_SERVER_NAME_RE = re.compile(r"^[a-z0-9_]{1,24}$")
_SANITIZE_RE = re.compile(r"[^a-z0-9_]+")

_VALID_TRANSPORTS = {"auto", "sse"}


def validate_mcp_servers(raw: Any) -> list[dict[str, Any]]:
    """Validate a server list; raises ValueError with an owner-readable reason."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCP_SERVERS 必须是 JSON 数组：{exc}") from exc
    if not isinstance(raw, list):
        raise ValueError("MCP_SERVERS 必须是 JSON 数组。")
    servers: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"MCP_SERVERS[{index}] 必须是对象。")
        name = str(item.get("name") or "").strip().lower()
        if not _SERVER_NAME_RE.match(name):
            raise ValueError(
                f"MCP_SERVERS[{index}].name 必须匹配 [a-z0-9_]{{1,24}}，收到 {item.get('name')!r}。"
            )
        if name in seen_names:
            raise ValueError(f"MCP server 名称重复：{name}")
        seen_names.add(name)
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"MCP_SERVERS[{index}].url 必须以 http:// 或 https:// 开头。")
        transport = str(item.get("transport") or "auto").strip().lower()
        if transport not in _VALID_TRANSPORTS:
            raise ValueError(f"MCP_SERVERS[{index}].transport 必须是 auto 或 sse。")
        raw_headers = item.get("headers") or {}
        if not isinstance(raw_headers, dict):
            raise ValueError(f"MCP_SERVERS[{index}].headers 必须是对象。")
        headers = {str(k).strip(): str(v) for k, v in raw_headers.items() if str(k).strip()}
        servers.append(
            {
                "name": name,
                "url": url,
                "transport": transport,
                "headers": headers,
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return servers


def _sanitize_tool_name(name: str) -> str:
    cleaned = _SANITIZE_RE.sub("_", str(name or "").strip().lower()).strip("_")
    return cleaned or "tool"


def _mcp_enabled(cfg: Any) -> bool:
    return bool(getattr(cfg, "enable_upstream_tools", True)) and bool(
        getattr(cfg, "enable_mcp_tools", True)
    )


def _enabled_servers(cfg: Any) -> list[dict[str, Any]]:
    servers = getattr(cfg, "mcp_servers", None) or []
    return [s for s in servers if isinstance(s, dict) and s.get("enabled", True)]


@asynccontextmanager
async def _streamable_http_with_headers(url: str, headers: dict[str, str]):
    """streamable_http_client does not manage the lifecycle of an externally
    provided http_client, so close the httpx client ourselves."""
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    async with create_mcp_http_client(headers=headers) as http_client:
        async with streamable_http_client(url, http_client=http_client) as streams:
            yield streams


def _build_client(server: dict[str, Any], *, read_timeout_seconds: float):
    """Build an SDK Client for one server entry. Imports the SDK lazily so the
    gateway still boots when the optional dependency is missing."""
    from mcp import Client

    url = server["url"]
    headers = server.get("headers") or {}
    if server.get("transport") == "sse":
        from mcp.client.sse import sse_client

        transport = sse_client(url, headers=headers or None)
        return Client(transport, read_timeout_seconds=read_timeout_seconds)
    if headers:
        return Client(
            _streamable_http_with_headers(url, headers),
            read_timeout_seconds=read_timeout_seconds,
        )
    return Client(url, read_timeout_seconds=read_timeout_seconds)


def _normalize_call_result(res: Any) -> dict[str, Any]:
    texts: list[str] = []
    other_blocks = 0
    for block in getattr(res, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            texts.append(text)
        else:
            other_blocks += 1
    joined = "\n".join(texts)
    if getattr(res, "is_error", False):
        return {
            "ok": False,
            "error": joined or "MCP tool returned an error without a message.",
            "error_kind": "mcp_tool_error",
        }
    result: dict[str, Any] = {"ok": True}
    structured = getattr(res, "structured_content", None)
    if structured is not None:
        result["result"] = structured
        if joined and joined != json.dumps(structured, ensure_ascii=False):
            result["text"] = joined
    else:
        result["result"] = joined
    if other_blocks:
        result["non_text_blocks"] = other_blocks
    return result


class McpToolRegistry:
    """In-memory snapshot of remote MCP tools plus per-server health."""

    def __init__(self) -> None:
        # exposed name -> {"server", "tool", "spec"}
        self._tools: dict[str, dict[str, Any]] = {}
        self._status: dict[str, dict[str, Any]] = {}
        self._refreshed_at: float = 0.0
        self._refresh_lock = asyncio.Lock()
        self._background_refresh: Optional[asyncio.Task] = None

    # -- snapshot readers (sync, used by merge_tools / routes) ---------------

    def tools_for_merge(self, cfg: Any) -> list[dict[str, Any]]:
        if not _mcp_enabled(cfg):
            return []
        enabled_names = {s["name"] for s in _enabled_servers(cfg)}
        return [
            entry["spec"]
            for entry in self._tools.values()
            if entry["server"] in enabled_names
        ]

    def status(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._status.values()]

    def tool_summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "name": exposed,
                "server": entry["server"],
                "remote_name": entry["tool"],
                "description": entry["spec"].get("function", {}).get("description", ""),
            }
            for exposed, entry in sorted(self._tools.items())
        ]

    def invalidate(self) -> None:
        self._refreshed_at = 0.0

    # -- refresh --------------------------------------------------------------

    async def ensure_fresh(self, cfg: Any) -> None:
        """TTL-gated refresh. Never raises; never blocks longer than one
        list round when a snapshot already exists."""
        if not _mcp_enabled(cfg) or not _enabled_servers(cfg):
            return
        ttl = max(int(getattr(cfg, "mcp_tools_cache_seconds", 300) or 300), 10)
        age = time.monotonic() - self._refreshed_at
        if self._refreshed_at and age < ttl:
            return
        if self._refreshed_at:
            # Stale but usable snapshot: refresh in the background so the
            # chat request keeps its latency.
            if self._background_refresh is None or self._background_refresh.done():
                self._background_refresh = asyncio.create_task(self._refresh_quietly(cfg))
            return
        try:
            await self.refresh(cfg)
        except Exception:
            logger.exception("[MCP] initial tool refresh failed")

    async def _refresh_quietly(self, cfg: Any) -> None:
        try:
            await self.refresh(cfg)
        except Exception:
            logger.exception("[MCP] background tool refresh failed")

    async def refresh(self, cfg: Any) -> list[dict[str, Any]]:
        """Reload the tool list of every enabled server. Per-server failures
        are recorded in status, not raised."""
        async with self._refresh_lock:
            servers = _enabled_servers(cfg)
            list_timeout = max(int(getattr(cfg, "mcp_list_timeout_seconds", 10) or 10), 2)
            outcomes = await asyncio.gather(
                *(self._list_server(server, list_timeout) for server in servers)
            )
            tools: dict[str, dict[str, Any]] = {}
            status: dict[str, dict[str, Any]] = {}
            for server, (remote_tools, error) in zip(servers, outcomes):
                name = server["name"]
                status[name] = {
                    "name": name,
                    "url": server["url"],
                    "transport": server.get("transport", "auto"),
                    "ok": error is None,
                    "error": error,
                    "tool_count": len(remote_tools or []),
                    "checked_at": iso_now(),
                }
                for remote in remote_tools or []:
                    exposed = f"{MCP_TOOL_PREFIX}{name}_{_sanitize_tool_name(remote['name'])}"
                    suffix = 2
                    while exposed in tools:
                        exposed = f"{MCP_TOOL_PREFIX}{name}_{_sanitize_tool_name(remote['name'])}_{suffix}"
                        suffix += 1
                    tools[exposed] = {
                        "server": name,
                        "tool": remote["name"],
                        "spec": {
                            "type": "function",
                            "function": {
                                "name": exposed,
                                "description": remote.get("description") or "",
                                "parameters": remote.get("input_schema")
                                or {"type": "object", "properties": {}},
                            },
                        },
                    }
            self._tools = tools
            self._status = status
            self._refreshed_at = time.monotonic()
            failed = [s for s in status.values() if not s["ok"]]
            logger.info(
                "[MCP] refreshed %d tools from %d servers (%d failed)",
                len(tools),
                len(servers),
                len(failed),
            )
            return self.status()

    async def _list_server(
        self, server: dict[str, Any], timeout_seconds: int
    ) -> tuple[Optional[list[dict[str, Any]]], Optional[str]]:
        try:
            async with asyncio.timeout(timeout_seconds):
                client = _build_client(server, read_timeout_seconds=float(timeout_seconds))
                async with client:
                    listed = await client.list_tools()
            remote_tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.input_schema,
                }
                for tool in listed.tools
            ]
            return remote_tools, None
        except TimeoutError:
            return None, f"list_tools 超时（{timeout_seconds}s）"
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    # -- execution -------------------------------------------------------------

    async def execute(self, name: str, arguments: dict, *, cfg: Any) -> dict[str, Any]:
        if not _mcp_enabled(cfg):
            return {"ok": False, "error": "MCP tools are disabled.", "error_kind": "validation"}
        entry = self._tools.get(name)
        if entry is None:
            # The config may have changed since the snapshot was taken.
            try:
                await self.refresh(cfg)
            except Exception:
                logger.exception("[MCP] refresh during execute failed")
            entry = self._tools.get(name)
        if entry is None:
            return {
                "ok": False,
                "error": f"Unknown MCP tool: {name}",
                "error_kind": "validation",
                "available_tools": sorted(self._tools),
            }
        server = next(
            (s for s in _enabled_servers(cfg) if s["name"] == entry["server"]),
            None,
        )
        if server is None:
            return {
                "ok": False,
                "error": f"MCP server {entry['server']} is disabled or removed.",
                "error_kind": "validation",
            }
        timeout_seconds = max(int(getattr(cfg, "mcp_call_timeout_seconds", 60) or 60), 5)
        arguments = arguments if isinstance(arguments, dict) else {}
        try:
            async with asyncio.timeout(timeout_seconds):
                client = _build_client(server, read_timeout_seconds=float(timeout_seconds))
                async with client:
                    raw = await client.call_tool(entry["tool"], arguments)
        except TimeoutError:
            return {
                "ok": False,
                "error": f"MCP 调用超时（{timeout_seconds}s）：{entry['server']}/{entry['tool']}",
                "error_kind": "timeout",
            }
        except Exception as exc:
            logger.warning("[MCP] call failed server=%s tool=%s: %s", entry["server"], entry["tool"], exc)
            return {
                "ok": False,
                "error": f"MCP 调用失败（{entry['server']}）：{type(exc).__name__}: {exc}",
                "error_kind": "mcp_connection",
            }
        return _normalize_call_result(raw)

    async def test_server(self, server: dict[str, Any], *, cfg: Any) -> dict[str, Any]:
        """One-off probe used by /api/mcp/test; does not touch the snapshot."""
        list_timeout = max(int(getattr(cfg, "mcp_list_timeout_seconds", 10) or 10), 2)
        remote_tools, error = await self._list_server(server, list_timeout)
        if error is not None:
            return {"ok": False, "error": error}
        return {
            "ok": True,
            "tool_count": len(remote_tools or []),
            "tools": [tool["name"] for tool in remote_tools or []],
        }


registry = McpToolRegistry()
