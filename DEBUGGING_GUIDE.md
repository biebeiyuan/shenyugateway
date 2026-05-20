# Shenyu Gateway Debugging Guide

This guide is the quick entrypoint for future debugging windows. Read it together with `README.md` before changing gateway logic.

## First Rule

Preserve behavior before cleanup. This gateway has browser-facing contracts outside this repo, and code can look unused from the admin UI while still being used by `home-frontend`.

Do not commit one-off test files. Prefer `python -c`, temp directories, or existing `test_*.py` files. If a temporary test script is created in the repo, delete it before committing unless it is intentionally promoted into a permanent regression test and documented.

## Module Map

- `gateway.py`: FastAPI app, middleware, routes, service orchestration, upstream HTTP calls, tool loop, response filtering, and public API contracts.
- `shenyu_gateway/config.py`: environment-backed runtime config.
- `shenyu_gateway/store.py`: SQLite runtime state. Routes and services should call `GatewayStore` instead of writing SQL directly.
- `shenyu_gateway/supabase.py`: low-level Supabase REST mechanics.
- `shenyu_gateway/sessions.py`: session and message logging facade.
- `shenyu_gateway/calendar.py`: calendar date/key helpers and JSON parsing.
- `shenyu_gateway/calendar_sources.py`: day/week/month source collection for calendar generation.
- `shenyu_gateway/context_layers.py`: stable/slow/volatile layer rendering, client message trimming, tool-safe trimming, and cold-start bridge insertion.
- `shenyu_gateway/gateway_tools.py`: gateway-native tool implementations. Look here for Supabase table tools, primary-text surface retrieval, heartbeat reads, notebook helpers, and memory helper behavior.
- `shenyu_gateway/tool_registry.py`: gateway-native tool schemas, enablement/merge logic, and tool-name dispatch into `GatewayToolService`.
- `shenyu_gateway/response_capture.py`: private assistant tag filtering for `<heartbeat>` and `[mem]...[/mem]`, heartbeat persistence helper, and inline memory scheduling helper.
- `shenyu_gateway/upstream_adapter.py`: pure OpenAI/Anthropic payload, cache, stream, and model URL conversion helpers.

## Chat Request Flow

Main chat flow is centered in `gateway.py`:

1. Auth middleware allows `OPTIONS` and accepts both `Authorization` and `?token=...`.
2. Chat route calls `_prepare_messages()`.
3. `_prepare_messages()` opens the gateway session, stores a raw request window, trims client messages, writes a request context snapshot, builds a context package, renders context layers, and inserts them into the message list.
4. `ContextBuilder.build_context_package()` fetches runtime data: heartbeat digest, calendar context, Hisense notebook/recap, meta summaries, and atomic memories.
5. `shenyu_gateway.context_layers` renders the package into:
   - `stable`: charter, optional gateway tool policy, heartbeat prompt, optional inline mem prompt.
   - `slow`: calendar memory, Hisense notebook, wake recap.
   - `heartbeat`: independent `## 你之前的心跳` block after `slow` and before chat history.
   - `volatile`: active atomic memories, inserted before the latest user message.
6. `_build_upstream_request()` prepares the upstream payload.
7. `shenyu_gateway.upstream_adapter` converts OpenAI-compatible messages/tools to Anthropic when needed, adds cache markers, and converts responses/chunks back.
8. Tool loop may call gateway tools, then `shenyu_gateway.response_capture` filters private `<heartbeat>` and `[mem]...[/mem]` blocks before visible output is logged or sent.

Tool schemas and name dispatch live in `shenyu_gateway/tool_registry.py`; implementation methods live in `shenyu_gateway/gateway_tools.py`. If a tool is visible but behaves wrong, check `tool_registry.py` dispatch first, then the matching method in `gateway_tools.py`.

Gateway tool descriptions are intentionally short because they enter the model tool context. Keep them to one-line purpose plus backing pool/table. Put detailed usage notes in `shenyu_supabase_guide` or docs, not in every parameter description.

Useful boundary map:

- `shenyu_surface_passages`: gateway tool; reads Supabase `room` and `message_board`.
- `shenyu_search_primary_texts`: gateway tool; reads Supabase `journal`, `room`, and `message_board`.
- `shenyu_ask_memory`: gateway tool; reads Supabase `memories` event summaries.
- `shenyu_search_atomic_memory`: gateway tool; reads active Supabase `atomic_memories`.
- `shenyu_list_self_memories`: gateway tool; reads assistant-owned Supabase `atomic_memories`, defaulting to inline `[mem]` notes.
- `shenyu_read_heartbeat`: gateway tool; reads SQLite `heartbeat_entries` or `hisense_heartbeat`.
- `supabase_*`: gateway fallback tools for direct Supabase table operations.
- `GATEWAY_TOOL_MODE=broker`: exposes one compact `shenyu_gateway_tool` that dispatches to the same gateway-native tools. Use `full` when the model needs stricter per-tool parameter schemas.
- `query_memory` and `get_memory_by_title`, when visible, are client-provided tools from outside the gateway; inspect the client/Operit tool definitions for their backing pool.

## Context Layer Debugging

When context looks wrong, inspect in this order:

