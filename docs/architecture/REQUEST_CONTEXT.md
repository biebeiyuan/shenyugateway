# 请求、上下文与持久化参考

本文由原 README 的现行子系统章节迁出，负责请求链、上下文、缓存、存储和归档细节。总体分区和风险状态分别见 `SYSTEM_ZONES.md` 与 `AUDIT_MATRIX.md`。

## Context Layers

Context is assembled in the order Shenyu should wake into it:

| Layer | Placement | Contents | Cache policy |
|---|---|---|---|
| request tools | request tools | client tools + `shenyu_*` / `supabase_*` tools | no dedicated breakpoint |
| `stable` | start of the system prefix | stable charter, wake welcome message, and the memory-island reading policy | covered by `system.end` |
| `slow` | system prefix after `stable` | calendar memory, Hisense notebook/recap | covered by `system.end` |
| `heartbeat` | system prefix after `slow` | `## 我之前的心跳` and optional Hisense heartbeat block | covered by `system.end` |
| `tool_policy` | system prefix after heartbeat | compact gateway/client tool reminder rendered as `## 工具怎么用` | covered by `system.end` |
| `format` | end of the system prefix | heartbeat and star format instructions | `system.end` uses the last non-empty system layer |
| `mem` | between fixed older history and the recent chat tail | stateful star/Mem memory island | breakpoint before and at the end of the island |
| client history | after the system prefix | chunk-trimmed client messages and an optional cold-start bridge | rolling-tail breakpoint when a slot is free |
| current user | latest user message | current request | no breakpoint |

The retired rolling and frozen context layers have been removed from the active flow. Their legacy SQLite tables are only cleaned up during session deletion when they exist in an older database.

`GATEWAY_TOOL_MODE=broker` is the default for normal threads and exposes one compact `shenyu_gateway_tool` dispatcher that calls the same gateway-native tools with fewer schema tokens. Broker calls should set `tool` to the full gateway tool name, including the `shenyu_` or `supabase_` prefix, and put the selected tool's arguments in the `params` object, not a JSON-encoded string. The old `arguments` field remains compatible. Use `full` when strict per-tool parameter guidance matters more than prompt size.

`GATEWAY_TOOL_SURFACE=daily` keeps broker mode but narrows the broker enum/description to daily hand tools: stars, recall, calendar, heartbeat, mem notes write/search, notebook, and conflict books. `CLIENT_TOOL_SURFACE=daily` filters client-provided tools to the normal desktop set (`gateway`, `read_file`, `visit_web`, `package_proxy`, room, and coread tools), while `none` hides client tools entirely. These surface filters do not apply room tools as a broker; room mode exposes direct `room_*` tools for the currently visible doors.

## Prompt Cache

Prompt cache breakpoints are controlled independently for each upstream payload format:

- `ENABLE_OPENAI_CACHE_CONTROL=true` enables markers on OpenAI-compatible payloads.
- `ENABLE_ANTHROPIC_CACHE_CONTROL=true` enables markers on native Anthropic payloads.
- `OPENAI_CACHE_TTL=5m` keeps the compatibility-first default for relays that only accept the basic marker.
- `ANTHROPIC_CACHE_TTL=1h` keeps native Anthropic cache entries alive across normal chat pauses.

Both formats default to enabled. Their switches and TTLs can be changed independently in the admin configuration page. OpenAI-compatible relays still need to support the Anthropic-style `cache_control` extension; set their TTL to `1h` only when the relay accepts the `ttl` field. A one-hour write costs more than a five-minute write, but repeated reads are cheaper and the longer lifetime fits conversations whose turns are often more than five minutes apart.

With a memory island and enough history, the gateway uses up to four logical breakpoints:

```text
system.end
history.before_island
memory_island.end
current_user.end
```

The concrete JSON paths differ between Anthropic and OpenAI-compatible payloads, but both adapters use the same logical boundaries. If the island changes, the island-end breakpoint is rewritten while the prefix before the island can still hit. For pure text, the final breakpoint stays on the current user's last content block. When the retained client window contains Operit extra-bundle attachments, it moves to the user turn immediately before the newest three user turns; image-only windows use the turn before the newest two. Those recent turns remain fully visible to the model but stay outside the stable cached prefix because attachment and image retention can rewrite them on later requests. Gateway tool-loop continuations still mark the latest tool result instead of applying the user-turn guard.

