# Shenyu Gateway

Shenyu Gateway is the single OpenAI-compatible provider entrypoint for Operit. It prepares context, exposes tools, routes tool calls, and adapts requests to Anthropic or OpenAI-compatible upstreams.

The gateway is not a persona layer or roleplay wrapper. It is a context and memory gateway: current conversation text stays primary, long-form primary text can surface softly, and durable memory is handled by explicit layers.

For future debugging and cleanup work, start with `DEBUGGING_GUIDE.md`. It records the current module boundaries, chat/context flow, external frontend contracts, and verification checklist.

## Current Architecture

```text
Operit
  -> Shenyu Gateway
       -> ContextBuilder
       -> GatewayStore (SQLite runtime state)
       -> GatewayToolService (Supabase tools, surface, memory)
       -> CalendarService (day/week/month pages)
       -> MemNoteService (small personal notes)
       -> Upstream adapter (Anthropic / OpenAI-compatible)
  -> Upstream model
  -> gateway tool loop when needed
```

## Maintenance Map

The codebase is partly layered already:

- `shenyu_gateway/config.py`: environment-backed runtime config.
- `shenyu_gateway/store.py`: SQLite runtime state only.
- `shenyu_gateway/supabase.py`: low-level Supabase REST client.
- `shenyu_gateway/calendar.py`: date/key helpers and calendar JSON parsing.
- `shenyu_gateway/calendar_sources.py`: day/week/month source collection for calendar generation.
- `shenyu_gateway/context_layers.py`: stable/slow/volatile layer rendering, client message trimming, and cold-start bridge insertion.
- `shenyu_gateway/gateway_tools.py`: gateway-native tool implementations, including Supabase table tools, recall compatibility helpers, heartbeats, notebook, and memory helpers.
- `shenyu_gateway/tool_registry.py`: gateway-native tool schemas, enablement/merge logic, and tool-name dispatch into `GatewayToolService`.
- `shenyu_gateway/response_capture.py`: private assistant tag filtering for `<heartbeat>` and `[mem]...[/mem]`, heartbeat persistence helper, and inline memory scheduling helper.
- `shenyu_gateway/mem_notes.py`: inline `[mem]` capture, clean note search, review/update/delete helpers, and old atomic read-only lookup.
- `shenyu_gateway/sessions.py`: session/message logging facade.
- `shenyu_gateway/upstream_adapter.py`: pure OpenAI/Anthropic message, cache, stream, and model URL conversion helpers.
- `gateway.py`: FastAPI routes, middleware, upstream HTTP calls, context orchestration, tool-loop orchestration, calendar generation service, and Hisense routes.

When cleaning or refactoring, preserve behavior first and move code by boundary:

1. Route handlers should stay thin and call service classes.
2. SQLite reads/writes belong in `GatewayStore`; do not query SQLite directly from route handlers.
3. Supabase HTTP mechanics belong in `SupabaseClient`; table-specific behavior can live in service classes.
4. Context data fetching belongs around `ContextBuilder`; layer rendering and message-window assembly belong in `shenyu_gateway/context_layers.py`.
5. Private response tag filtering and capture helpers belong in `shenyu_gateway/response_capture.py`.
6. Gateway-native tool behavior belongs in `shenyu_gateway/gateway_tools.py`; tool schemas, merge logic, and name dispatch belong in `shenyu_gateway/tool_registry.py`. Keep tool descriptions short: one-line purpose plus backing table/pool.
7. Upstream protocol conversion belongs in `shenyu_gateway/upstream_adapter.py`; request routing and HTTP calls stay near `_build_upstream_request`.
8. External frontend contracts below are not dead code just because admin UI does not import them.

## Context Layers

Context is assembled from low-change to high-change content:

| Layer | Placement | Contents | Cache policy |
|---|---|---|---|
| `tools` | request tools | client tools + `shenyu_*` / `supabase_*` tools | breakpoint at `tools[-1]` |
| `stable` | first system message | stable charter, active meta summaries, gateway tool policy, heartbeat instructions | breakpoint |
| `slow` | second system message when present | calendar memory, Hisense notebook/recap | breakpoint |
| `heartbeat` | after `slow`, before client history | `## 你之前的心跳` and optional Hisense heartbeat block | no breakpoint |
| client history | original messages | trimmed client messages when `MAX_CLIENT_MESSAGES` is set | fallback breakpoint only if one is free |
| `volatile` | inserted before latest user message | active mem notes | no breakpoint |
| current user | latest user message | current request | no breakpoint |

