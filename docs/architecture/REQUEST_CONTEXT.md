# 请求、上下文与持久化参考

本文由原 README 的现行子系统章节迁出，负责请求链、上下文、缓存、存储和归档细节。总体分区和风险状态分别见 `SYSTEM_ZONES.md` 与 `AUDIT_MATRIX.md`。

## Context Layers

Context is assembled in the order Shenyu should wake into it:

| Layer | Placement | Contents | Cache policy |
|---|---|---|---|
| request tools | request tools | client tools + `shenyu_*` / `supabase_*` tools | no dedicated breakpoint |
| `stable` | start of the system prefix | stable charter, wake welcome message, and resident memory profile | covered by `system.end` |
| `slow` | system prefix after `stable` | calendar memory | covered by `system.end` |
| `heartbeat` | system prefix after `slow` | `## 我之前的心跳` | covered by `system.end` |
| `tool_policy` | system prefix after heartbeat | compact gateway/client tool reminder rendered as `## 工具怎么用` | covered by `system.end` |
| `format` | end of the system prefix | optional model-authored echo format instructions, then heartbeat and star format instructions | `system.end` uses the last non-empty system layer |
| `mem` | between fixed older history and the recent chat tail | stateful star/Mem memory island | breakpoint before and at the end of the island |
| client history | after the system prefix | chunk-trimmed client messages and an optional cold-start bridge | rolling-tail breakpoint when a slot is free |
| current user | latest user message | current request | no breakpoint |

The retired rolling and frozen context layers have been removed from the active flow. Their legacy SQLite tables are only cleaned up during session deletion when they exist in an older database.

`GATEWAY_TOOL_MODE=broker` is the default for normal threads and exposes one compact `shenyu_gateway_tool` dispatcher that calls the same gateway-native tools with fewer schema tokens. Broker calls should set `tool` to the full gateway tool name, including the `shenyu_` or `supabase_` prefix, and put the selected tool's arguments in the `params` object, not a JSON-encoded string. The old `arguments` field remains compatible. Use `full` when strict per-tool parameter guidance matters more than prompt size.

`GATEWAY_TOOL_SURFACE=daily` keeps broker mode but narrows the broker enum/description to daily hand tools: stars, recall, calendar, heartbeat, mem notes write/search, notebook, and `shenyu_books`. `CLIENT_TOOL_SURFACE=daily` filters client-provided tools to the normal desktop set (`gateway`, `read_file`, `visit_web`, `package_proxy`, room, and coread tools), while `none` hides client tools entirely. These surface filters do not apply room tools as a broker; room mode exposes only the direct tools attached to doors visible at the current charge. The shared shelf overview and `shenyu_books` entry appear together when the physical shelf door is visible.

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

Each logged breakpoint also carries a truncated SHA-256 fingerprint of the exact cacheable prefix after removing `cache_control` metadata. The fingerprint contains no recoverable message text. Identical path/fingerprint pairs across adjacent requests prove that the gateway sent the same prefix; a provider-reported miss in that case points toward upstream cache retention or routing rather than a gateway boundary move.

Every gateway-managed tool round keeps its own content-free `prompt_cache` evidence: breakpoint paths, prefix fingerprints, configured TTL, tail guard, and the number of `cache_control` markers present in the final outbound payload. This structure is safe to retain in SQLite and appears beside the round's provider-reported read/write usage. Full Messages and upstream payloads remain live-process-only and opt-in.

`MAX_CLIENT_MESSAGES` is the base window size `L`. The overflow block is approximately 20% of `L`, rounded to a multiple of four and clamped to 20–40 messages. The window grows to high-water `H = L + overflow`, then trims once at a complete human/tool turn boundary back toward `L`. Between trims, the retained history start and memory-island anchor remain fixed. Active client tool continuations defer a high-water trim so a tool call cannot be separated from its result. Changing `MAX_CLIENT_MESSAGES`, rebuilding a branch, or starting a new window creates a new context epoch. Cold-start bridge history uses the same effective window size.

Window and island decisions are written without message content to SQLite. Inspect them with:

```bash
python scripts/context_window_observer.py --db data/shenyu_gateway.db
```

The in-memory admin request log keeps a bounded display snapshot of the Memory Island selected for each request so Stars and Mem changes remain inspectable without enabling full payload retention. Star text is capped at 220 characters and Mem text at 180 characters per item. This snapshot follows the existing recent-log capacity and disappears on process restart; SQLite window/island decision records remain content-free.

Real cache reporting still depends on the upstream or OpenAI-compatible relay honoring and reporting `cache_control`. A positive value in either field is evidence of a provider-reported read:

```text
usage.prompt_tokens_details.cached_tokens > 0
```

or the normalized gateway log field:

```text
cache_usage.cache_read_input_tokens > 0
```

