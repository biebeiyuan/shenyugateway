from __future__ import annotations

import asyncio
import time as _time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException, Request

from .context_layers import trim_client_image_blocks as _trim_client_image_blocks
from .request_logs import (
    _finalize_tool_stream_log,
    _mark_tool_stream_activity,
    _mark_request_log_phase,
    _message_log_preview,
    _record_completion_finish_reason,
    _record_finish_reason,
    _record_response_text,
    _record_upstream_payload,
    _request_logs,
    _retain_request_log_payloads,
)
from .runtime import iso_now as _iso_now
from .runtime import logger
from .sessions import SessionManager
from .streaming import (
    _gateway_error_completion,
    _gateway_error_text,
    _sse_response,
    _stream_gateway_error_events,
)
from .tool_loop import _latest_user_text
from .tool_registry import is_gateway_native_tool, merge_tools
from .upstream_adapter import _cache_usage_summary
from .upstream_response_evidence import (
    ensure_upstream_response_evidence,
    upstream_response_evidence_snapshot,
)
from .response_meta import attach_response_meta, build_response_meta, echo_events_enabled, response_meta_enabled
from .private_capture import unpack_private_capture_result as _unpack_private_capture_result


@dataclass
class ChatPipeline:
    cfg: Any
    store: Any
    prepare_messages: Callable[[Request, Any], Awaitable[tuple[list[dict], dict]]]
    build_upstream_request: Callable[..., Awaitable[tuple[dict, dict, str, dict, dict]]]
    run_internal_tool_loop: Callable[..., Awaitable[dict]]
    run_internal_tool_loop_stream: Callable[..., Any]
    stream_chat: Callable[..., Awaitable[Any]]
    nonstream_chat: Callable[..., Awaitable[dict]]
    resolve_upstream: Callable[[], dict[str, str]]
    mapped_model_name: Callable[[str], str]
    private_capture_fallback_text: Callable[[str, list[str]], tuple[str, str]]
    private_capture_kinds: Callable[..., list[str]]
    finalize_assistant_private_content: Callable[..., tuple[str, str, str, dict[str, Any]]]
    store_heartbeat: Callable[[str, dict, str], None]
    mark_context_consumed: Callable[[dict], None]
    write_completion_context_snapshot: Callable[..., Any]

    async def run(self, request: Request, body: Any):
        t0 = _time.monotonic()
        log_entry = self._build_initial_log_entry(request=request, body=body)
        _request_logs.appendleft(log_entry)
        request.state.shenyu_log_entry = log_entry
        _mark_request_log_phase(log_entry, "pipeline.received", now_iso=log_entry["timestamp"])
        self._persist_log_entry(log_entry)

        try:
            self._mark_log_stage(log_entry, "prepare_messages")
            prepared_messages, meta = await self.prepare_messages(request, body)
            sessions = SessionManager(self.store, self.cfg)
            session = meta["session"]
            session_id = session["id"]
            prepared_messages_for_log, _ = _trim_client_image_blocks(prepared_messages, keep_recent_messages=0)
            sessions.log_input_messages(session_id, prepared_messages_for_log)

            merged_tools = merge_tools(body.tools, self.cfg, meta=meta)
            has_gateway_managed_tools = any(
                is_gateway_native_tool(tool.get("function", {}).get("name", ""))
                for tool in merged_tools
            )

            self._update_log_entry(
                log_entry=log_entry,
                body=body,
                prepared_messages=prepared_messages,
                prepared_messages_for_log=prepared_messages_for_log,
                meta=meta,
                merged_tools=merged_tools,
                has_gateway_managed_tools=has_gateway_managed_tools,
            )

            if has_gateway_managed_tools:
                self._mark_log_stage(log_entry, "gateway_tool_path")
                return await self._run_gateway_tool_path(
                    request=request,
                    body=body,
                    prepared_messages=prepared_messages,
                    meta=meta,
                    log_entry=log_entry,
                    t0=t0,
                )

            self._mark_log_stage(log_entry, "plain_upstream_path")
            return await self._run_plain_upstream_path(
                request=request,
                body=body,
                prepared_messages=prepared_messages,
                meta=meta,
                log_entry=log_entry,
                sessions=sessions,
                session=session,
                session_id=session_id,
            )
        except Exception as exc:
            log_entry["status"] = "error"
            log_entry["error"] = str(exc)[:500]
            raise
        finally:
            log_entry["duration_ms"] = int((_time.monotonic() - t0) * 1000)
            log_entry["last_activity_at"] = _iso_now()
            _mark_request_log_phase(log_entry, "pipeline.returned", now_iso=log_entry["last_activity_at"])
            self._persist_log_entry(log_entry)

    def _build_initial_log_entry(self, *, request: Request, body: Any) -> dict:
        log_id = uuid.uuid4().hex[:8]
        request_id = getattr(request.state, "shenyu_request_id", log_id)
        now_value = _iso_now()
        return {
            "id": log_id,
            "request_id": request_id,
            "timestamp": now_value,
            "last_activity_at": now_value,
            "stage": "received",
            "model": body.model,
            "client_model": body.model,
            "upstream_model": body.model,
            "model_mapped": False,
            "stream": body.stream,
            "session_tag": request.headers.get("X-Shenyu-Session-Tag")
            or request.headers.get("X-Session-Tag")
            or "unknown",
            "is_first_turn": False,
            "original_messages_count": len(body.messages),
            "prepared_messages_count": 0,
            "client_message_window": {},
            "memory_island": {},
            "cold_start": {
                "injected": False,
                "snapshot_id": None,
                "reason": None,
                "source_message_count": 0,
                "source_session_tags": [],
                "bridge_messages": 0,
            },
            "system_additions_preview": "",
            "system_additions_full": None,
            "system_additions_chars": 0,
            "tools_count": len(body.tools or []),
            "tool_names": [
                tool.get("function", {}).get("name", "")
                for tool in (body.tools or [])[:20]
                if isinstance(tool, dict)
            ],
            "tool_names_all": [
                tool.get("function", {}).get("name", "")
                for tool in (body.tools or [])
                if isinstance(tool, dict)
            ],
            "has_internal_tools": False,
            "upstream_url": "",
            "upstream_scope": "unknown",
            "request_payloads_retained": _retain_request_log_payloads(self.cfg),
            "prepared_messages": None,
            "prepared_messages_preview": [],
            "upstream_payload": None,
            "upstream_payload_summary": None,
            "upstream_response_evidence": None,
            "cache_layers": {},
            "prompt_cache": {
                "enabled": False,
                "protocol": "unknown",
                "upstream_scope": "unknown",
                "breakpoints": [],
                "note": "Request log was created before context preparation finished.",
            },
            "usage": None,
            "cache_usage": _cache_usage_summary({}),
            "finish_reason": None,
            "status": "preparing",
            "duration_ms": 0,
            "error": None,
            "response_preview": None,
            "response_full": None,
            "empty_visible_response_fallback": False,
            "empty_visible_response_fallback_detail": None,
        }

    def _mark_log_stage(self, log_entry: dict, stage: str) -> None:
        log_entry["stage"] = stage
        now_value = _iso_now()
        log_entry["last_activity_at"] = now_value
        _mark_request_log_phase(log_entry, f"stage.{stage}", now_iso=now_value)
        self._persist_log_entry(log_entry)

    def _persist_log_entry(self, log_entry: dict) -> None:
        persist = getattr(self.store, "upsert_request_log", None)
        if not callable(persist):
            return
        try:
            persist(
                log_entry,
                retention=getattr(self.cfg, "gateway_request_log_retention", 200),
            )
        except Exception:
            logger.warning(
                "Failed to persist request log id=%s",
                log_entry.get("id"),
                exc_info=True,
            )

    def _update_log_entry(
        self,
        *,
        log_entry: dict,
        body: Any,
        prepared_messages: list[dict],
        prepared_messages_for_log: list[dict],
        meta: dict,
        merged_tools: list[dict],
        has_gateway_managed_tools: bool,
    ) -> None:
        request_upstream = meta.get("upstream") or self.resolve_upstream()
        sys_parts = [
            msg.get("content", "")
            for msg in prepared_messages
            if msg.get("role") == "system"
        ]
        system_additions = "\n\n---\n\n".join(sys_parts)
        retain_payloads = bool(log_entry.get("request_payloads_retained"))
        island_state = (meta.get("package") or {}).get("memory_island_state") or {}
        island_log_content = dict(
            (meta.get("package") or {}).get("memory_island_log_content")
            or {
                "version": island_state.get("version"),
                "star_count": len(island_state.get("stars") or []),
                "mem_count": len(island_state.get("mem_notes") or []),
            }
        )
        island_log_content["rendered_text"] = island_state.get("rendered_text") or "" if retain_payloads else ""
        upstream_model = self.mapped_model_name(body.model)
        log_entry.update({
            "stage": "prepared",
            "prepared_at": _iso_now(),
            "last_activity_at": _iso_now(),
            "model": body.model,
            "client_model": body.model,
            "upstream_model": upstream_model,
            "model_mapped": upstream_model != body.model,
            "stream": body.stream,
            "session_tag": meta["session"].get("session_tag", "default"),
            "client_name": meta["session"].get("client_name", "unknown-client"),
            "client_profile": meta.get("client_profile") or {},
            "is_first_turn": meta.get("is_first_turn", False),
            "original_messages_count": len(body.messages),
            "prepared_messages_count": len(prepared_messages),
            "client_message_window": meta.get("client_message_window", {}),
            "memory_island": (meta.get("package") or {}).get("memory_island_decision") or {},
            "memory_island_version": (
                island_state.get("version")
            ),
            "memory_island_content": island_log_content,
            "cold_start": {
                "injected": bool(meta.get("cold_start_snapshot")),
                "snapshot_id": (meta.get("cold_start_snapshot") or {}).get("id"),
                "reason": (meta.get("cold_start_snapshot") or {}).get("reason"),
                "source_message_count": (meta.get("cold_start_snapshot") or {}).get("source_message_count", 0),
                "source_session_tags": (meta.get("cold_start_snapshot") or {}).get("source_session_tags", []),
                "bridge_messages": meta.get("client_message_window", {}).get("cold_start_bridge_messages", 0),
            },
            "system_additions_preview": system_additions[:500],
            "system_additions_full": system_additions if retain_payloads else None,
            "system_additions_chars": len(system_additions),
            "tools_count": len(merged_tools),
            "tool_names": [t.get("function", {}).get("name", "") for t in merged_tools[:20]],
            "tool_names_all": [t.get("function", {}).get("name", "") for t in merged_tools],
            "has_internal_tools": has_gateway_managed_tools,
            "tool_events": [],
            "is_room": bool(meta.get("is_room")),
            "room_charge": (meta.get("package") or {}).get("charge") if meta.get("is_room") else None,
            "upstream_url": request_upstream["chat_url"],
            "upstream_scope": request_upstream["scope"],
            "request_payloads_retained": retain_payloads,
            "prepared_messages": prepared_messages_for_log if retain_payloads else None,
            "prepared_messages_preview": [_message_log_preview(msg) for msg in prepared_messages_for_log],
            "upstream_payload": None,
            "upstream_payload_summary": None,
            "upstream_response_evidence": None,
            "cache_layers": {
                key: f"{len(value)} chars" if value else "(empty)"
                for key, value in meta.get("cache_layers", {}).items()
            },
            "prompt_cache": {
                "enabled": (
                    bool(getattr(self.cfg, "enable_anthropic_cache_control", True))
                    if request_upstream["protocol"] == "anthropic"
                    else bool(getattr(self.cfg, "enable_openai_cache_control", True))
                ),
                "protocol": request_upstream["protocol"],
                "ttl": (
                    getattr(self.cfg, "anthropic_cache_ttl", "1h")
                    if request_upstream["protocol"] == "anthropic"
                    else getattr(self.cfg, "openai_cache_ttl", "5m")
                ),
                "upstream_scope": request_upstream["scope"],
                "breakpoints": [],
                "note": "Prompt cache metadata is populated when the upstream payload is built.",
            },
            "usage": None,
            "cache_usage": _cache_usage_summary({}),
            "finish_reason": None,
            "status": "pending",
            "duration_ms": 0,
            "error": None,
            "response_preview": None,
            "response_full": None,
            "empty_visible_response_fallback": False,
            "empty_visible_response_fallback_detail": None,
        })

    async def _run_gateway_tool_path(
        self,
        *,
        request: Request,
        body: Any,
        prepared_messages: list[dict],
        meta: dict,
        log_entry: dict,
        t0: float,
    ):
        if body.stream:
            log_entry["status"] = "streaming_tools"
            _mark_tool_stream_activity(log_entry)

            async def _tool_loop_stream():
                _mark_tool_stream_activity(log_entry)
                try:
                    async for chunk in self.run_internal_tool_loop_stream(
                        request,
                        body,
                        prepared_messages,
                        meta,
                        log_entry=log_entry,
                    ):
                        _mark_tool_stream_activity(log_entry)
                        yield chunk
                except asyncio.CancelledError:
                    log_entry["status"] = "client_disconnected"
                    log_entry["error"] = "Client disconnected during native internal gateway tool stream."
                    raise
                except HTTPException as exc:
                    log_entry["status"] = "error"
                    log_entry["error"] = _gateway_error_text(exc)
                    for chunk in _stream_gateway_error_events(body.model, log_entry["error"]):
                        _mark_tool_stream_activity(log_entry)
                        yield chunk
                except Exception as exc:
                    logger.exception("Internal gateway tool stream failed")
                    log_entry["status"] = "error"
                    log_entry["error"] = _gateway_error_text(exc)
                    for chunk in _stream_gateway_error_events(body.model, log_entry["error"]):
                        _mark_tool_stream_activity(log_entry)
                        yield chunk
                finally:
                    _finalize_tool_stream_log(
                        log_entry,
                        int((_time.monotonic() - t0) * 1000),
                    )
                    self._persist_log_entry(log_entry)

            return _sse_response(_tool_loop_stream())

        try:
            completion = await self.run_internal_tool_loop(
                request,
                body,
                prepared_messages,
                meta,
                log_entry=log_entry,
            )
        except HTTPException as exc:
            log_entry["status"] = "error"
            log_entry["error"] = _gateway_error_text(exc)
            completion = _gateway_error_completion(body.model, log_entry["error"])
            _record_response_text(log_entry, completion["choices"][0]["message"]["content"])
            return completion
        except Exception as exc:
            logger.exception("Internal gateway tool request failed")
            log_entry["status"] = "error"
            log_entry["error"] = _gateway_error_text(exc)
            completion = _gateway_error_completion(body.model, log_entry["error"])
            _record_response_text(log_entry, completion["choices"][0]["message"]["content"])
            return completion

        self.mark_context_consumed(meta)
        log_entry["usage"] = completion.get("usage", log_entry.get("usage"))
        log_entry["cache_usage"] = log_entry.get("cache_usage") or _cache_usage_summary(completion.get("usage", {}))
        _record_completion_finish_reason(log_entry, completion)
        log_entry["status"] = "ok"
        _record_response_text(
            log_entry,
            str(completion.get("choices", [{}])[0].get("message", {}).get("content", "")),
        )
        return completion

    async def _run_plain_upstream_path(
        self,
        *,
        request: Request,
        body: Any,
        prepared_messages: list[dict],
        meta: dict,
        log_entry: dict,
        sessions: SessionManager,
        session: dict,
        session_id: str,
    ):
        payload, headers, _, cache_meta, upstream = await self.build_upstream_request(
            request,
            body,
            messages_override=prepared_messages,
            meta=meta,
        )
        _record_upstream_payload(log_entry, payload, headers)
        log_entry["prompt_cache"] = cache_meta
        ensure_upstream_response_evidence(
            upstream,
            payload,
            "stream" if body.stream else "nonstream",
            reset=True,
        )
        log_entry["upstream_response_evidence"] = upstream_response_evidence_snapshot(upstream)

        if body.stream:
            log_entry["status"] = "streaming"
            log_entry["usage"] = {"note": "Streaming usage is not available in this gateway log path."}

            def _on_stream_complete(
                collected_text: str,
                heartbeat_content: str = "",
                fallback_applied: bool = False,
                usage: Optional[dict] = None,
                finish_reason: Optional[str] = None,
                terminal_status: str = "ok",
                terminal_error: Optional[str] = None,
                echo_content: str = "",
            ):
                try:
                    log_entry["upstream_response_evidence"] = upstream_response_evidence_snapshot(upstream)
                    if terminal_status != "ok":
                        log_entry["status"] = terminal_status
                        log_entry["error"] = terminal_error or "Upstream stream did not complete normally."
                        _record_response_text(log_entry, collected_text)
                        return
                    log_entry["status"] = "ok"
                    _record_finish_reason(log_entry, finish_reason)
                    if usage:
                        log_entry["usage"] = usage
                        log_entry["cache_usage"] = _cache_usage_summary(
                            usage,
                            protocol=upstream.get("protocol", ""),
                        )
                    if fallback_applied:
                        log_entry["empty_visible_response_fallback"] = True
                        fallback_text, fallback_context = self.private_capture_fallback_text(
                            _latest_user_text(prepared_messages),
                            self.private_capture_kinds(
                                heartbeat_content=heartbeat_content,
                            ),
                        )
                        log_entry["empty_visible_response_fallback_detail"] = {
                            "applied": True,
                            "text": fallback_text,
                            "kinds": self.private_capture_kinds(
                                heartbeat_content=heartbeat_content,
                            ),
                            "context": fallback_context,
                        }
                    if collected_text or echo_content:
                        assistant_msg = {"role": "assistant", "content": collected_text}
                        sessions.log_assistant_output(session_id, assistant_msg, echo=echo_content)
                        self.write_completion_context_snapshot(meta, collected_text, echo_content)
                        _record_response_text(log_entry, collected_text)
                    else:
                        _record_response_text(log_entry, "")
                    if heartbeat_content:
                        self.store_heartbeat(session_id, session, heartbeat_content)
                    self.mark_context_consumed(meta)
                finally:
                    self._persist_log_entry(log_entry)

            def _response_meta(
                *,
                heartbeat_content: str = "",
                usage: Optional[dict] = None,
                **_kwargs: Any,
            ) -> dict[str, Any]:
                return build_response_meta(
                    meta,
                    _cache_usage_summary(
                        usage or {},
                        protocol=upstream.get("protocol", ""),
                    ),
                    heartbeat_captured=bool(heartbeat_content),
                )

            return await self.stream_chat(
                request,
                payload,
                headers,
                body.model,
                upstream,
                on_complete=_on_stream_complete,
                latest_user_text=_latest_user_text(prepared_messages),
                response_meta=_response_meta if response_meta_enabled(meta) else None,
                emit_echo_events=echo_events_enabled(meta),
            )

        completion = await self.nonstream_chat(request, payload, headers, body.model, upstream)
        log_entry["upstream_response_evidence"] = upstream_response_evidence_snapshot(upstream)
        log_entry["usage"] = completion.get("usage", {})
        log_entry["cache_usage"] = _cache_usage_summary(
            completion.get("usage", {}),
            protocol=upstream.get("protocol", ""),
        )
        _record_completion_finish_reason(log_entry, completion)
        assistant_message = completion.get("choices", [{}])[0].get("message", {})
        clean_content, heartbeat_content, echo_content, fallback_meta = _unpack_private_capture_result(
            self.finalize_assistant_private_content(
                assistant_message,
                latest_user_text=_latest_user_text(prepared_messages),
            )
        )
        if heartbeat_content:
            self.store_heartbeat(session_id, session, heartbeat_content)
        if fallback_meta["applied"]:
            log_entry["empty_visible_response_fallback"] = True
            log_entry["empty_visible_response_fallback_detail"] = dict(fallback_meta)

        sessions.log_assistant_output(session_id, {"role": "assistant", "content": clean_content}, echo=echo_content)
        self.write_completion_context_snapshot(meta, clean_content, echo_content)
        self.mark_context_consumed(meta)
        if echo_content and echo_events_enabled(meta):
            completion.setdefault("shenyu", {})["echo"] = echo_content
        if response_meta_enabled(meta):
            attach_response_meta(
                completion,
                meta,
                log_entry.get("cache_usage") or {},
                heartbeat_captured=bool(heartbeat_content),
            )
        log_entry["status"] = "ok"
        _record_response_text(log_entry, clean_content)
        return completion