1. `cfg` flags: `MAX_CLIENT_MESSAGES`, `ENABLE_COLD_START`, `CALENDAR_INJECT_*`, `INJECT_ATOMIC_MEMORIES`, `ENABLE_GATEWAY_TOOLS`, `GATEWAY_TOOL_MODE`.
2. `_prepare_messages()` metadata: `client_message_window`, `cache_layers`, `cold_start_snapshot`, `is_hisense`, `upstream`.
3. SQLite tables:
   - `raw_request_windows`: original client payload before trimming.
   - `request_context_snapshots`: trimmed client window before gateway layers; used by cold start and calendar generation.
   - `cold_start_snapshots`: bounded bridge packages.
   - `heartbeat_entries`: normal/global heartbeat pool.
   - `hisense_heartbeat`: Hisense heartbeat pool.
4. `ContextBuilder.build_context_package()` to confirm which sources were fetched.
5. `context_layers.render_layered_additions()` and `context_layers.assemble_layered_messages()` to confirm layer placement.

Layer order in the final request:

```text
tools
stable system
slow system
heartbeat system
cold-start bridge messages, when active
trimmed client history
volatile system, when active, before latest user
latest user
```

## Calendar Debugging

Calendar generation uses `CalendarService` in `gateway.py`, but source collection lives in `calendar_sources.py`.

Current source rules:

- Day: latest 10 `request_context_snapshots`, latest 8 normal heartbeats, recent day/week/month pages, and a small surface pass.
- Week: latest 8 context snapshots, latest 5 normal heartbeats, and recent day/week/month pages.
- Month: latest 6 context snapshots, latest 5 normal heartbeats, and recent day/week/month pages.

If generated pages look empty, check `request_context_snapshots` first, then `heartbeat_entries`, then Supabase `calendar_pages`.

## Response Capture Debugging

Private assistant tags are parsed in `response_capture.py`:

- `AssistantTagFilter` supports chunked streaming input. It withholds partial `<heartbeat>` or `[mem]` tags until they close or are flushed.
- `split_private_assistant_tags()` is the non-streaming helper.
- `store_heartbeat()` writes normal or Hisense heartbeat rows through `GatewayStore`.
- `schedule_inline_memory_capture()` schedules `AtomicMemoryService.process_inline_memories()` without making `response_capture.py` import `gateway.py`.

Visible output should never include closed private blocks:

- `<heartbeat>...</heartbeat>` is removed and written to `heartbeat_entries` or `hisense_heartbeat`.
- Closed `[mem ...]...[/mem]` is removed and captured for inline memory processing.
- Incomplete `[mem]` is left visible on flush; incomplete heartbeat is captured and hidden.

When this area breaks, check `test_gateway_tags.py` first, then `scripts/test_inline_mem_capture.py`.

## External Frontend Contracts

These are hard contracts with `home-frontend`; do not remove or reshape them during cleanup:

- `GET /api/gateway/heartbeats?token=...&limit=2000&order=asc&scope=normal|hisense`
  - Query token auth must work.
  - Keep `limit`, `order`, and `scope`.
  - Return JSON with `heartbeats`.
  - Each heartbeat must include at least `content` and `created_at`.
  - `scope=normal` reads `heartbeat_entries`; `scope=hisense` reads `hisense_heartbeat`.
- `GET /api/calendar/month?token=...&month=YYYY-MM`
  - Return `grid`.
  - Each day item must keep `date`, `day`, `in_month`, `has_day`, `has_week`, and `day_page.id/title/summary/status` when present.
- `GET /api/calendar/page/{page_id}?token=...`
  - Return at least `id`, `title`, `summary`, and `content`.

Browser behavior to preserve:

- `/api/*` accepts `?token=...` because the external frontend intentionally avoids `Authorization` headers to reduce CORS preflight.
- `OPTIONS` must not be blocked by auth middleware.
- Keep CORS origins listed in `README.md`, including `null`.

Permanent test coverage for these contracts is in `test_external_contracts.py`.

## Verification Checklist

After Python changes:

```powershell
python -m py_compile gateway.py shenyu_gateway\store.py shenyu_gateway\calendar_sources.py shenyu_gateway\context_layers.py shenyu_gateway\response_capture.py shenyu_gateway\upstream_adapter.py test_external_contracts.py test_gateway_hisense_context.py test_gateway_tags.py test_gateway_trim.py scripts\test_inline_mem_capture.py
git diff --check
rg -n "<AGENTS.md mojibake pattern>" README.md DEBUGGING_GUIDE.md gateway.py shenyu_gateway test_*.py
```

If the local environment has `pytest` available:

```powershell
python -m pytest test_gateway_trim.py test_gateway_tags.py test_gateway_hisense_context.py test_external_contracts.py
```

If `pytest` is not available or WindowsApps Python fails, use a no-file smoke test with `TestClient` and a temporary SQLite database. Do not leave one-off smoke scripts in the repo.

## Refactor Boundaries

- Keep routes thin; push logic into services or helper modules.
- Keep query-token auth and CORS behavior in `gateway.py`, near the middleware and routes.
- Keep SQLite behavior in `GatewayStore`.
- Keep Supabase HTTP mechanics in `SupabaseClient`.
- Keep context rendering and message-window surgery in `context_layers.py`.
- Keep private response tag filtering, heartbeat capture helpers, and inline memory scheduling in `response_capture.py`.
- Keep upstream protocol conversion in `upstream_adapter.py`.
- Add comments only where they protect external contracts or explain non-obvious behavior.