`prompt_cache.enabled` only means the gateway inserted configured breakpoints. A missing cache usage field is provider unknown, not proof of a cache miss. `cache_usage` aggregates provider-reported read/write values. Each round also exposes `cache_usage.total_input_tokens` for the Admin `input` badge: Anthropic totals uncached `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, while OpenAI-compatible `prompt_tokens` / Responses `input_tokens` already include the cached subset and are used without adding it again. Output tokens are excluded. When that provider-normalized denominator is reliable, `cache_read_percent = read / total_input` is the compact user-facing single-request cache rate; otherwise the UI omits the percentage. `cache_prefix_reuse_percent = read / (read + creation)` remains available as a separately labeled diagnostic in details. Neither percentage is a cross-request hit rate or bill-savings estimate.

History-event classification removes transient images and Operit extra bundles before comparing raw request windows. Text-only content is canonicalized semantically, so a plain string and an equivalent list of text blocks are the same lineage. Image expiry or client content-shape flattening must not create `history_branch`. A rolling-window head slide — the current window equals the previous window minus its oldest messages, plus optional appended tail turns, with at least 8 overlapping messages — is normal bounded-client behavior (e.g. the PWA reloading after its localStorage cap, or re-entering a thread from a gateway snapshot): it classifies as the matching append/retry event, keeps the epoch, and shifts the stored gateway window start by the slide so the retained upstream window is unchanged. A branch reset is reserved for a real edit before the active tail turn.

## Streaming And Tool Calls

The gateway has two streaming paths:

- Plain pass-through streaming: when no gateway-managed tools are exposed for a request, `_stream_chat()` forwards upstream chunks while filtering private `<heartbeat>` blocks from visible output.
- Gateway-managed tool streaming: when `shenyu_*` / `supabase_*` tools are available, `_run_internal_tool_loop_stream()` consumes upstream stream chunks directly. It intercepts gateway-native tool calls, executes them server-side, appends tool results to the working message list, and starts the next upstream round. Final natural-language replies stream to the client token by token.

Request count is still driven by model tool rounds, not by streaming itself:

- direct answer: one upstream request
- one internal tool round: one upstream request to produce the tool call, then one upstream request to produce the final answer from the tool result
- repeated internal tool rounds: one upstream request per round, bounded by `MAX_INTERNAL_TOOL_ROUNDS`

Streaming changes the connection shape, not the number of model rounds. The managed stream sends OpenAI-compatible empty delta keepalives while waiting on the upstream or tool execution, and all SSE responses set `Cache-Control: no-cache, no-transform` plus `X-Accel-Buffering: no` to reduce proxy buffering.

Both streaming paths are wrapped by `resilient_sse_response` (`shenyu_gateway/streaming.py`): a producer task reads the inner event generator into a queue while the consumer side serves the client, emitting a keepalive event every 15 seconds of upstream silence (sized for the ~100s Cloudflare Tunnel idle cutoff). A client disconnect does not cancel the upstream read — the producer detaches, keeps draining until the reply finishes naturally (bounded by a 30-minute watchdog), and the normal `terminal_status="ok"` completion still saves the assistant output, snapshot, and request log; the request log additionally records `client_disconnected: true`. Only the watchdog-cancel path ends with `terminal_status="client_disconnected"`, and `_on_stream_complete` then still writes any collected partial assistant text to session history (without a completion snapshot or context-consumed marking, because the content is incomplete). The tool loop likewise no longer treats a disconnect as a stop condition; it finishes its rounds and records the flag. The PWA side pairs this with a 180-second stall watchdog on `reader.read()`, `[DONE]`-based truncation detection, throttled transcript persistence during streaming, and a tail-only reconcile (`pwa/src/session/reconcile.ts`) that re-fetches the session detail on foreground return and adopts the server-drained reply.

All four response paths (plain/tool-loop × streaming/non-streaming) record the same content-free `upstream_response_evidence`. The `upstream` layer observes the provider response before adaptation; the `normalized` layer observes the OpenAI-compatible completion/chunk handed toward the client. Fixed block/delta counters plus `thinking_content_seen`, usage, and finish booleans are safe to persist in request-log history. Raw response bodies, Thinking text, signatures, redacted data, and arbitrary upstream field names remain excluded. This evidence diagnoses which boundary lost a standard Thinking value; it does not alter the response or make relay-private fields part of the gateway contract.

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

Adding ordinary gateway-native tools should not require changes to the streaming loop. Add the schema/name dispatch in `shenyu_gateway/tool_registry.py` and the behavior in the `shenyu_gateway/gateway_tools/` mixin package. Only update streaming/protocol code when adding a new upstream protocol, a tool whose execution progress must stream to the client, or a non-gateway client tool with special forwarding semantics.

`shenyu_gateway/upstream_adapter.py` normalizes upstream stream protocols. Anthropic `tool_use` / `input_json_delta` chunks are converted into OpenAI-compatible `tool_calls` deltas, and completion-to-SSE conversion can skip duplicate role chunks and split large final content into smaller events.

The gateway's public `/v1/chat/completions` contract remains OpenAI-compatible, including multimodal `image_url` blocks from the PWA. `UPSTREAM_PROTOCOL` controls only the outbound provider format: the Anthropic adapter converts those blocks to Anthropic `image` sources (and converts Anthropic responses back to OpenAI-compatible responses). Clients do not need to switch wire formats when the configured upstream changes.

## Tool Error Log

When a gateway-native tool call fails, the gateway records the failure in SQLite `tool_error_log` and surfaces it in the admin **工具报错** page (`/admin/#/tool-errors`). The point is to answer one question: *where is Shenyu's tool use going wrong, and is it our bug or a malformed call?*

Each row is classified into one `error_kind`:

- `exception`: a real server-side crash (traceback / attribute error / type error). Gateway bugs to fix.
- `config`: a missing or disabled dependency (`... not configured`, `embedding api is not configured`, `not available`). Fix by configuration, not code.
- `validation`: the model called the tool wrong — unknown/deprecated tool name, bad arguments, or a rejected broker target. These point at tool schema/description problems, i.e. Shenyu being led astray.

Classification lives in `_classify_tool_error()` (`shenyu_gateway/tool_loop.py`) and prefers an `error_kind` the handler declared explicitly; genuine exceptions are tagged at the `except` site rather than guessed, and a small keyword heuristic is only a fallback. The config-phrase list is `TOOL_ERROR_CONFIG_PHRASES` at the top of `shenyu_gateway/store/_admin.py`. The legacy `error_source` column is retained and derived from `error_kind`.

The admin view groups errors into three tabs — `全部` / `真报错` (`exception` + `config`) / `调用被拒` (`validation`) — and expands a `调用被拒` row to show `args_json` (what Shenyu actually passed) beside `error_text` (what was expected). That side-by-side is the evidence base for tightening tool schemas so Shenyu stops mis-calling them.