Use `python scripts\vps_gateway_logs.py cache` for a content-free timeline of cache hits, request gaps, configured TTLs, image retention, epoch resets, and memory-island rewrites. It defaults to the local `vps` SSH alias on Windows and automatically follows Coolify container-name changes after a deployment.

`MAX_CLIENT_MESSAGES` is the base window size `L`. The overflow block is approximately 20% of `L`, rounded to a multiple of four and clamped to 20–40 messages. The window grows to high-water `H = L + overflow`, then trims once at a complete human/tool turn boundary back toward `L`. Between trims, the retained history start and memory-island anchor remain fixed. Active client tool continuations defer a high-water trim so a tool call cannot be separated from its result. Changing `MAX_CLIENT_MESSAGES`, rebuilding a branch, or starting a new window creates a new context epoch. Cold-start bridge history uses the same effective window size.

Window and island decisions are written without message content to SQLite. Inspect them with:

```bash
python scripts/context_window_observer.py --db data/shenyu_gateway.db
```

Real cache reporting still depends on the upstream or OpenAI-compatible relay honoring and reporting `cache_control`. A positive value in either field is evidence of a provider-reported read:

```text
usage.prompt_tokens_details.cached_tokens > 0
```

or the normalized gateway log field:

```text
cache_usage.cache_read_input_tokens > 0
```

`prompt_cache.enabled` only means the gateway inserted configured breakpoints. A missing cache usage field is provider unknown, not proof of a cache miss. `cache_usage` aggregates provider-reported read/write values and must not be used to infer an exact cross-provider hit rate or bill savings.

## Streaming And Tool Calls

The gateway has two streaming paths:

- Plain pass-through streaming: when no gateway-managed tools are exposed for a request, `_stream_chat()` forwards upstream chunks while filtering private `<heartbeat>` blocks from visible output.
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

Mixed gateway/client transcript rules:

- New responses must not generate `<gateway_tool_results>`, XML wrappers, or raw JSON summaries in `assistant.content`.
- When one assistant turn contains both gateway-native and client-executable tool calls, the gateway executes its native calls, logs the tool audit rows, and stores a hidden pending transcript in SQLite.
- The response sent back to the client keeps only the client-executable `tool_calls`. The client then runs those tools using normal OpenAI tool protocol.
- On the next request, before calling the upstream model, the gateway matches the client's returned tool-call ids against `pending_gateway_tool_turns`. If matched, it rebuilds the upstream transcript as: original mixed assistant message, hidden gateway tool result messages, then the client's tool result messages.
- Native Anthropic thinking/signature blocks are retained only inside an unfinished tool turn. The gateway restores them only when the session, client tool-call ids, visible assistant text, tool names, and tool arguments still match; roll/edit/branch mismatches keep the client history unchanged. Opaque signature and redacted-thinking data are never written into readable request logs.
- `ANTHROPIC_AUTO_THINKING_EFFORT` accepts empty, `max`, or `xhigh`. Empty sends no `output_config.effort`; a tool continuation pins the effort used by its first round so an admin change applies only to the next new turn. `xhigh` is not compatible with Claude Opus 4.6.
- Pending mixed transcripts are marked consumed only after the upstream request succeeds. If a match is not found, the gateway logs the miss and forwards the client history unchanged.
- Existing old history that already contains `<gateway_tool_results>` is not migrated or filtered. The fix is forward-only: new code should not create that block again.

Adding ordinary gateway-native tools should not require changes to the streaming loop. Add the schema/name dispatch in `shenyu_gateway/tool_registry.py` and the behavior in `shenyu_gateway/gateway_tools.py`. Only update streaming/protocol code when adding a new upstream protocol, a tool whose execution progress must stream to the client, or a non-gateway client tool with special forwarding semantics.

`shenyu_gateway/upstream_adapter.py` normalizes upstream stream protocols. Anthropic `tool_use` / `input_json_delta` chunks are converted into OpenAI-compatible `tool_calls` deltas, and completion-to-SSE conversion can skip duplicate role chunks and split large final content into smaller events.

## Tool Error Log

When a gateway-native tool call fails, the gateway records the failure in SQLite `tool_error_log` and surfaces it in the admin **工具报错** page (`/admin/#/tool-errors`). The point is to answer one question: *where is Shenyu's tool use going wrong, and is it our bug or a malformed call?*

