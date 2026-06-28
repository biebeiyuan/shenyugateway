from __future__ import annotations

import asyncio
import os
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .request_logs import (
    _finish_http_request_event,
    _start_http_request_event,
)
from .runtime import iso_now as _iso_now, logger


def register_middlewares(app: FastAPI, cfg) -> None:
    @app.exception_handler(Exception)
    async def _global_exc_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "shenyu_request_id", None) or uuid.uuid4().hex[:8]
        if not getattr(request.state, "shenyu_error_logged", False):
            logger.exception("Unhandled exception request_id=%s for %s %s", request_id, request.method, request.url.path)
        content = {"error": "Internal Server Error", "request_id": request_id}
        if os.getenv("DEBUG_TRACEBACKS", "").strip().lower() in {"1", "true", "yes", "on"}:
            import traceback as _tb

            content["detail"] = str(exc)
            content["traceback"] = _tb.format_exc()
        return JSONResponse(status_code=500, content=content)

    @app.middleware("http")
    async def log_unhandled_exceptions(request: Request, call_next):
        request_id = uuid.uuid4().hex[:8]
        request.state.shenyu_request_id = request_id
        track_chat_request = request.url.path == "/v1/chat/completions"
        started_at = asyncio.get_running_loop().time()
        if track_chat_request:
            client_host = request.client.host if request.client else ""
            _start_http_request_event(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                client=client_host,
                session_tag=request.headers.get("X-Shenyu-Session-Tag") or request.headers.get("X-Session-Tag") or "",
                client_name=request.headers.get("X-Shenyu-Client") or request.headers.get("X-Client-Name") or "",
                now_iso=_iso_now(),
            )
        try:
            response = await call_next(request)
            response.headers["X-Shenyu-Request-Id"] = request_id
            if track_chat_request:
                _finish_http_request_event(
                    request_id=request_id,
                    now_iso=_iso_now(),
                    duration_ms=int((asyncio.get_running_loop().time() - started_at) * 1000),
                    http_status=response.status_code,
                )
            return response
        except HTTPException:
            if track_chat_request:
                _finish_http_request_event(
                    request_id=request_id,
                    now_iso=_iso_now(),
                    duration_ms=int((asyncio.get_running_loop().time() - started_at) * 1000),
                    error="HTTPException",
                )
            raise
        except Exception:
            if track_chat_request:
                _finish_http_request_event(
                    request_id=request_id,
                    now_iso=_iso_now(),
                    duration_ms=int((asyncio.get_running_loop().time() - started_at) * 1000),
                    error="Unhandled exception",
                )
            request.state.shenyu_error_logged = True
            logger.exception("Unhandled exception request_id=%s for %s %s", request_id, request.method, request.url.path)
            raise

    @app.middleware("http")
    async def admin_auth_middleware(request: Request, call_next):
        from shenyu_gateway.auth import admin_auth_middleware_handler
        return await admin_auth_middleware_handler(request, call_next, cfg=cfg)