The tool result sent back to Shenyu keeps the original `error`, adds the resolved `error_kind`, and includes a short `ps` from 圆儿. `exception`/`config` results say that he found a household bug; `validation` results ask him to check whether the correct method was actually exposed and report it if not. The `ps` is conversational guidance only and never replaces the machine-readable error.

- Table: SQLite `tool_error_log`. The `error_kind` column is auto-migrated on startup via `_ensure_column` (existing rows default to `unknown`); no manual migration or new env var is required.
- API: `GET /api/gateway/tool-errors?limit=50&kind=<exception|config|validation>` (`kind` optional; the view currently filters client-side).
- Frontend: `admin/src/views/ToolErrorsView.vue`, `admin/src/api/toolErrors.ts`.

The deprecated compatibility names `shenyu_ask_memory`, `shenyu_search_primary_texts`, and `shenyu_get_meta_summaries` are now rejected with `error_kind=validation` and a redirect to `shenyu_recall`, instead of silently forwarding. The broker `shenyu_gateway_tool` schema exposes only `tool` + `params` (the old `arguments` field is still accepted server-side but no longer advertised).

## SQLite Runtime State

SQLite stores only gateway runtime state:

- `gateway_sessions`
- `gateway_messages`: local message stream for inspection only. It is not the cold-start source of truth.
- `request_context_snapshots`: recent client context windows. Cold-start is now the only consumer.
- `raw_request_windows`: recent untrimmed client request windows for backup/export/debugging.
- `cold_start_snapshots`: bounded bridge packages created from recent context snapshots.
- `pending_gateway_tool_turns`: short-lived hidden mixed tool transcripts. It stores the original mixed assistant tool-call message, gateway tool result messages, client tool-call ids, and consumed/expiry timestamps.
- `cache_entries`: short-lived gateway cache.
- `request_log_history`: bounded, versioned safe request summaries used by the Admin log page and helper across process/container replacement. Full request/response payload fields are excluded before storage.
- `heartbeat_entries`: global private heartbeat notes captured from `<heartbeat>...</heartbeat>` or written manually in admin. `session_id` is retained as the source session, but runtime injection reads the shared global pool.

`request_context_snapshots` is the replacement for the old rolling/frozen context path. Each request stores the trimmed client window before gateway layers are inserted. The cold-start bridge reads these snapshots (calendar generation, formerly a second consumer, was removed on 2026-07-26). `raw_request_windows` stores the original client payload window before any gateway-side trimming and is kept separate so cold-start stays bounded.

### SQLite Retention And Cleanup

SQLite is intentionally kept as a small online runtime database. Supabase remains the durable memory/content store.

The default database path is `./data/shenyu_gateway.db`, which resolves to `/app/data/shenyu_gateway.db` in the production container. The Dockerfile does not declare a volume. Coolify must mount a persistent volume for `/app/data` (or for the directory selected by `GATEWAY_DB_PATH`) if SQLite state is expected to survive a container replacement. Admin-written `/app/.env` overrides have the same container-lifetime limitation unless that file is also persisted; Coolify dashboard environment variables remain the deployment source outside the container.

Admin configuration updates currently store secret values in both `.env` and SQLite `config_overrides` so runtime settings can survive the deployment patterns this gateway already supports. Treat both paths and their backups as secret-bearing assets: restrict filesystem/volume access, do not export the database casually, and rotate credentials after suspected exposure. The Admin API never returns those values. Replacing this dual storage requires an external secret store and a migration plan; do not add reversible application-managed “encryption” with a key stored beside the database.

### Content Copy Matrix

| Data product | Content retained | Default bound | Purpose | Session delete |
|---|---|---|---|---|
| `gateway_messages` | prepared user/assistant text, tool args and result summaries | newest 1500 rows per session | local inspection, lineage and export | deleted |
| `raw_request_windows` | compacted original client history; image bytes replaced by fingerprints | newest 3 windows per session | history event classification, backup/debug | deleted |
| `request_context_snapshots` | trimmed client-visible history before pending transcript reinjection | newest 3 snapshots per session | cold start source | deleted |
| `cold_start_snapshots` | copied source snapshot messages | newest 20 completed snapshots; active preserved | bounded cross-thread bridge | deleted |
| `pending_gateway_tool_turns` | original mixed assistant call and gateway tool result messages | active until consumed or 24h expiry | reconstruct gateway/client mixed turns | deleted |
| `tool_error_log` / `room_trace` | tool args/errors or Room diagnostic text | explicit table-specific limits/cleanup | diagnostics | deleted |
| request-log deque | summaries by default; full messages/payload/response only with `GATEWAY_LOG_FULL_PAYLOADS=true` (env or Admin runtime toggle, applies per new request) | 30 requests, process memory | live debugging | process restart clears it |
| `request_log_history` | versioned safe summaries/previews (message previews keep the newest 100 entries); full messages/payload/response, images, raw Thinking/signatures excluded | newest 200 by default, SQLite | cross-deploy Admin/API/helper debugging | independent of session delete |
| helper `--save` JSON | one explicitly exported redacted log detail | operator-managed file | offline debugging | independent local file |
| Supabase `shenyu_chat_archive` | deduplicated visible user/assistant text | durable; no automatic session-delete coupling | long-term recall/archive | not deleted |

These copies are not interchangeable: raw windows classify client history, snapshots feed cold start, pending rows preserve tool protocol, and the archive is the durable recall source. Reducing copies requires replacing those responsibilities first, not deleting tables based only on duplicate text.

Default online retention:

- `GATEWAY_MESSAGE_RETENTION=1500`: keep the newest local message rows per session. These rows are for admin inspection and export, not for cold-start injection.
- `GATEWAY_CONTEXT_SNAPSHOT_RETENTION=3`: keep the newest context snapshots per session. Do not set this to `0`; cold-start needs recent snapshots.
- `GATEWAY_COLD_START_RETENTION=20`: keep recent cold-start snapshots per session. Cleanup only removes old inactive snapshots; an active bridge remains available until the normal window trim retires it.
- `GATEWAY_REQUEST_LOG_RETENTION=200`: keep the newest safe request-log summaries globally. The Admin/API list merges them with the live 30-entry deque and prefers the live copy when both exist. A startup pass marks rows left in `preparing`, `pending`, or streaming states as `interrupted`.
- Consumed or expired `pending_gateway_tool_turns` are removed during cleanup. Unconsumed pending rows are kept until expiry so a client can return its tool result in the next request.
- `heartbeat_entries` is not removed by automatic cleanup. It can be manually written/deleted from the admin session page.
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
- Be conservative with `request_context_snapshots`; cold-start reads this table.
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
- `calendar_pages`
- `calendar_prompt_configs` (orphaned since the 2026-07-26 calendar-generation removal; no code reads or writes it, and it never had a migration)
- `calendar_generation_runs` (orphaned, same as above)
- `windowsill`
- `shenyu_mem_notes`
- `shenyu_stars`
- `shenyu_star_links`
- `shenyu_star_recall_runs`
- `shenyu_star_recall_candidates`
- `shenyu_star_feedback`
- `shenyu_star_activations`
- `shenyu_entities`
- `shenyu_entity_aliases`
- `shenyu_entity_mentions`
- `shenyu_entity_relations`
- `atomic_memories` (legacy read-only migration source)

The short-lived notes table is no longer used by gateway code.

The mem review UI reads and updates Supabase `shenyu_mem_notes`. The star review UI reads and updates the `shenyu_stars` family of tables. The old `atomic_memories` table is only exposed through a read-only lookup for manual migration. SQLite only provides local request/session context.

## Windowsill

`windowsill` is Shenyu's own writing place for essays, journal entries, moods, and reflections, without the category structure of `journal`. Apply `supabase/migrations/20260710_create_windowsill.sql` and `supabase/migrations/20260814_windowsill_origin.sql` before enabling the tools.

- `shenyu_windowsill_write(content, title?, mood?)` leaves a new entry. PostgreSQL generates `id` and `created_at`; neither is supplied by the model.
- `shenyu_windowsill_list(mood?, limit?)` returns recent entries, newest first, with optional exact mood filtering.
- `room_scribble` is the Room adapter for the same table: it automatically writes `origin=room`, while normal windowsill writes retain the database default `origin=normal`. Room reads only its own origin; the normal list can see both without splitting the writing pool.
- Legacy SQLite `room_scribbles` are copied idempotently on Room context/tool/Admin access with their original time and `origin=room`; a local link row prevents duplicate imports after restart.
- Successful writes are indexed immediately; the periodic recall reconciliation worker repairs any missed write later.
- The table is intentionally reached through these dedicated tools. Raw Supabase tools remain an explicit maintenance/debug surface rather than a daily Shenyu surface.

## 窗外 (Web)

The 窗外 pair gives Shenyu web reach from the PWA, implemented in `gateway_tools/_web.py` as ordinary gateway-native tools (both on the daily surface):

- `shenyu_web_search(query, limit?)` posts to Serper (`google.serper.dev`, Google results with `gl=cn`/`hl=zh-cn`) and returns only `title`/`url`/`snippet` (+`date` when present); snippets are clipped, provider metadata (position, sitelinks, knowledge graph) never enters the result. Requires `SERPER_API_KEY`; without it the tool degrades to an `error_kind: config` result.
- `shenyu_web_read(url, part?)` fetches page text through Jina Reader (`r.jina.ai`) with `x-return-format: text` — the default markdown is mostly image/link syntax (a weather page measured 30k chars of markdown for 3k of prose), and tool results enter context verbatim and pin into the prompt-cache prefix. Pages are split into ~15,000-char parts cut at newline boundaries, large enough that an ordinary long article usually needs no more than one continuation; part 1 is returned by default and a `rest` note tells the model how to continue. Fetched pages are cached in process memory for ~10 minutes so continuing to the next part does not re-download. `JINA_API_KEY` is required in practice: Jina refuses anonymous reads from datacenter ASNs (the VPS and the proxied dev box both hit `AuthenticationRequiredError`), so 401/402 is reported as `error_kind: config` naming the missing or exhausted key rather than a bare status code.
- Both calls go to fixed public endpoints only — the gateway never fetches a model-supplied host directly. Results are framed in the tool descriptions as outside reference material, not household truth (prompt-injection posture). Failures (timeouts, non-200, empty pages) return standard `{ok: false, error, error_kind}` results and never fail the chat.
- These two tools preset their own resident-facing `ps` on upstream-failure paths. A dead link or a refusing site is a normal outside condition, so `_decorate_tool_error_result`'s default "又抓到一个家里的bug" line would be a false statement; the tool says the outside road did not connect instead. Missing keys (`config`) and malformed calls (`validation`) keep the household wording, because those really are ours to fix.
- Outbound HTTP honors `UPSTREAM_PROXY` when set, otherwise `trust_env=True` for WSL-style mirrored proxies, matching the RSS client conventions.

Both keys are editable at runtime from the Admin Config page (窗外 card), following the QWeather precedent.

## Recall Index