The retired rolling and frozen context layers have been removed from the active flow. Their legacy SQLite tables are only cleaned up during session deletion when they exist in an older database.

`GATEWAY_TOOL_MODE=broker` is the default and exposes one compact `shenyu_gateway_tool` dispatcher that calls the same gateway-native tools with fewer schema tokens. Use `full` when strict per-tool parameter guidance matters more than prompt size.

## Prompt Cache

The gateway adds Anthropic-compatible `cache_control` markers on stable prefixes. With a full set of layers, the intended breakpoints are:

```text
tools[-1]
messages[0].stable
messages[1].slow
```

If `slow` is empty, the gateway may use the remaining breakpoint on the previous stable conversation message. Heartbeat and volatile retrieval results are deliberately left uncached so random or frequently changing content does not poison the prefix cache.

Real cache hits still depend on the upstream or OpenAI-compatible relay honoring Anthropic `cache_control`. Check:

```text
usage.prompt_tokens_details.cached_tokens > 0
```

or the normalized gateway log field:

```text
cache_usage.cache_read_input_tokens > 0
```

## Streaming And Tool Calls

The gateway has two streaming paths:

- Plain pass-through streaming: when no gateway-managed tools are exposed for a request, `_stream_chat()` forwards upstream chunks while filtering private `<heartbeat>` and `[mem]...[/mem]` blocks from visible output.
- Gateway-managed tool streaming: when `shenyu_*` / `supabase_*` tools are available, `_run_internal_tool_loop_stream()` consumes upstream stream chunks directly. It intercepts gateway-native tool calls, executes them server-side, appends tool results to the working message list, and starts the next upstream round. Final natural-language replies stream to the client token by token.

Request count is still driven by model tool rounds, not by streaming itself:

- direct answer: one upstream request
- one internal tool round: one upstream request to produce the tool call, then one upstream request to produce the final answer from the tool result
- repeated internal tool rounds: one upstream request per round, bounded by `MAX_INTERNAL_TOOL_ROUNDS`

Streaming changes the connection shape, not the number of model rounds. The managed stream sends OpenAI-compatible empty delta keepalives while waiting on the upstream or tool execution, and all SSE responses set `Cache-Control: no-cache, no-transform` plus `X-Accel-Buffering: no` to reduce proxy buffering.

Tool routing rules:

- Gateway-native calls are recognized by `is_gateway_native_tool()` and executed through `execute_gateway_tool()`.
- Mixed batches are split: gateway-native calls are consumed by the gateway, while client-executable calls remain in `tool_calls` and are forwarded to the client.
- Internal tool exceptions are returned to the model as tool results shaped like `{ok: false, error: ...}` so one failed tool does not automatically fail the whole chat request.
- Repeated identical tool calls within one internal loop use an in-memory duplicate-result cache.

Adding ordinary gateway-native tools should not require changes to the streaming loop. Add the schema/name dispatch in `shenyu_gateway/tool_registry.py` and the behavior in `shenyu_gateway/gateway_tools.py`. Only update streaming/protocol code when adding a new upstream protocol, a tool whose execution progress must stream to the client, or a non-gateway client tool with special forwarding semantics.

`shenyu_gateway/upstream_adapter.py` normalizes upstream stream protocols. Anthropic `tool_use` / `input_json_delta` chunks are converted into OpenAI-compatible `tool_calls` deltas, and completion-to-SSE conversion can skip duplicate role chunks and split large final content into smaller events.

## SQLite Runtime State

SQLite stores only gateway runtime state:

- `gateway_sessions`
- `gateway_messages`: local message stream for inspection only. It is not the cold-start source of truth.
- `request_context_snapshots`: recent client context windows. Calendar generation and cold-start both depend on this.
- `raw_request_windows`: recent untrimmed client request windows for backup/export/debugging.
- `cold_start_snapshots`: bounded bridge packages created from recent context snapshots.
- `cache_entries`: short-lived gateway cache.
- `heartbeat_entries`: global private heartbeat notes captured from `<heartbeat>...</heartbeat>` or written manually in admin. `session_id` is retained as the source session, but runtime injection reads the shared global pool.
- `hisense_heartbeat`: private heartbeat notes captured from Hisense sessions. These use the same parser as normal heartbeats but are stored and injected separately.