Each row is classified into one `error_kind`:

- `exception`: a real server-side crash (traceback / attribute error / type error). Gateway bugs to fix.
- `config`: a missing or disabled dependency (`... not configured`, `embedding api is not configured`, `not available`). Fix by configuration, not code.
- `validation`: the model called the tool wrong — unknown/deprecated tool name, bad arguments, or a rejected broker target. These point at tool schema/description problems, i.e. Shenyu being led astray.

Classification lives in `_classify_tool_error()` (`shenyu_gateway/tool_loop.py`) and prefers an `error_kind` the handler declared explicitly; genuine exceptions are tagged at the `except` site rather than guessed, and a small keyword heuristic is only a fallback. The config-phrase list is `TOOL_ERROR_CONFIG_PHRASES` at the top of `shenyu_gateway/store/_admin.py`. The legacy `error_source` column is retained and derived from `error_kind`.

The admin view groups errors into three tabs — `全部` / `真报错` (`exception` + `config`) / `调用被拒` (`validation`) — and expands a `调用被拒` row to show `args_json` (what Shenyu actually passed) beside `error_text` (what was expected). That side-by-side is the evidence base for tightening tool schemas so Shenyu stops mis-calling them.

- Table: SQLite `tool_error_log`. The `error_kind` column is auto-migrated on startup via `_ensure_column` (existing rows default to `unknown`); no manual migration or new env var is required.
- API: `GET /api/gateway/tool-errors?limit=50&kind=<exception|config|validation>` (`kind` optional; the view currently filters client-side).
- Frontend: `admin/src/views/ToolErrorsView.vue`, `admin/src/api/toolErrors.ts`.

The deprecated compatibility names `shenyu_ask_memory`, `shenyu_search_primary_texts`, and `shenyu_get_meta_summaries` are now rejected with `error_kind=validation` and a redirect to `shenyu_recall`, instead of silently forwarding. The broker `shenyu_gateway_tool` schema exposes only `tool` + `params` (the old `arguments` field is still accepted server-side but no longer advertised).

## SQLite Runtime State

SQLite stores only gateway runtime state:

- `gateway_sessions`
- `gateway_messages`: local message stream for inspection only. It is not the cold-start source of truth.
- `request_context_snapshots`: recent client context windows. Calendar generation and cold-start both depend on this.
- `raw_request_windows`: recent untrimmed client request windows for backup/export/debugging.
- `cold_start_snapshots`: bounded bridge packages created from recent context snapshots.
- `pending_gateway_tool_turns`: short-lived hidden mixed tool transcripts. It stores the original mixed assistant tool-call message, gateway tool result messages, client tool-call ids, and consumed/expiry timestamps.
- `cache_entries`: short-lived gateway cache.
- `heartbeat_entries`: global private heartbeat notes captured from `<heartbeat>...</heartbeat>` or written manually in admin. `session_id` is retained as the source session, but runtime injection reads the shared global pool.
- `hisense_heartbeat`: private heartbeat notes captured from Hisense sessions. These use the same parser as normal heartbeats but are stored and injected separately.

`request_context_snapshots` is the replacement for the old rolling/frozen context path. Each request stores the trimmed client window before gateway layers are inserted. Calendar generation and cold-start bridge both read these snapshots. `raw_request_windows` stores the original client payload window before any gateway-side trimming and is kept separate so cold-start stays bounded.

### SQLite Retention And Cleanup

SQLite is intentionally kept as a small online runtime database. Supabase remains the durable memory/content store.

The default database path is `./data/shenyu_gateway.db`, which resolves to `/app/data/shenyu_gateway.db` in the production container. The Dockerfile does not declare a volume. Coolify must mount a persistent volume for `/app/data` (or for the directory selected by `GATEWAY_DB_PATH`) if SQLite state is expected to survive a container replacement. Admin-written `/app/.env` overrides have the same container-lifetime limitation unless that file is also persisted; Coolify dashboard environment variables remain the deployment source outside the container.

Admin configuration updates currently store secret values in both `.env` and SQLite `config_overrides` so runtime settings can survive the deployment patterns this gateway already supports. Treat both paths and their backups as secret-bearing assets: restrict filesystem/volume access, do not export the database casually, and rotate credentials after suspected exposure. The Admin API never returns those values. Replacing this dual storage requires an external secret store and a migration plan; do not add reversible application-managed “encryption” with a key stored beside the database.