`shenyu_recall` is the unified search entrypoint for old context. Every selected indexed source is hydrated from all its indexed chunks before returning, so the result contains its complete original content plus `source_type` and `source_id`. `shenyu_recall_read(source_type, source_id)` remains available for direct reads when those identifiers are already known. It never exposes rank scores, but a selected original may carry a compact `recall_match` structure: direct confirmed anchor, one confirmed relationship path, or another association. This tells Shenyu why an original is present without adding summaries, importance, or hidden ranking fields. The owner-only `/api/gateway/memory-graph/recall-preview` read path displays the same route label in Admin, calls Recall with auto-sync disabled, and does not mutate memory state. Full candidate and selection traces stay in gateway logs.

Recall accepts `mode=auto|exact|fuzzy|mood|verbatim`. `auto` only switches on strong intent signals and otherwise behaves as `fuzzy`:

- `exact`: one primary original, optionally one strongly related star/mem note/heartbeat.
- `fuzzy`: up to three primary excerpts plus at most one strongly related federated item; default total limit 4.
- `mood`: at most three sparse results, with stars/heartbeats/mem notes eligible as first-class lanes.
- `verbatim`: explicitly searches `shenyu_chat_archive`; raw chat does not enter ordinary recall.

Ordinary memories search across historical session tags. `session_tag` remains provenance and a possible future tie-breaker, not a visibility boundary. Rows explicitly marked `private` or `hidden` still require an exact session match.

Indexed public source types:

- `memory`: rows from `memories`
- `journal`: rows from `journal`
- `windowsill`: personal writing from `windowsill`, including Room entries marked `写自房间`
- `heartbeat`: settled normal-scope rows from `shenyu_heartbeat_archive`
- `room`: rows from `room`
- `board`: rows from `message_board`
- `calendar`: rows from `calendar_pages`
- `mem_note`: active rows from `shenyu_mem_notes`
- `notebook`: rows from `shenyu_notebook`

Stars remain a specialized federated ranker. Active mem notes are now indexed public sources so manually confirmed entity anchors and the shared keyword/vector/graph ranking can reach their original content; that shared document contains only the note body and time, not summaries, triggers, importance, or structured Mem fields. The existing Mem-specific candidate path remains a companion lane and source dedupe prevents duplicate returns. Recent unsettled normal heartbeats are scored from SQLite; settled heartbeats are indexed from the Supabase archive. `atomic_memories` and `meta_summaries` remain internal/legacy sources.

`shenyu_mem_notes` is the single canonical light-memory table. Legacy rows and v2 rows are not separate pools: legacy trigger/content fields remain readable, while missing `summary` and `memory_kind` receive a non-destructive runtime projection. Automatic mem-note recall is cross-session for normal chat. Only active notes enter the semantic index; captured and archived notes remain available to management/search tools without automatically surfacing.

Required Supabase migrations:

- `supabase/migrations/20260526_shenyu_recall_index.sql`
- `supabase/migrations/20260527_shenyu_recall_keyword_rpc.sql`
- `supabase/migrations/20260527_shenyu_recall_vector_rpc.sql`
- `supabase/migrations/20260723_create_memory_graph.sql` (entities, aliases, source mentions, and typed relations)
- `supabase/migrations/20260814_windowsill_origin.sql` (Room-to-windowsill provenance)
- `supabase/migrations/20260828_mem_note_remind_on.sql` (mem note date reminders; also relaxes the active-ready CHECK so a date alone is a valid anchor)

Migrations are an explicit deployment operation, not a gateway-startup side effect. Apply the required SQL through the project's Supabase migration workflow before deploying code that reads or writes the new schema. For the memory graph, verify the four `shenyu_entity_*` tables first; then deploy, open `/admin/#/memory-graph`, create one test anchor, and only then run the historical backfill.

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

The in-process recall worker first reconciles source tables into `shenyu_recall_index` every `RECALL_SYNC_WORKER_INTERVAL_SECONDS`, then embeds pending rows when embeddings and a valid API key are enabled. It embeds up to `RECALL_EMBEDDING_WORKER_BATCH_SIZE` rows per pass. Background recall, graph, and heartbeat upserts use `return=minimal`: those callers do not need stored rows back, and avoiding a full mutation representation prevents persisted embeddings from becoming recurrent Supabase egress. Request-time auto sync remains an emergency fallback rather than the freshness strategy.

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
`X-Shenyu-Session-Tag: 7.12`; the first request using that tag binds the frozen bridge, which stays available while
the rolling window still retains it. If no frozen snapshot was prepared, a previously unseen session tag still
automatically chooses the latest source thread with a request context snapshot. Existing sessions never trigger
cross-thread cold start merely because they were idle.

Flow:

1. `_prepare_messages()` opens the session and stores a `request_context_snapshot`.
2. `_maybe_prepare_cold_start_snapshot()` first reuses a frozen snapshot bound to the target session.
3. It calculates the gap between the target window and the real current client message count.
4. If the session is new and has no frozen snapshot, it chooses the latest source thread automatically.
5. It freezes the bounded source bridge and reuses it on later requests; the ordinary window decides when old bridge
   messages are trimmed.
6. After a successful bridge injection, the snapshot remains active while the fixed bridge is still inside the rolling
   window. It becomes inactive only after the normal window trim has pushed the bridge entirely out; a client-side
   duplicate of the bridge does not consume it because the client may omit that history again on a later request.

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

The calendar layer holds private day/week/month diary pages. Since 2026-07-26 the gateway-side generation
pipeline is removed: Shenyu handwrites every page herself through the `shenyu_add_calendar` gateway tool
(versioned append/replace into `calendar_pages`), and the admin CalendarView is a pure reading view.
Before ordinary chat replies, the gateway injects a compact calendar memory block when Supabase is configured.
By default, day pages are ordered by their diary date, the newest 2 written pages are left out, and the next 3 pages
are injected; gaps between diary dates do not count. Week and month pages remain the latest 1 page each with no
offset. Day/week/month injection can be enabled or disabled independently, and each period has its own injected-page
limit. Chat context injection includes the stored `content` body only, without the listing `summary` or short `digest`.