`request_context_snapshots` is the replacement for the old rolling/frozen context path. Each request stores the trimmed client window before gateway layers are inserted. Calendar generation and cold-start bridge both read these snapshots. `raw_request_windows` stores the original client payload window before any gateway-side trimming and is kept separate so cold-start stays bounded.

### SQLite Retention And Cleanup

SQLite is intentionally kept as a small online runtime database. Supabase remains the durable memory/content store.

Default online retention:

- `GATEWAY_MESSAGE_RETENTION=1500`: keep the newest local message rows per session. These rows are for admin inspection and export, not for cold-start injection.
- `GATEWAY_CONTEXT_SNAPSHOT_RETENTION=3`: keep the newest context snapshots per session. Do not set this to `0`; cold-start and calendar source collection need recent snapshots.
- `GATEWAY_COLD_START_RETENTION=20`: keep recent cold-start snapshots per session. Cleanup only removes old snapshots whose `injected_count >= max_injections`, so active cold-start bridges are preserved.
- `heartbeat_entries` and `hisense_heartbeat` are not removed by automatic cleanup. They can be manually written/deleted from the admin session page, and those actions affect their respective heartbeat pools.
- expired `cache_entries` are removed during cleanup.

Runtime cleanup APIs:

- `POST /api/gateway/prune`: applies the retention policy above.
- `POST /api/gateway/dedupe-messages`: removes exact duplicate local message rows within each session, keeping the newest row for each `session_id + role + content + tool_name`.
- `GET /api/gateway/sessions/{session_tag}/export`: exports one session as JSON before manual deletion or migration, including raw request windows.

Admin page note:

- The session page's `消息` tab now renders `raw_request_windows`.
- That tab shows the original client payload window captured before gateway-side trimming.
- `gateway_messages` stays in the database for inspection and cleanup, but it is no longer the primary session-detail view.

Safe cleanup boundaries:

- It is safe to prune/dedupe `gateway_messages`; cold-start does not read this table.
- It is safe to prune/dedupe `raw_request_windows`; they are backup/debug records and are not used for cold-start injection.
- Be conservative with `request_context_snapshots`; cold-start and calendar generation read this table.
- Do not delete active `cold_start_snapshots`; the retention cleanup already avoids active snapshots.
- Heartbeats are independent from message cleanup and are only changed by explicit heartbeat actions.

## Supabase Long-Term State

Supabase remains the durable fact and content source:

- `journal`
- `room`
- `message_board`
- `memories`
- `meta_summaries`
- `heartbeats`
- `system_docs`
- `memory_tags`
- `memory_links`
- `calendar_prompt_configs`
- `calendar_pages`
- `calendar_generation_runs`
- `shenyu_mem_notes`
- `atomic_memories` (legacy read-only migration source)

The short-lived notes table is no longer used by gateway code.

The mem review UI reads and updates Supabase `shenyu_mem_notes`. The old `atomic_memories` table is only exposed through a read-only lookup for manual migration. SQLite only provides local request/session context.

## Recall Index

`shenyu_recall` is the unified search entrypoint for old context. It searches the `shenyu_recall_index` Supabase table with keyword matching first and vector matching when embeddings are configured. The tool returns the selected original chunks with title, source, date, and content, so the model can read the matched text directly instead of only seeing a summary.

Indexed public source types:

- `memory`: rows from `memories`
- `journal`: rows from `journal`
- `room`: rows from `room`
- `board`: rows from `message_board`
- `calendar`: rows from `calendar_pages`
- `mem_note`: rows from `shenyu_mem_notes`
- `notebook`: rows from `shenyu_notebook`

`atomic_memories` and `meta_summaries` are not exposed through the public recall source filter. `note` is accepted only as a backward-compatible alias for old recall index rows; new mem-note rows are indexed as `mem_note`.

Required Supabase migrations:

- `supabase/migrations/20260526_shenyu_recall_index.sql`
- `supabase/migrations/20260527_shenyu_recall_keyword_rpc.sql`
- `supabase/migrations/20260527_shenyu_recall_vector_rpc.sql`