### Content Copy Matrix

| Data product | Content retained | Default bound | Purpose | Session delete |
|---|---|---|---|---|
| `gateway_messages` | prepared user/assistant text, tool args and result summaries | newest 1500 rows per session | local inspection, lineage and export | deleted |
| `raw_request_windows` | compacted original client history; image bytes replaced by fingerprints | newest 3 windows per session | history event classification, backup/debug | deleted |
| `request_context_snapshots` | trimmed client-visible history before pending transcript reinjection | newest 3 snapshots per session | cold start and calendar source | deleted |
| `cold_start_snapshots` | copied source snapshot messages | newest 20 completed snapshots; active preserved | bounded cross-thread bridge | deleted |
| `pending_gateway_tool_turns` | original mixed assistant call and gateway tool result messages | active until consumed or 24h expiry | reconstruct gateway/client mixed turns | deleted |
| `tool_error_log` / `room_trace` | tool args/errors or Room diagnostic text | explicit table-specific limits/cleanup | diagnostics | deleted |
| request-log deque | summaries by default; full messages/payload/response only with `GATEWAY_LOG_FULL_PAYLOADS=true` | 30 requests, process memory | live debugging | process restart clears it |
| helper `--save` JSON | one explicitly exported redacted log detail | operator-managed file | offline debugging | independent local file |
| Supabase `shenyu_chat_archive` | deduplicated visible user/assistant text | durable; no automatic session-delete coupling | long-term recall/archive | not deleted |

These copies are not interchangeable: raw windows classify client history, snapshots feed cold start/calendar, pending rows preserve tool protocol, and the archive is the durable recall source. Reducing copies requires replacing those responsibilities first, not deleting tables based only on duplicate text.

Default online retention:

- `GATEWAY_MESSAGE_RETENTION=1500`: keep the newest local message rows per session. These rows are for admin inspection and export, not for cold-start injection.
- `GATEWAY_CONTEXT_SNAPSHOT_RETENTION=3`: keep the newest context snapshots per session. Do not set this to `0`; cold-start and calendar source collection need recent snapshots.
- `GATEWAY_COLD_START_RETENTION=20`: keep recent cold-start snapshots per session. Cleanup only removes old snapshots whose `injected_count >= max_injections`, so active cold-start bridges are preserved.
- Consumed or expired `pending_gateway_tool_turns` are removed during cleanup. Unconsumed pending rows are kept until expiry so a client can return its tool result in the next request.
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
- It is safe to prune consumed or expired `pending_gateway_tool_turns`; do not delete fresh unconsumed pending rows while a client tool turn may still be in flight.
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
- `windowsill`
- `shenyu_mem_notes`
- `shenyu_stars`
- `shenyu_star_links`
- `shenyu_star_recall_runs`
- `shenyu_star_recall_candidates`
- `shenyu_star_feedback`
- `shenyu_star_activations`
- `atomic_memories` (legacy read-only migration source)

The short-lived notes table is no longer used by gateway code.

The mem review UI reads and updates Supabase `shenyu_mem_notes`. The star review UI reads and updates the `shenyu_stars` family of tables. The old `atomic_memories` table is only exposed through a read-only lookup for manual migration. SQLite only provides local request/session context.

## Windowsill

`windowsill` is Shenyu's own writing place for essays, journal entries, moods, and reflections, without the category structure of `journal`. Apply `supabase/migrations/20260710_create_windowsill.sql` before enabling the tools.

- `shenyu_windowsill_write(content, title?, mood?)` leaves a new entry. PostgreSQL generates `id` and `created_at`; neither is supplied by the model.
- `shenyu_windowsill_list(mood?, limit?)` returns recent entries, newest first, with optional exact mood filtering.
- Successful writes are indexed immediately; the periodic recall reconciliation worker repairs any missed write later.
- The table is intentionally reached through these dedicated tools. Raw Supabase tools remain an explicit maintenance/debug surface rather than a daily Shenyu surface.

## Recall Index

`shenyu_recall` is the unified search entrypoint for old context. It returns a small matched excerpt plus `source_type` and `source_id`; use `shenyu_recall_read(source_type, source_id)` only when the full original is needed. It never exposes rank scores or match explanations to Shenyu. Full candidate and selection traces stay in gateway logs.