Tables:

- `calendar_pages`: versioned handwritten pages. The only live calendar table; `calendar_prompt_configs` and `calendar_generation_runs` are orphaned (see the Supabase list above).

Chat injection:

- `ContextBuilder` reads latest calendar pages into the `slow` layer.
- `CALENDAR_INJECT_DAY`, `CALENDAR_INJECT_WEEK`, and `CALENDAR_INJECT_MONTH` toggle period injection.
- `CALENDAR_CONTEXT_DAY_LIMIT`, `CALENDAR_CONTEXT_WEEK_LIMIT`, and `CALENDAR_CONTEXT_MONTH_LIMIT` set injected counts.
- `CALENDAR_CONTEXT_DAY_OFFSET` skips that many newest day pages before applying the day limit; it does not affect week or month pages.
- Only stored `content` bodies are rendered into chat context; `summary` remains for calendar listings and `digest` remains a short memory snippet.
- The rendered block uses labels: `recent days`, `this week`, `this month`.
- Missing Supabase or empty pages are skipped silently.

For `shenyu_add_calendar`, `date` is always the natural `YYYY-MM-DD` alias. The gateway converts it to `YYYY-Www` for week pages and `YYYY-MM` for month pages before calling the calendar service; callers that already know the canonical key can pass `period_key` directly.

Endpoints (read-only; both are external contracts with `home-frontend`, pinned by `tests/test_external_contracts.py`):

- `GET /api/calendar/month`
- `GET /api/calendar/page/{page_id}`

## External Frontend Contracts

The separate `home-frontend` project calls a small set of gateway APIs directly from the browser. These contracts are runtime dependencies even when this repo's admin UI does not reference them.

Preserve browser access behavior:

- `/api/*` must continue to accept `?token=...` authentication as well as `Authorization`.
- `OPTIONS` requests must bypass auth so CORS preflight is not rejected.
- CORS must continue to allow `https://home.yuanuwuclaude.uk`, `https://yuanuwuclaude.uk`, `http://localhost:8005`, `http://127.0.0.1:8005`, `http://localhost:5500`, `http://127.0.0.1:5500`, and `null`.

The PWA client profile uses `X-Shenyu-Client: shenyu-pwa`. That profile hides client-provided tool
schemas while keeping gateway-native tools (`shenyu_*`, `supabase_*`, and `room_*`) available. It also
emits a client-neutral tool execution event for UI mapping. Other clients may opt into the same event
stream with `X-Shenyu-Tool-Events: 1`. A client must additionally send `X-Shenyu-Tool-Details: 1` to
receive raw tool input and the exact tool-result JSON passed to the model; PWA uses this only for the
active response detail sheet. The PWA reads the same-origin `shenyu_upstream_presets` entries used by
the Admin Config page and applies a selected preset through `POST /api/config`; this changes the fixed
default upstream configuration, not the PWA client identity, session semantics, memory surface, or tool
event contract.

The model sheet also owns browser-local editable upstream headers. Completed rows travel only on chat requests
as `ChatRequest.upstream_headers`; `upstream_client.py` validates them once and applies them to both OpenAI-compatible
and Anthropic outbound requests. The Claude Code preset mirrors the locally captured CLI/SDK identity layer:
`User-Agent: claude-cli/2.1.201 (external, sdk-cli)`, `Accept`, `Anthropic-Beta`, `X-App`,
`X-Claude-Code-Session-Id`, the observed `X-Stainless-*` fields, and the direct-browser-access marker. For native
Anthropic requests it also supplies the captured `metadata.user_id` shape with a random browser-local device id,
empty account UUID, and the same session UUID. Device and session ids remain fixed until the user explicitly
refreshes the session UUID, preserving upstream prompt-cache continuity. The preset does not copy Claude Code's
coding system prompt or tool schemas because those would replace Shenyu's product semantics. Gateway-owned
authentication, protocol-version, cookie, hop-by-hop, and `X-Shenyu-*` headers cannot be replaced. Header values
are neither request-log fields nor persistent history. Simulated metadata is excluded from the safe persistent
request-log tier, but can appear in the live full upstream payload when `GATEWAY_LOG_FULL_PAYLOADS=true`. The safe
`upstream_payload_summary.claude_code_identity` records only five shape booleans for the CLI User-Agent, Claude Code
beta, valid session UUID, complete Stainless header group, and session-matched metadata; it never stores their
values. Omitting the preset preserves the existing upstream request exactly.

The optional `ECHO_PROMPT` is appended to the `format` system layer immediately before the Heartbeat
format prompt. It asks the model to place a visible, model-authored reflection at the beginning of its
assistant text as `[回响]...[/回响]`; this is a user-facing self-reflection channel, not provider hidden
Thinking or the private `<heartbeat>` block. The Admin Config field is global, and `ECHO_RETENTION_TURNS`
(default `1`, range `0..20`) controls only how many later user turns keep the tagged block in the next
upstream request. `0` removes it on the next request. The PWA always keeps echo in its local transcript,
variants, and context snapshots, even after the model-facing tag expires. Empty echo is valid and does not
create a fallback reply. The long-term `shenyu_chat_archive` path strips echo tags before archival so a
short-lived private reflection does not become unlimited recall material.