Recall-related env vars:

```text
ENABLE_RECALL_AUTO_SYNC=false
RECALL_CANDIDATE_LIMIT=160

ENABLE_RECALL_EMBEDDINGS=false
ENABLE_RECALL_EMBEDDING_WORKER=true
RECALL_EMBEDDING_WORKER_INTERVAL_SECONDS=900
RECALL_EMBEDDING_WORKER_BATCH_SIZE=50
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
```

When `ENABLE_RECALL_EMBEDDINGS=true`, the gateway can fill pending embeddings. The in-process worker runs every `RECALL_EMBEDDING_WORKER_INTERVAL_SECONDS` seconds and embeds up to `RECALL_EMBEDDING_WORKER_BATCH_SIZE` pending rows per pass. This keeps normal `shenyu_recall` calls fast: live search reads the index and only embeds the query vector when vector recall is enabled; it does not rebuild or backfill the whole index during a user request.

For manual backfill or one-off repair, run:

```bash
python scripts/embed_recall_pending.py --batch-size 50 --sleep 0.5
```

To inspect source coverage before or after a rebuild:

```bash
python scripts/inspect_recall_sources.py
```

## Cold Start Layer

Cold start bridges context across windows without reintroducing the retired frozen context layer. It now behaves like
the normal client window at the start of a new thread: the latest previous request snapshot is inserted as ordinary
user/assistant history before the new thread's messages, then it shrinks as the new thread grows.

Flow:

1. `_prepare_messages()` opens the session and stores a `request_context_snapshot`.
2. `_maybe_prepare_cold_start_snapshot()` checks whether the request is a new window or a stale window.
3. It calculates the gap between the target window and the current client message count.
4. It reads recent previous request snapshots via `latest_cross_session_context()`.
5. It dedupes overlapping `user`/`assistant` messages and inserts only the number needed to fill that gap.
6. Once the new thread reaches the target window size, the bridge automatically stops.

Config:

- `ENABLE_COLD_START`
- `COLD_START_MESSAGE_LIMIT` (optional; blank follows `MAX_CLIENT_MESSAGES`)
- `COLD_START_IDLE_MINUTES`
- `MAX_CLIENT_MESSAGES`

Inspection endpoints:

- `GET /api/gateway/overview`
- `GET /api/gateway/cold-start/preview`
- `GET /api/gateway/sessions/{session_tag}`

## Calendar Layer

The calendar layer writes private day/week/month memory pages. It is manually triggered from the admin UI.
Before ordinary chat replies, the gateway also injects a compact calendar memory block when Supabase is configured:
by default latest 3 day pages, latest 1 week page, and latest 1 month page. Day/week/month injection can be
enabled or disabled independently, and each period has its own injected-page limit. Chat context injection includes
the stored `digest` only, without the listing `summary` and without additional digest truncation.

Tables:

- `calendar_prompt_configs`: active prompt versions for day/week/month.
- `calendar_pages`: versioned generated pages.
- `calendar_generation_runs`: generation logs and source refs.

Source collection:

- Day pages read the latest 10 `request_context_snapshots`, latest 8 normal heartbeats, recent day/week/month pages, and a small surface pass.
- Week pages read the latest 8 context snapshots, latest 5 normal heartbeats, and recent day/week/month pages.
- Month pages read the latest 6 context snapshots, latest 5 normal heartbeats, and recent day/week/month pages.

Chat injection:

- `ContextBuilder` reads latest calendar pages into the `slow` layer.
- `CALENDAR_INJECT_DAY`, `CALENDAR_INJECT_WEEK`, and `CALENDAR_INJECT_MONTH` toggle period injection.
- `CALENDAR_CONTEXT_DAY_LIMIT`, `CALENDAR_CONTEXT_WEEK_LIMIT`, and `CALENDAR_CONTEXT_MONTH_LIMIT` set injected counts.
- Only full stored `digest` values are rendered into chat context; `summary` remains for calendar listings.
- The rendered block uses short labels: `这几天`, `这周`, `这个月`.
- Missing Supabase or empty pages are skipped silently.

The active source renderer is snapshot-based. It no longer injects the retired summary/window blocks.

Endpoints:

- `GET /api/calendar/prompts`
- `POST /api/calendar/prompts`
- `POST /api/calendar/prompts/{prompt_id}/activate`
- `GET /api/calendar/month`
- `GET /api/calendar/page/{page_id}`
- `GET /api/calendar/context-snapshots`
- `GET /api/calendar/preview-sources`
- `GET /api/calendar/send-preview`
- `POST /api/calendar/generate`

## External Frontend Contracts

The separate `home-frontend` project calls a small set of gateway APIs directly from the browser. These contracts are runtime dependencies even when this repo's admin UI does not reference them.

Preserve browser access behavior:

- `/api/*` must continue to accept `?token=...` authentication as well as `Authorization`.
- `OPTIONS` requests must bypass auth so CORS preflight is not rejected.
- CORS must continue to allow `https://home.yuanuwuclaude.uk`, `https://yuanuwuclaude.uk`, `http://localhost:8005`, `http://127.0.0.1:8005`, `http://localhost:5500`, `http://127.0.0.1:5500`, and `null`.

Preserve these response contracts:

- `GET /api/gateway/heartbeats?token=...&limit=2000&order=asc&scope=normal|hisense` returns `heartbeats`; each item must include at least `content` and `created_at`. `scope=normal` reads `heartbeat_entries`; `scope=hisense` reads `hisense_heartbeat`.
- `GET /api/calendar/month?token=...&month=YYYY-MM` returns `grid`; each day item must keep `date`, `day`, `in_month`, `has_day`, `has_week`, and when present `day_page.id/title/summary/status`.
- `GET /api/calendar/page/{page_id}?token=...` returns at least `id`, `title`, `summary`, and `content`.

## Mem Note Layer

Mem notes are small personal notes, separate from event memories and calendar pages.

Two switches control it:

- `INJECT_MEM_NOTES`: before a reply, search active mem notes and inject relevant hits in `volatile`.
- `ENABLE_INLINE_MEMORY_CAPTURE`: after a reply, capture explicit `[mem]...[/mem]` notes.

Explicit inline memory flow:

1. Assistant reply is filtered before it reaches the client.
2. Only closed `[mem]...[/mem]` blocks are removed from visible text.
3. Each captured note is inserted into `shenyu_mem_notes` as `captured`.
4. Inline notes are stored as one paragraph. Type, trigger, keywords, status, and cooldown are filled later.
5. The note types are `她为我做的事`, `我为她做的事`, `关于她的事实`, `关于我的事`, `心里那一档`, and `承诺`.
6. `shenyu_write_mem_note` writes an intentional note directly as `active`. If type or trigger is missing, the writer fills safe defaults so the note can surface immediately.

Search/injection flow:

1. `ContextBuilder` calls `MemNoteService.search_notes()` when enabled.
2. Active rows are matched mainly by manually filled `trigger_text` and `trigger_keywords`, with content as a fallback.
3. Cooldown blocks frequent repeats. Relevant hits are rendered cleanly in `volatile`, without tier/importance/heat.

Endpoints:

- `GET /api/gateway/mem-notes/search`
- `GET /api/gateway/mem-notes`
- `PATCH /api/gateway/mem-notes/{note_id}`
- `DELETE /api/gateway/mem-notes/{note_id}`
- `GET /api/gateway/legacy-atomic-memories`

Admin UI notes:

- Mem0 is now a standalone admin area instead of being embedded in the generic config page.
- The Mem0 page includes:
  - controls for explicit `[mem]` capture and mem-note injection
  - the mem-note attribute workflow for Supabase `shenyu_mem_notes`
  - read-only old `atomic_memories` lookup for manual migration

Current implementation details:

- Automatic/model-based extraction is disabled.
- `[mem]` notes are stored verbatim as `captured` rows.
- Prompt-preset and manual-extract endpoints have been removed.

## Private Capture Empty Reply Fallback

Closed private assistant blocks are removed from visible replies:

- `<heartbeat>...</heartbeat>` is stored in SQLite heartbeat tables.
- `[mem]...[/mem]` is captured into Supabase `shenyu_mem_notes` when inline capture is enabled.
- `shenyu_write_mem_note`, including through `shenyu_gateway_tool`, writes a Supabase mem note during the internal tool loop.

If all visible text is removed and there are no client-executable tool calls, the gateway sends a short visible fallback instead of returning an empty successful assistant message. This prevents clients and automated workflows from treating a successful private capture as a malformed empty response.