Recall accepts `mode=auto|exact|fuzzy|mood|verbatim`. `auto` only switches on strong intent signals and otherwise behaves as `fuzzy`:

- `exact`: one primary original, optionally one strongly related star/mem note/heartbeat.
- `fuzzy`: up to three primary excerpts plus at most one strongly related federated item; default total limit 4.
- `mood`: at most three sparse results, with stars/heartbeats/mem notes eligible as first-class lanes.
- `verbatim`: explicitly searches `shenyu_chat_archive`; raw chat does not enter ordinary recall.

Ordinary memories search across historical session tags. `session_tag` remains provenance and a possible future tie-breaker, not a visibility boundary. Rows explicitly marked `private` or `hidden` still require an exact session match.

Indexed public source types:

- `memory`: rows from `memories`
- `journal`: rows from `journal`
- `windowsill`: personal writing from `windowsill`
- `heartbeat`: settled normal-scope rows from `shenyu_heartbeat_archive`
- `room`: rows from `room`
- `board`: rows from `message_board`
- `calendar`: rows from `calendar_pages`
- `notebook`: rows from `shenyu_notebook`

Stars and active mem notes are federated through their existing specialized rankers instead of being duplicated into the public document source filter. Recent unsettled normal heartbeats are scored from SQLite; settled heartbeats are indexed from the Supabase archive. `atomic_memories` and `meta_summaries` remain internal/legacy sources.

`shenyu_mem_notes` is the single canonical light-memory table. Legacy rows and v2 rows are not separate pools: legacy trigger/content fields remain readable, while missing `summary` and `memory_kind` receive a non-destructive runtime projection. Automatic mem-note recall is cross-session for normal chat. Only active notes enter the semantic index; captured and archived notes remain available to management/search tools without automatically surfacing.

Required Supabase migrations:

- `supabase/migrations/20260526_shenyu_recall_index.sql`
- `supabase/migrations/20260527_shenyu_recall_keyword_rpc.sql`
- `supabase/migrations/20260527_shenyu_recall_vector_rpc.sql`

Recall-related env vars:

```text
ENABLE_RECALL_AUTO_SYNC=false
RECALL_CANDIDATE_LIMIT=160
RECALL_VECTOR_MIN_SCORE=0.42
ENABLE_RECALL_SYNC_WORKER=true
RECALL_SYNC_WORKER_INTERVAL_SECONDS=900

ENABLE_RECALL_EMBEDDINGS=false
ENABLE_RECALL_EMBEDDING_WORKER=true
RECALL_EMBEDDING_WORKER_INTERVAL_SECONDS=900
RECALL_EMBEDDING_WORKER_BATCH_SIZE=50
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
```

The in-process recall worker first reconciles source tables into `shenyu_recall_index` every `RECALL_SYNC_WORKER_INTERVAL_SECONDS`, then embeds pending rows when embeddings and a valid API key are enabled. It embeds up to `RECALL_EMBEDDING_WORKER_BATCH_SIZE` rows per pass. Request-time auto sync remains an emergency fallback rather than the freshness strategy.

`BAAI/bge-m3` remains the compatibility default: it is multilingual, produces the existing 1024-dimensional vectors, and handles inputs up to 8192 tokens. A model change requires a measured recall A/B run and full re-embedding; do not mix vectors from different models in the same index merely because a newer model exists.

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
the normal client window at the start of a new thread: a bounded snapshot from one selected source thread is inserted
as ordinary user/assistant history before the new thread's messages, then it shrinks as the new thread grows.

`POST /api/gateway/cold-start/preview` is also the freezing endpoint used by the admin UI. The daily cold-start form
binds the latest source thread's effective window to an explicit new session tag. The lightweight form additionally
accepts an explicit source thread and message limit. Both forms return a header such as
`X-Shenyu-Session-Tag: 7.12`; the first request using that tag consumes the frozen bridge once. If no frozen snapshot
was prepared, a previously unseen session tag still automatically chooses the latest source thread with a request
context snapshot. Existing sessions never trigger cross-thread cold start merely because they were idle.

Flow:

1. `_prepare_messages()` opens the session and stores a `request_context_snapshot`.
2. `_maybe_prepare_cold_start_snapshot()` first reuses a frozen snapshot bound to the target session.
3. It calculates the gap between the target window and the real current client message count.
4. If the session is new and has no frozen snapshot, it chooses the latest source thread automatically.
5. It inserts only the number needed to fill the current live gap.
6. After a successful bridge injection, the one-shot snapshot becomes inactive.

