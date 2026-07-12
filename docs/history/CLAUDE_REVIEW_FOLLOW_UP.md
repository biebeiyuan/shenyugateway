# Claude Code Review Follow-Up（历史）

本文从 README 迁出，记录当时 code-review 报告对应的执行思路。状态和优先级可能已经过时；当前结论以代码、测试和 `docs/architecture/AUDIT_MATRIX.md` 为准。


This plan comes from the Claude code-review report, adjusted for the current mixed-tool fix.

Current status:

- A6 is complete. The gateway no longer writes `<gateway_tool_results>` into new assistant content. Instead, it uses `pending_gateway_tool_turns` and reconstructs the structured tool transcript before the next upstream request.
- Do not implement the report's A/C "strip XML" variants now; they would hide state from the next model turn. Do not use custom client metadata for this path; ordinary clients should only need normal OpenAI tool messages.
- B1, B2, B3, and B7 are still useful, but should stay separate from protocol fixes.

Recommended order:

| Phase | Item | Why now | Scope | Exit criteria |
|---|---|---|---|---|
| 1 | B3 `execute_gateway_tool` dispatch refactor | Highest maintenance risk in the remaining report. It also gives the next refactors a cleaner tool boundary. | Add handler snapshot tests first, then replace the giant handler dict/lambdas with `ToolContext` plus registered async handler functions. Keep broker behavior identical. | All existing tool-registry tests pass; new parameter snapshot tests cover aliases, session_tag fallback, cfg defaults, broker nested arguments, and unsupported tools. |
| 2 | B7 return format normalization | Small, easy win after B3 tests make tool behavior visible. | Add `ok: true` to successful tool results that currently omit it, especially memory/search style results. Keep error shape as `{ok: false, error: ...}`. | Tests assert both success and error shapes for direct and broker calls. |
| 3 | B1 `gateway.py` split | **Partially done.** Auth, upstream HTTP, prepare-messages, and private-capture logic have been extracted into `auth.py`, `upstream_client.py`, `prepare_messages.py`, and `private_capture.py`. Remaining candidates: calendar service, admin routes, streaming helpers. | Extract remaining concerns by dependency order. Move code without behavior changes. | `gateway.py` remains the app entrypoint and chat route coordinator; moved modules have focused imports; streaming/tool-loop tests still pass. |
| 4 | B2 `GatewayToolService` composition split | Useful only after B3/B1 reduce the surrounding noise. | Keep `GatewayToolService` as a compatibility facade and delegate to Supabase, memory, star memory, calendar, heartbeat, and notebook operation classes. | Tool registry does not change; service tests prove old method signatures still work. |

Phase 1 executable checklist:

1. In `test_gateway_tool_registry.py`, create a call-recording fake service that can record every tool method invocation.
2. Add snapshot tests for every public gateway-native tool and for `shenyu_gateway_tool` broker mode.
3. Cover tricky argument behavior before refactoring: `query/q`, `source_types/sources`, `date_from/since`, `date_to/until`, `note_id/id/noteId`, invalid numeric limits, cfg-driven defaults, and session_tag fallback/non-fallback differences.
4. Add `ToolContext` and `_tool_handler()` registration in `shenyu_gateway/tool_registry.py`.
5. Move 2-3 handlers at a time from lambda dict entries into named async functions; run the registry tests after each batch.
6. Remove the old handler dict after all registered handlers are covered.
7. Run:

```bash
python -c "import test_gateway_tool_registry as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]"
python -c "import test_gateway_streaming as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]"
python -m py_compile gateway.py shenyu_gateway/*.py
```

Phase 3 split guidance:

Completed extractions:
- `shenyu_gateway/auth.py` — admin auth middleware, API key verification, login page.
- `shenyu_gateway/upstream_client.py` — all upstream HTTP communication: protocol detection, URL routing, request building, streaming, error formatting.
- `shenyu_gateway/prepare_messages.py` — cold-start snapshot, runtime pruning, pending gateway tool turn injection, message helpers.
- `shenyu_gateway/private_capture.py` — private content finalization (heartbeat only), fallback text, context-consumed marking.
- `shenyu_gateway/utils.py` — consolidated `shorten` and `clean_config_text` from duplicated definitions across modules.
- `shenyu_gateway/runtime.py` — shared runtime utilities (logger, timestamps, json_dumps, dotenv).
- `shenyu_gateway/schemas.py` — Pydantic data models.
- `shenyu_gateway/middleware.py` — FastAPI middleware registration.
- `shenyu_gateway/chat_pipeline.py` — main chat request orchestration.
- `shenyu_gateway/streaming.py` — SSE streaming helpers.
- `shenyu_gateway/stream_proxy.py` — plain pass-through streaming.
- `shenyu_gateway/tool_loop.py` — internal gateway tool loop.
- `shenyu_gateway/context_snapshots.py` — context snapshot creation helpers.
- `shenyu_gateway/request_logs.py` — in-memory request log ring buffer.
- `shenyu_gateway/tool_schemas.py` — tool JSON schema definitions.
- `shenyu_gateway/calendar_routes.py` — calendar API routes.
- `shenyu_gateway/hisense_routes.py` — Hisense API routes.
- `shenyu_gateway/archive_routes.py` — archive/conflict book API routes.
- `shenyu_gateway/config_routes.py` — configuration API routes.
- `shenyu_gateway/admin_shell_routes.py` — admin shell/UI routes.
- `shenyu_gateway/room_scenes.py` — window scene copy and weather logic.

`gateway.py` is now ~740 lines (down from ~1157). It remains the app entrypoint and route registrar; chat pipeline logic lives in `chat_pipeline.py`.