Fallback text is generated in `gateway.py` by `_finalize_assistant_private_content()`, `_private_capture_fallback_text()`, and `_is_free_time_fallback_context()`:

- free-time workflow context: `沈予在自由时间 · 已存 heartbeat`, `沈予在自由时间 · 已存 mem`, or `沈予在自由时间 · 已存 heartbeat + mem`
- generic context: `沈予已记录 · 已存 heartbeat`, `沈予已记录 · 已存 mem`, or `沈予已记录 · 已存 heartbeat + mem`
- if no private capture type is detected: `沈予已记录。`

Free-time detection is intentionally broad. It matches current Operit proxy reminders such as `<proxy_sender name="沈予"/> 【提醒】予予现在是自由时间`, any text containing `自由时间`, and explicit `free_time` / `free-time` markers. Prefer adding a stable workflow marker or header in future clients if this workflow expands.

For debugging, check `GET /api/gateway/logs` or `GET /api/gateway/logs/{id}`. When the fallback fires, `empty_visible_response_fallback` is `true` and `empty_visible_response_fallback_detail` records the generated `text`, stored `kinds`, and context (`free_time` or `generic`).

Request log response text fields:

- `response_preview` is a short list-friendly preview and may be truncated.
- `response_full` is retained in detail logs when `GATEWAY_LOG_FULL_PAYLOADS` is enabled. The admin Response tab prefers `response_full` and falls back to `response_preview`.
- `client_disconnected` means the gateway detected the downstream client had gone away while a stream/tool loop was still running. Empty-delta keepalives are used to reduce false disconnects through clients or proxies that ignore SSE comments.

## Configuration

Important environment variables:

```text
UPSTREAM_URL=https://api.treegpt.cc
ANTHROPIC_API_KEY=
UPSTREAM_PROTOCOL=openai
UPSTREAM_PROXY=
UPSTREAM_TRUST_ENV=false
HISENSE_UPSTREAM_URL=
HISENSE_API_KEY=
HISENSE_PROTOCOL=

CALENDAR_UPSTREAM_URL=
CALENDAR_API_KEY=
CALENDAR_PROTOCOL=auto
CALENDAR_MODEL=claude-opus-4-7

ENABLE_COLD_START=true
COLD_START_MESSAGE_LIMIT=
COLD_START_IDLE_MINUTES=120
MAX_CLIENT_MESSAGES=

INJECT_MEM_NOTES=false
ENABLE_INLINE_MEMORY_CAPTURE=false

DEFAULT_SURFACE_LIMIT=3

ENABLE_GATEWAY_TOOLS=false
ENABLE_MEM0_MANAGEMENT_TOOLS=false
EXPOSE_SUPABASE_TOOLS=true
GATEWAY_TOOL_MODE=broker
MAX_INTERNAL_TOOL_ROUNDS=3
```

`UPSTREAM_PROXY` is optional. Use it when the gateway host can only reach the upstream API through a local proxy, for example:

```text
UPSTREAM_PROXY=http://127.0.0.1:7897
```

When `UPSTREAM_PROXY` is set, upstream LLM requests use that explicit proxy and ignore ambient proxy environment variables. If you prefer to inherit `HTTP_PROXY` / `HTTPS_PROXY` from the process environment, leave `UPSTREAM_PROXY` empty and set `UPSTREAM_TRUST_ENV=true`.

Cloudflare Tunnel only handles inbound traffic to the gateway. It can make `https://your-domain` reach `localhost:8010`, but it does not by itself make the gateway's outbound connection to `UPSTREAM_URL` work. If requests fail with `无法连接上游 ... All connection attempts failed`, check the gateway machine's outbound route to the upstream host, local proxy/TUN mode, and `UPSTREAM_PROXY`.

## Running

The gateway defaults to port `8010`. Override it with `PORT` when needed.

### Local development

```bash
# Terminal 1: Python backend
python gateway.py

# Terminal 2: Vue frontend with hot reload
cd admin && npm run dev
```

Open `http://localhost:5173` for frontend dev — Vite proxies `/api` and `/health` to the backend on `8010`. Edit `.vue` files and see changes instantly.

### Build for production (Coolify / server deploy)