Config:

- `ENABLE_COLD_START`
- `COLD_START_MESSAGE_LIMIT` (optional; blank follows `MAX_CLIENT_MESSAGES`)
- `MAX_CLIENT_MESSAGES`

Inspection endpoints:

- `GET /api/gateway/overview`
- `GET /api/gateway/cold-start/preview`
- `POST /api/gateway/cold-start/preview`
- `GET /api/gateway/sessions/{session_tag}`

## Calendar Layer

The calendar layer writes private day/week/month memory pages. It is manually triggered from the admin UI.
Before ordinary chat replies, the gateway also injects a compact calendar memory block when Supabase is configured:
by default latest 3 day pages, latest 1 week page, and latest 1 month page. Day/week/month injection can be
enabled or disabled independently, and each period has its own injected-page limit. Chat context injection includes
the stored `content` body only, without the listing `summary` or short `digest`.

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
- Only stored `content` bodies are rendered into chat context; `summary` remains for calendar listings and `digest` remains a short memory snippet.
- The rendered block uses labels: `recent days`, `this week`, `this month`.
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

## Durable Archive Layer

SQLite holds only rebuildable runtime state. Anything whose loss would hurt lives in Supabase. Three archive subsystems enforce this:

### Heartbeat archive (disaster recovery)

`shenyu_heartbeat_archive` in Supabase is the durable copy of both SQLite heartbeat pools. The worker (`shenyu_gateway/heartbeat_archive.py`):

- syncs heartbeats only after a settle window (`HEARTBEAT_ARCHIVE_SETTLE_HOURS=6`), so manual cleanup of re-roll duplicates or runaway heartbeats done in SQLite first never reaches the archive;
- reconciles afterwards: rows deleted from SQLite after archiving are soft-deleted (`deleted_at`) in the archive, never erased;
- backfills all history automatically on first run.

SQLite stays the live read path; injection behavior is unchanged. Config: `ENABLE_HEARTBEAT_ARCHIVE`, `HEARTBEAT_ARCHIVE_SETTLE_HOURS`, `HEARTBEAT_ARCHIVE_INTERVAL_SECONDS`, `HEARTBEAT_ARCHIVE_BATCH_SIZE`.

### Chat archive (L0 source of truth)

`shenyu_chat_archive` in Supabase stores verbatim user/assistant messages, message by message, archived from the client window in `_prepare_messages()` (fire-and-forget; failures never affect chat). Dedup uses `chat_archive_seen` in SQLite (recent hashes per session_tag), so resent sliding windows archive each message once while a genuinely repeated message months later is a new event. Re-rolled replies never return in the client window, so they are naturally excluded. Threads are derived as `main` / `hisense` / custom session tags.

- Backfill from existing SQLite history: `python scripts/backfill_chat_archive.py` (idempotent; `--dry-run` to preview).
- Admin reader: `/admin` → 档案 tab; API under `/api/archive/*`.
- Config: `ENABLE_CHAT_ARCHIVE`.
- This table is the source of truth: recall indexes and conflict books are derived from it; soft-delete only.

### Conflict books（矛盾书）

Frozen verbatim excerpts of arguments, clipped by the user from the archive reader, readable and annotatable by Shenyu. Invariants enforced in `shenyu_gateway/conflict_books.py` (no API path can violate them):

- `original_text` is frozen at clip time; update paths drop it and a text-only patch is rejected.
- Shenyu's annotations are append-only with timestamps; no update or delete endpoint exists.
- Every `shenyu_conflict_read` appends a row to `shenyu_conflict_reads` and bumps `read_count`, so the shelf shows 翻过几次/最近何时.
- Books are never auto-injected as content. The only passive surface is the `## 矛盾书` shelf block (titles + status only) in the `slow` layer, toggled by `INJECT_CONFLICT_SHELF`.

Tools: `shenyu_conflict_list`, `shenyu_conflict_read`, `shenyu_conflict_annotate`. Admin UI: 档案 tab (clip flow) and 矛盾书 tab (edit title/notes/epilogue/status; soft delete). Migrations: `20260613_shenyu_heartbeat_archive.sql`, `20260613_shenyu_chat_archive.sql`, `20260613_shenyu_conflict_books.sql`.