Cross-client conversation continuity is keyed by `X-Shenyu-Session-Tag`, not by `X-Shenyu-Client`.
`X-Shenyu-Client` only selects the client capability profile. Operit and PWA can therefore share one
conversation by sending the same session tag; the gateway updates the session's last client name but
does not create a second session. PWA also accepts `/chat/?session_tag=<tag>` for an explicit handoff and
offers an explicit `接入线程` action that loads a selected existing session before sending. The PWA
uses the Admin `客户端上下文保留` value for that history load, so the handoff window stays aligned
with the gateway's configured client context window. The handoff reads the newest `context_snapshots[0].messages`
(`request_context_snapshots` is accepted as an equivalent response key) because it is the trimmed client-visible
transcript; `recent_messages` is only a compatibility fallback for sessions without a snapshot and must not be
treated as a complete chat history. The handoff sheet also exposes an explicit clean cold-start recovery action;
it removes exact duplicate rows from the local PWA transcript while retaining newer PWA messages, then lets the
next request use the non-duplicated cold-start source to rebind the gateway epoch. The PWA persists roughly the
gateway high-water window locally; once a `shenyu-pwa` request contains a full configured client window, the gateway
retires any active temporary cold-start snapshot and sends no bridge for that session. The recovery action is therefore
only a short-history handoff path. Assistant rolls stay client-side:
each regenerated answer is a variant of the same assistant turn,
the selected variant is the only one sent on the next request, and switching variants does not rewrite gateway
history until a new request is sent. A new or different tag intentionally starts a separate session, so a client
must preserve its original tag when switching back.

For streaming chat, tool events are separate SSE events and do not alter OpenAI-compatible chat chunks:

```text
event: shenyu_tool
data: {"type":"shenyu.tool_event","event":{"phase":"tool_start",...}}
```

The standard event payload contains `phase` (`tool_start` or `tool_end`), `tool_call_id`, `name`,
`target_tool`, `round`, and completion metadata such as `ok`, `cached`, `duration_ms`, and `error_kind`.
Arguments and tool results remain omitted unless the client explicitly requests `X-Shenyu-Tool-Details: 1`.
That opt-in adds `input` and, after completion, `output`: the exact JSON string that the gateway appends
to the following upstream tool-result message. Those detail fields are current-response data only and
must never be persisted in request logs or SQLite history. Non-streaming responses expose the same list
under `shenyu.tool_events`. A client should treat a tool round as complete only after its `tool_end` event.
The PWA records its current streamed text length when each tool event arrives, so it can place that
tool round between the corresponding text segments without adding a provider-specific field to the
gateway contract.

PWA echo deltas use a separate SSE event and never enter visible assistant content deltas:

```text
event: shenyu_echo
data: {"type":"shenyu.echo_delta","object":"shenyu.echo_delta","echo":"..."}
```

Non-streaming PWA responses expose `shenyu.echo` for one echo and `shenyu.echo_segments` when a
gateway-tool loop produced multiple echo passages around tool events. Each segment carries a
`stream_order` so the PWA can place 回响, Thinking, and tool rows in their actual process order. A
non-PWA client does not receive these echo events/fields unless its resolved client profile enables the
same event surface. The raw tagged assistant text remains in the model-facing session history/snapshot
path for the configured retention window; request-log previews and durable chat archive strip the leading
tag.

Every successful PWA reply also receives one content-free response summary. Streaming responses emit it
before `[DONE]` as `event: shenyu_meta` with `type: shenyu.response_meta`; non-streaming responses expose the
same object under `shenyu.response_meta`. `context_rounds` is the number of retained human-turn groups actually
sent in the client-history window. `context_trim_in_rounds` uses the same request's dynamic `context_high_water`
and `client_non_system_retained` values to estimate how many normal PWA user/assistant turns remain before the
gateway's next high-water trim; it is null when the configured window is unlimited. `cache_read_percent`
uses the provider-normalized cache coverage already used by Admin and is omitted when its denominator is not
reliable. For a tool-using reply, that percentage aggregates all upstream rounds; `tool_rounds` counts only rounds
that actually executed a gateway-native tool, while `first_tool_round_cache_hit` states whether the first upstream
round reported positive cache reads. `heartbeat_captured` is a boolean only: heartbeat text remains private and is
never added to the client event.

The PWA keeps streaming enabled by default and stores its Stream toggle as a browser-local preference.
Turning it off sends `stream: false` only for that PWA's chat requests; the completed response then
hydrates the same visible answer, Thinking, `shenyu.tool_events`, and `shenyu.response_meta` message state without changing the
gateway default, upstream preset, session identity, or any other client.
Both modes pass through the response-shape evidence described above, so a single normal request can distinguish
an upstream omission from adapter loss or a PWA parser/display problem without enabling full-payload logging.

Preserve these response contracts:

- `GET /api/gateway/heartbeats?token=...&limit=2000&order=asc&scope=normal` returns `heartbeats`; each item must include at least `content` and `created_at`. `scope=normal` reads `heartbeat_entries`; unknown scopes (including the retired `hisense`) still return 200 with an empty list so stale external callers degrade gracefully.
- `GET /api/calendar/month?token=...&month=YYYY-MM` returns `grid`; each day item must keep `date`, `day`, `in_month`, `has_day`, `has_week`, and when present `day_page.id/title/summary/status`.
- `GET /api/calendar/page/{page_id}?token=...` returns at least `id`, `title`, `summary`, and `content`.

## Durable Archive Layer

SQLite holds only rebuildable runtime state. Anything whose loss would hurt lives in Supabase. Three archive subsystems enforce this:

### Heartbeat archive (disaster recovery)

`shenyu_heartbeat_archive` in Supabase is the durable copy of both SQLite heartbeat pools. The worker (`shenyu_gateway/heartbeat_archive.py`):

- syncs heartbeats only after a settle window (`HEARTBEAT_ARCHIVE_SETTLE_HOURS=6`), so manual cleanup of re-roll duplicates or runaway heartbeats done in SQLite first never reaches the archive;
- uploads remain enabled independently from deletion reconciliation;
- only when `HEARTBEAT_ARCHIVE_RECONCILE_DELETIONS=true` does it reconcile rows deleted from SQLite after archiving into archive `deleted_at`; the default is `false`, and even an explicitly enabled worker refuses to reconcile a non-empty remote scope against an empty local heartbeat pool;
- backfills all history automatically on first run.