```bash
# Install backend dependencies
pip install -r requirements.txt

# Build the admin frontend
cd admin && npm ci && npm run build && cd ..

# Start the gateway (serves built admin from dist/)
python gateway.py
```

UI routes:

```text
http://localhost:8010/admin
```

`/` redirects to `/admin`, so the admin login is the single main browser entrypoint. The same gateway key protects `/admin` and `/api/*`.

`/admin` is the formal Vue/Vite admin app. It is organized by feature:

- `admin/src/api/config.ts`: gateway and upstream configuration.
- `admin/src/api/mem0.ts`: Mem config, mem-note review APIs, and old atomic read-only lookup.
- `admin/src/api/sessions.ts`: local SQLite session browser.
- `admin/src/api/logs.ts`: request log list and detail APIs.
- `admin/src/api/calendar.ts`: calendar prompts, month grid, previews, and generation.
- `admin/src/api/hisense.ts`: Hisense preview, notebook CRUD, and session APIs.
- `admin/src/views/ConfigView.vue`: configuration page.
- `admin/src/views/Mem0View.vue`: Mem capture/injection controls, mem-note attribute workflow, and old atomic read-only lookup.
- `admin/src/views/SessionsView.vue`: session inspection page.
- `admin/src/views/LogsView.vue`: request log viewer with expandable detail tabs.
- `admin/src/views/CalendarView.vue`: day/week/month calendar memory workflow.
- `admin/src/views/HisenseView.vue`: Hisense slow-layer preview, notebook management, and session history.
- `admin/src/components/AppShell.vue`: shared admin navigation and layout.

The old single-file `/debug` console has been retired. User-facing admin features should go into `admin/src/views/*` and `admin/src/api/*`.

After backend or admin build changes, restart the running gateway process. The process serves files loaded from disk at startup, so an already-running server may still show the old `/admin` page until it is restarted.

For frontend development, run Vite separately. Its proxy already targets the backend on `localhost:8010`:

```bash
cd admin
npm run dev
```

Docker builds the admin UI first, then serves the Python gateway with the built `/admin` assets:

```bash
docker build -t shenyu-gateway .
docker run --env-file .env -p 8010:8010 shenyu-gateway
```

## Verification Checklist

- Search the active code paths for retired summary/window env vars and the removed short-lived notes table; they should not appear.
- `GET /api/gateway/context/preview` should show `stable`, optional `slow`, and `volatile`.
- `GET /api/calendar/send-preview?...` should show `Current Client Context Snapshots`, not rolling/frozen blocks.
- `GET /api/gateway/logs` should show prompt cache breakpoints and cold-start metadata.
- `GET /api/gateway/logs/{id}` should show `response_full` for retained payloads; the list view should keep using short previews.
- Run `python -c "import test_gateway_streaming as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]"` after streaming/tool-loop edits when `pytest` is unavailable.
- Run `python -c "import test_upstream_adapter_stream as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]"` after upstream stream adapter edits when `pytest` is unavailable.
- Run `cd admin && npm run build` after admin UI edits.
- Run `python -m py_compile gateway.py shenyu_gateway/*.py` after edits.

## DevOps Plan | 部署计划

### Deploy to Coolify

1. Push this repo to a git remote (GitHub/GitLab).
2. In Coolify, create a new service → select this repo.
3. Use the `Dockerfile` — Coolify detects it automatically.
4. Set environment variables in Coolify's dashboard (`.env` content).
5. Port mapping: `8010:8010`.
6. Coolify auto-deploys on every git push.

### Frontend workflow

| Environment | Command | URL |
|---|---|---|
| Local dev | `cd admin && npm run dev` | `http://localhost:5173` (hot reload) |
| Production | `cd admin && npm run build` → served by Python from `dist/` | `https://your-domain/admin` |

**Before each deploy to Coolify:**
1. Make frontend changes in `.vue` files.
2. Run `cd admin && npm run build` to update `dist/`.
3. Commit and push — Coolify picks up the new built assets.

### Future improvements (when needed)

- GitHub Action to auto-build `admin/` on push, so `dist/` doesn't need to be committed.
- Coolify build step to run `npm ci && npm run build` inside the Dockerfile instead of committing `dist/`.
- Add `CALENDAR_UPSTREAM_URL` etc. env var passthrough to the admin config page.