SQLite stays the live read path; injection behavior is unchanged. Enable deletion reconciliation only on the production instance with its stable persistent SQLite volume. Config: `ENABLE_HEARTBEAT_ARCHIVE`, `HEARTBEAT_ARCHIVE_SETTLE_HOURS`, `HEARTBEAT_ARCHIVE_INTERVAL_SECONDS`, `HEARTBEAT_ARCHIVE_BATCH_SIZE`, `HEARTBEAT_ARCHIVE_RECONCILE_DELETIONS`.

### Chat archive (L0 source of truth)

`shenyu_chat_archive` in Supabase stores verbatim user/assistant messages, message by message, archived from the client window in `_prepare_messages()` (fire-and-forget; failures never affect chat). Dedup uses `chat_archive_seen` in SQLite, consulted globally across session tags (rows still record their session_tag for provenance): resent sliding windows archive each message once, a window handed over into a new session (PWA history handoff, cold-start bridge) does not re-archive the carried history, and a genuinely repeated message months later is a new event once its hash ages out of retention. Re-rolled replies never return in the client window, so they are naturally excluded.

`event_at` is the client-local send time: user messages carry it in the PWA tail status suffix (the 第N天 segment anchors the year at 2026-03-09; parsing lives in `client_extra.py` next to the shared suffix regex) or in legacy Operit time markers; assistant replies inherit the preceding user message's time. `archived_at` increases by 1μs per row inside a batch so `(event_at, archived_at)` replays the window order. The stored `thread` column is provenance only (one value per session epoch, including the retired `hisense` rows — the durable archive is soft-delete only): the archive reader presents one merged timeline and folds handoff duplicates per (CST day, content_hash); deleting a message also deletes its same-day twins.

- Backfill from existing SQLite history: `python scripts/backfill_chat_archive.py` (idempotent; `--dry-run` to preview).
- Admin reader: `/admin` → 档案 tab; API under `/api/archive/*`.
- Config: `ENABLE_CHAT_ARCHIVE`.
- This table is the source of truth: recall indexes and conflict books are derived from it; soft-delete only.

### Origin books（来历书）

Frozen verbatim excerpts of arguments, clipped by the user from the archive reader, readable and annotatable by Shenyu. Invariants enforced in `shenyu_gateway/conflict_books.py` (no API path can violate them):

- `original_text` is frozen at clip time; update paths drop it and a text-only patch is rejected.
- Shenyu's annotations are append-only with timestamps; no update or delete endpoint exists.
- Every origin-book read through `shenyu_books` still appends a row to `shenyu_conflict_reads` and bumps `read_count`, so the overview and Admin shelf can show 翻过几次/最近何时.
- Full book contents are never auto-injected. The passive `slow` surface is `## 书架一览`: generated-home change count/last confirmation, identity revision/actor, and origin-book titles. The legacy `INJECT_CONFLICT_SHELF` switch still gates this unified overview.
- The public book entry is `shenyu_books` with `action=read|write|annotate`; there is no model-facing list/shelf action. `write` only accepts `identity`, while `home` is generated and read-only. The old `shenyu_conflict_*` names remain hidden compatibility handlers. Duplicate origin titles are rejected as ambiguous rather than guessed.

Tools: `shenyu_books`. Admin UI: 档案 tab (clip flow) and the three-tier shared bookshelf at the legacy `/conflict` route: revisioned `我是谁`, generated read-only `家现在`, and frozen origin books. All three can receive append-only annotations; origin-book cover fields and soft deletion remain available without exposing any original-text update path. Identity and the home annotation anchor use `shenyu_books` / `shenyu_book_revisions` / `shenyu_book_annotations`; origin books continue using `20260613_shenyu_conflict_books.sql`.

### Generated home and living identity

`home`（家现在）is generated from the current repository/runtime snapshot, `resident_home_manifest.json`, and the weekly change ledger. It has no writable body or revision flow: reads return the full current home, and annotations append against a stable internal anchor without changing the generated content. `identity`（我是谁）is the single shared mutable document. Every identity write creates a revision before updating the current body; `expected_revision` rejects stale writes instead of silently overwriting a newer edit. Timestamps and actors are assigned by the gateway entry point.

### Owner-only project map

`家里地图`与`家现在`在 Admin 书架上同层摆放，但不是第四种 resident book。`GET /api/project-map` 每次读取时由 `project_map.py` 从 `resident_home_manifest.json`、`resident_home_changes.jsonl`、`project_delivery_log.jsonl`、README Maintenance Map / 产品反查表、`DOCS_MAP.md` 现行文档表和 `SYSTEM_ZONES.md` 的请求链与跨区桥梁现场组装；组件之间的直接连接只由恰好两项 manifest 组件实际命中的共享源码文件推导，像 `context_builder.py` 这样的多方公共总线保留在 `SYSTEM_ZONES.md` 的全屋跨区桥梁中，交付记录的产品与区域落点由现行反查表和核心文件现场推导，不另存一份手工连线表。生产镜像必须带上这些被读取的现行文档与台账。

这册地图只给后台里的圆圆看。它不注册 `ResidentBooksService` slug，不出现在 `render_bookshelf_overview()`，不进入 `shenyu_books`、普通聊天、Room 或任何模型上下文，也没有写入、批注或正文覆盖入口。页面上的“实时”表示它反映当前已部署 checkout / build revision、最近确认状态和已记录的交付时间线；未部署的本地变化不会凭空出现在生产页面。交付时间线与住户影响台账分开，前者回答“最近做了什么”，后者回答“沈予的生活机制发生了什么”。
