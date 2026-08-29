# Shenyu Gateway

Shenyu Gateway is the single OpenAI-compatible provider entrypoint for Operit. It prepares context, exposes tools, routes tool calls, and adapts requests to Anthropic or OpenAI-compatible upstreams.

The gateway is not a persona layer or roleplay wrapper. It is a context and memory gateway: current conversation text stays primary, long-form primary text can surface softly, and durable memory is handled by explicit layers.

## 新线程入口

Coding agent 先遵守 **`AGENTS.md`**，再读 **`START_HERE.md`**；人直接从 `START_HERE.md` 开始即可。它会按任务指向现行专题文档，不要求预读全部架构、设计和 Debug 文档。

- 想找文件：看本页 § Maintenance Map，再看 `docs/architecture/SYSTEM_ZONES.md` 的责任边界。
- 想判断某份 Markdown 是否仍是当前事实：看 `DOCS_MAP.md`。
- 已经有具体问题：按 `START_HERE.md` 的任务表进入对应文档和代码。

权威的新线程阅读原则和文档状态统一由 `DOCS_MAP.md` 维护；本页不再复制另一套完整顺序。

## Current Architecture

```text
Operit / PWA chat
  -> Shenyu Gateway
       -> ContextBuilder
       -> GatewayStore (SQLite runtime state)
       -> GatewayToolService (Supabase tools, surface, memory)
       -> CalendarService (read-only day/week/month pages)
       -> MemNoteService (small personal notes)
       -> StarService (small chord/association memories)
       -> Upstream adapter (Anthropic / OpenAI-compatible)
  -> Upstream model
  -> gateway tool loop when needed
```

## Maintenance Map

The codebase is partly layered already:

### Core entrypoint

- `gateway.py`: FastAPI app entrypoint, lifespan, CORS, route registration, and model listing. Chat, calendar, admin, archive, and config routes have been extracted into dedicated modules.

### Config & runtime

- `shenyu_gateway/config.py`: environment-backed runtime config.
- `shenyu_gateway/runtime.py`: shared runtime utilities (logger, `now_ts`, `iso_now`, `json_dumps`, dotenv loading, and the repository's single local-timezone definition plus its day helpers).
- `shenyu_gateway/schemas.py`: Pydantic data models (`ChatMessage`, request/response shapes).

### Storage

- `shenyu_gateway/store/`: SQLite runtime state (package split into mixins: `_base`, `_sessions`, `_messages`, `_pending`, `_snapshots`, `_cold_start`, `_heartbeats`, `_cache`, `_room`, `_admin`, `_window_state`, `_request_log_history`).
- `shenyu_gateway/supabase.py`: low-level Supabase REST client.

### Chat pipeline & streaming

- `shenyu_gateway/chat_pipeline.py`: main chat request orchestration (context build → upstream call → tool loop → response).
- `shenyu_gateway/streaming.py`: SSE streaming helpers, chunk serialization, keepalive logic, and the client-facing `shenyu_echo` delta event.
- `shenyu_gateway/echo.py`: model-authored leading `[回响]...[/回响]` stream splitter, turn-based upstream retention trimming, and archive/history-safe tag stripping.
- `shenyu_gateway/response_meta.py`: content-free assistant reply status contract shared by streaming and non-streaming paths: retained context rounds, reliable cache coverage, real gateway-tool rounds, first-round cache hit, and heartbeat-captured boolean.
- `shenyu_gateway/stream_proxy.py`: plain pass-through streaming with `<heartbeat>` filtering.
- `shenyu_gateway/tool_loop.py`: internal gateway tool loop plus per-round request, response-shape, and cache diagnostics.
- `shenyu_gateway/middleware.py`: FastAPI middleware registration (global exception handler, request-id injection, HTTP event logging).

### Context assembly

- `shenyu_gateway/context_builder.py`: async parallel gathering of all memory sources into a context package.
- `shenyu_gateway/context_layers.py`: stable/slow/mem/heartbeat/tool-policy/format layer rendering (including the optional echo prompt immediately before Heartbeat), client message trimming, and cold-start bridge insertion.
- `shenyu_gateway/project_map.py`: owner-only live project map assembled from the current system zones, maintenance/product indexes, resident component fingerprints, and change ledger; it derives one-hop component links only from mapped source files claimed by exactly two components, while broader shared hubs remain cross-zone bridge evidence.
- `shenyu_gateway/project_delivery.py` / `project_delivery_log.jsonl`: structured owner-facing delivery ledger and validation/append helpers; one entry represents one coherent completed outcome and links it to a product, paths, docs, verification, and optional reusable lesson.
- `shenyu_gateway/resident_home.py`: resident-facing component manifest, source fingerprints, review acknowledgements, and weekly change records.
- `shenyu_gateway/resident_books.py`: unified bookshelf facade for the generated read-only home snapshot, the revisioned `我是谁` document, append-only annotations, and legacy origin-book storage.
- `shenyu_gateway/resident_profile.py`: stable wake/profile text for memory practice and the origin book.
- `shenyu_gateway/context_snapshots.py`: context snapshot creation and helpers for cold-start sources.
- `shenyu_gateway/context_window.py`: semantic history-event classification, chunk-safe client-history windowing with high-water/epoch/anchor state, and cold-start bridge overlap deduplication.
- `shenyu_gateway/client_extra.py`: shared recognition/stripping of client-injected per-message extras (Operit `message_insert_extra_bundle` attachments and the PWA tail status suffix), imported by trimming, archiving, history normalization, and recall-query cleaning.
- `shenyu_gateway/memory_island.py`: Stars/Mem island rendering and per-lane retain/rewrite state, including overlap decisions and current/added/updated/removed log summaries.
- `shenyu_gateway/prepare_messages.py`: cold-start snapshot preparation, runtime state pruning, pending gateway tool turn injection, and message/tool-call helpers.

### Upstream communication

- `shenyu_gateway/upstream_adapter.py`: pure OpenAI/Anthropic message, cache, stream, and model URL conversion helpers.
- `shenyu_gateway/upstream_client.py`: upstream HTTP client construction, protocol detection, URL routing, request building, streaming chunk iteration, model listing, and connection error formatting.
- `shenyu_gateway/upstream_response_evidence.py`: content-free counters for raw upstream response shapes and their OpenAI-compatible normalized output, shared by streaming, non-streaming, and tool-loop paths.

### Tools

- `shenyu_gateway/gateway_tools/`: gateway-native tool implementations (`GatewayToolService`, package split into mixins like stars/: `_supabase`, `_recall`, `_mem_notes`, `_stars`, `_books`, `_calendar`, `_sessions`, `_windowsill`, `_notebook`, `_web`, `_compat`, plus shared `_runtime`/`_helpers`/`_base`). `__init__.py` assembles the service and re-exports `configure_gateway_tools` / `get_runtime`. `_web` is the 窗外 pair: `shenyu_web_search` (Serper, `SERPER_API_KEY`) and `shenyu_web_read` (Jina Reader, `JINA_API_KEY` — required from datacenter IPs).
- `shenyu_gateway/tool_registry.py`: gateway-native tool schemas, enablement/merge logic, and tool-name dispatch into `GatewayToolService`.
- `shenyu_gateway/tool_schemas.py`: tool JSON schema definitions (separated from registry logic).
- `shenyu_gateway/mcp_registry.py`: gateway-as-MCP-client registry — validates `MCP_SERVERS`, caches remote tool lists (TTL, background refresh), exposes them as `mcp_<server>_<tool>` function tools, and executes calls with timeout/degradation (never 500s the chat path).

### Memory subsystems

- `shenyu_gateway/stars/`: Star memory service (package split into mixins: `_helpers`, `_chord`, `_scene`, `_weights`, `_crud`, `_recall`, `_activity`, `_review`, `_feedback`, `_logging`, `_render`, `_embedding`). ACT-R activation, chord/content/harmony scoring, review candidates, feedback logging, and constellation links.
- `shenyu_gateway/mem_notes/`: note service package (mixin pattern, like stars/): `_helpers` (constants), `_validation` (field validation), `_suggestions` (auto mem_type/keyword inference), `_search` (keyword/semantic/entity matching, scoring, cooldown, rendering), `_crud` (create/update/delete/list/legacy-atomic). `__init__.py` assembles `MemNoteService` and re-exports backward-compat symbols.
- `shenyu_gateway/mem_notes_relevance.py`: pure-function helpers for mem-note recall scoring, anchor matching, auto-extraction (people/places/objects/keywords/summary/memory_kind inference), `compute_heat()`, and `running_joke_serendipity_rate()`.
- `shenyu_gateway/memory_graph.py`: temporal personal memory graph service for confirmed entities, aliases (create/confirm/delete), source mentions, typed relationships, exact-alias backfill, one-hop Recall candidates, snapshot recency mapped to each source's real event day (`last_mentioned_at` per anchor plus a `recent` activity feed; mention-row bookkeeping timestamps are never used), per-anchor original-mention reads (`entity_mentions`), and unanchored name-candidate aggregation from mem-note fields.
- `shenyu_gateway/recall/`: unified recall index (package split into mixins like stars/: `_text` pure tokenize/query-parse functions shared by stars//mem_notes/, `_documents` corpus model, `_sources` per-table sync adapters, `_embedding` pending-embed worker, `_query` retrieval pipeline, `_ranking` scoring/fusion/presentation, `_base` constructor + config accessors). Keyword + vector + memory-graph hybrid search across registered sources, with complete selected-source hydration. `__init__.py` assembles `RecallIndexService` and re-exports backward-compat symbols.
- `shenyu_gateway/embeddings.py`: embedding client (SiliconFlow / BAAI/bge-m3).

### Capture & private content

- `shenyu_gateway/response_capture.py`: private assistant tag filtering for `<heartbeat>`, heartbeat persistence helper.
- `shenyu_gateway/private_capture.py`: private assistant content finalization (`<heartbeat>` extraction), context-consumed marking, fallback text generation, free-time detection, and strict timestamped Room-entry detection.

### Durable archive

- `shenyu_gateway/chat_archive.py`: L0 verbatim chat archive service (fire-and-forget archival to Supabase `shenyu_chat_archive`).
- `shenyu_gateway/heartbeat_archive.py`: heartbeat disaster recovery archive to Supabase (`shenyu_heartbeat_archive`), settle window, and explicitly gated soft-delete reconciliation with an empty-local-pool refusal.
- `shenyu_gateway/conflict_books.py`: durable origin-book records and invariants (frozen original_text, append-only annotations); the shelf/tool presentation is also a memory-data concern in system zone six.

### Calendar

- `shenyu_gateway/calendar.py`: date/period-key helpers and month grid construction.
- `shenyu_gateway/calendar_service.py`: `CalendarService` — read-only month status and page detail. Page content is handwritten by 沈予 via the `shenyu_add_calendar` gateway tool (`gateway_tools/_calendar.py`); there is no gateway-side generation pipeline.

### Weather

- `shenyu_gateway/weather.py`: QWeather client behind `GET /api/gateway/weather` for the PWA status suffix — call-time config reads, in-process city (24h) and weather (15min) caches, and unconditional degradation to `available:false`.

### Room mode

- `shenyu_gateway/room_text.py`: all room mode copy — charter, atmosphere scenes, door descriptions, trace phrases. Change text here only.
- `shenyu_gateway/room_context.py`: room mode charge calculation, layer rendering, door filtering logic.
- `shenyu_gateway/room_tools.py`: room mode tool definitions, compatibility broker, execute dispatch, door count collection, and the Room-to-canonical-windowsill bridge (`origin=room` plus idempotent legacy scribble import).
- `shenyu_gateway/room_scenes.py`: window scenes (weather, atmosphere, landscape). Change scene copy here only.
- `shenyu_gateway/room_newspaper.py`: fixed RSS sources, feed parsing, issue rolling, optional quality checks, and draft generation.
- `shenyu_gateway/private_capture.py`: recognizes the exact `【窗边 · DD/MM HH:mm】` entry that selects the Room context path; the retired Operit proxy workflow is not a Room entry.

### Auth & sessions

- `shenyu_gateway/auth.py`: admin auth middleware, API key verification, login page HTML, and `ADMIN_PROTECTED_PREFIXES`.
- `shenyu_gateway/sessions.py`: bridge from request handling to SQLite session/message persistence.

### Route modules (extracted from gateway.py)

- `shenyu_gateway/gateway_admin_routes.py`: admin API routes (stars, mem notes, room, overview, prune, etc.).
- `shenyu_gateway/calendar_routes.py`: read-only calendar API routes (month grid, page detail).
- `shenyu_gateway/archive_routes.py`: archive reader, origin-book, shared resident-book, and owner-only project-map API routes.
- `shenyu_gateway/config_routes.py`: configuration API routes (get/set runtime config).
- `shenyu_gateway/mcp_routes.py`: MCP server management API routes (`/api/mcp/servers` list/save with header masking, `/api/mcp/test` one-off probe, `/api/mcp/refresh`).
- `shenyu_gateway/admin_shell_routes.py`: admin shell/UI routes (static file serving, login page).

Route modules are HTTP adapters, not a separate business zone. `gateway.py` mounts them, while each endpoint's behavior remains owned by its feature area.

### Request logging

- `shenyu_gateway/request_logs.py`: live request log ring buffer, phase markers, HTTP event tracking, and the safe serializer used for persistent summaries.
- `shenyu_gateway/store/_request_log_history.py`: bounded SQLite request-log history used by Admin/API/helper after process or container replacement.

### Tool error logging

- `shenyu_gateway/tool_loop.py`: classifies gateway-tool results with `ok: false`, adds the resident-facing error `ps`, and records them through `_record_tool_error()`; this is separate from request-level error filtering.
- `shenyu_gateway/store/_admin.py`: writes and reads the dedicated SQLite `tool_error_log` table, including `validation`, `config`, and `exception` classification.
- `shenyu_gateway/gateway_admin_routes.py`: exposes `GET /api/gateway/tool-errors` for the Admin UI and diagnostics.
- `admin/src/api/toolErrors.ts` → `admin/src/views/ToolErrorsView.vue`: frontend API mapping and the “工具报错” page.

### Shared utilities

- `shenyu_gateway/utils.py`: shared utilities (`shorten`, `clean_config_text`, `normalize_text`) used across multiple modules.

### Admin frontend

- `admin/src/api/http.ts`: shared HTTP client (axios instance, auth token).
- `admin/src/api/config.ts`: gateway and upstream configuration.
- `admin/src/api/mem0.ts`: Mem config, mem-note review APIs, and old atomic read-only lookup.
- `admin/src/api/memoryGraph.ts`: entity, alias, relation, source-anchor, and historical-backfill APIs.
- `admin/src/api/stars.ts`: Star list/search/create/review/feedback/connect APIs.
- `admin/src/api/sessions.ts`: local SQLite session browser.
- `admin/src/api/logs.ts`: request log list and detail APIs.
- `admin/src/api/calendar.ts`: read-only calendar month grid and page detail.
- `admin/src/api/archive.ts`: chat archive reader and frozen origin-book APIs.
- `admin/src/api/books.ts`: resident-shelf APIs plus the separate owner-only live project-map contract.
- `admin/src/api/room.ts`: room mode APIs (traces, drawer notes, scribbles, pins, newspapers).
- `admin/src/api/toolErrors.ts`: tool error log APIs.
- `admin/src/api/mcp.ts`: MCP server management APIs (`/api/mcp/*`) plus the frontend mirror of server validation and masked-header rules.
- `admin/src/components/McpServersCard.vue`: MCP server management panel inside ConfigView — server list with status dots, add/edit form with header key-value rows, one-off connection test, and merged-tool listing.
- `admin/src/views/HomeView.vue`: admin landing/dashboard page.
- `admin/src/views/ConfigView.vue`: configuration page.
- `admin/src/views/Mem0View.vue`: Mem injection/tool controls, full-set two-state recall-eligibility management, Shenyu-write provenance badges, mem-note attributes, and old atomic read-only lookup.
- `admin/src/views/MemoryGraphView.vue`: personal memory-graph console — a clustered gilt thread map (anchors linked by confirmed/suggested red threads cluster into islands, isolates rest along the bottom edge; layout is id-sorted so a refresh does not reshuffle the net) with recent-mention warmth (names turn pine 松绿) plus a recent-activity stream. Picking an anchor runs a real recall and pins the result on the recall board (`RecallBoard.vue`); picking a ghost name lifts the reading overlay (`AnchorOriginalsOverlay.vue`) of the originals that mention it, with a pin-it action. Entity/alias/relation management with candidate confirmation stays folded behind 管理 below the map (and behind the hub's 管理这个名字 when the recalled word is an anchor), beside an archived-anchor drawer, unanchored name candidates, historical exact-alias backfill. The recall board is a read-only preview that mirrors what the model actually receives — the recalled word pinned at a compact center hub with per-source papers orbiting in three rings by strength (脱口而出 direct / 由此及彼 related / 浮想 other) over evidence-highlighted per-source papers, with explicit source-anchor linking on the lifted paper (the preview response only adds the query terms used for highlighting, never scoring internals).
- `admin/src/views/memory-graph/RecallBoard.vue`: the 描金线索板 (gilt-thread cork board) for 想起的一瞬间 — the recalled word pinned at the center hub (begonia + eyebrow + count), three rings of per-source papers by recall strength (direct: pine pin + strong thread to the hub; related: gilt pin + thinner gilt thread + a relation-path tag; other: taped to the outer ring, no thread), gold filigree corners, grain overlay, and a click-to-lift full-text reading layer built from the same `OriginalPaper` + `AttachAnchors` as the net's reading overlay. Paper angles are spaced evenly around the whole circle (first paper always at the top, radius set by group) so any result count surrounds the hub instead of piling into one side, and the hub is sized to never cover the inner ring; positions are seeded by source key so a board stays put across refreshes; narrow screens fall back to a paper stream.
- `admin/src/views/memory-graph/sourceDisplay.ts`: single home for recall-source display literals (Chinese labels, seal glyphs, paper families) shared by the memory-net view, the recall board, and the reading overlay.
- `admin/src/views/memory-graph/sourceAnchors.ts`: single home for original↔anchor attachment (manual-confirm evidence literal, source keys, per-source manual/auto anchor state with a small cache) — the one implementation both reading surfaces use. `admin/src/views/memory-graph/AttachAnchors.vue`: the shared 「挂着 / 自动连上的」 editing block built on it.
- `admin/src/views/memory-graph/botanical.ts`: Shenyu's hand-drawn SVG glyphs (begonia + per-source emblems, tinted by `--sy-rose-soft` petals and `--sy-gilt` linework), rendered through `admin/src/views/memory-graph/SyGlyph.vue`.
- `admin/src/views/memory-graph/OriginalPaper.vue`: one original rendered in its per-source paper style (letter, sticky note, card, slip) with seal, title, event day, optional lede line, and full text (content slot allows evidence highlighting).
- `admin/src/views/memory-graph/AnchorOriginalsOverlay.vue`: the lift-up full-text reading card opened by picking a name off the net — flip navigation across papers, hit-word (alias) editing, per-paper anchor attachment (`AttachAnchors.vue`), and ghost pinning.
- `admin/src/views/StarsView.vue`: standalone Star entry shell at `/stars`, with split Star panels under `admin/src/views/stars/`.
- `admin/src/views/stars/StarsLabelsPanel.vue`: manual relationship-label review, small-batch backfill, per-item results, and recent batch history.
- `admin/src/views/stars/StarsReviewPanel.vue`: admin review scoring, missed recording, and candidate constellation feedback.
- `admin/src/views/stars/StarsSettingsPanel.vue`: Star memory configuration controls.
- `admin/src/views/stars/StarsWritePanel.vue`: manual star creation and search.
- `admin/src/views/stars/StarsListPanel.vue`: star list/filter panel.
- `admin/src/views/stars/StarMapView.vue`: Three.js star graph view (memory star map at `/stars/map`).
- `admin/src/views/stars/starMelody.ts`: constellation → Web Audio melody.
- `admin/src/views/stars/starUi.ts`: shared Star UI formatting and link-order helpers.
- `admin/src/views/SessionsView.vue`: session inspection page.
- `admin/src/views/LogsView.vue`: request log viewer with expandable detail tabs, per-round normalized input/cache badges, cache-structure evidence, and raw-versus-normalized upstream response-shape verdicts.
- `admin/src/views/CalendarView.vue`: day/week/month diary reading view (month grid, entry lists, reading pane, collapsed context-injection settings with a day-page offset).
- `admin/src/views/ArchiveView.vue`: chat archive reader and origin-book clip flow.
- `admin/src/views/ConflictView.vue`: three-tier bookshelf for revisioned `我是谁`, generated read-only `家现在`, owner-only `家里地图`, and frozen origin books; keeps their distinct visibility and write boundaries explicit.
- `admin/src/views/bookshelf/HomeBookModal.vue`: generated-home reader for live commit/confirmation state, resident components, weekly impacts, and append-only annotations.
- `admin/src/views/bookshelf/ProjectMapBookModal.vue`: owner-facing atlas shell for live status, page selection, and the Admin-only visibility boundary.
- `admin/src/views/bookshelf/ProjectMapOverviewPanel.vue`: progressive overview for resident mechanisms, Agent architecture zones, and cross-zone bridges.
- `admin/src/views/bookshelf/ProjectMapFlowPanel.vue`: interactive request route from client entry through context, tools/upstream, capture, and return.
- `admin/src/views/bookshelf/ProjectMapConnectionsPanel.vue`: one-hop component coupling map derived from shared mapped source files, with explicit architecture bridges as secondary evidence.
- `admin/src/views/bookshelf/ProjectMapChangesPanel.vue`: review state, resident-impact changes, component confirmations, and current-document evidence.
- `admin/src/views/bookshelf/ProjectMapDeliveryPanel.vue`: owner-facing chronological delivery journal with product filters, explicit local/pushed/deployed/device-verified status, expandable verification, and optional lessons/debug links.
- `admin/src/views/RoomView.vue`: room mode admin preview shell (charge, traces, drawer notes, pins, and newspaper placement).
- `admin/src/views/room/RoomNewspaperPanel.vue`: in-place Room newspaper panel (generate, review, publish, discard, and source status).
- `admin/src/views/ToolErrorsView.vue`: tool error log viewer.
- `admin/src/components/AppShell.vue`: shared admin navigation and layout, including the day/night (日月) theme toggle.
- `admin/src/theme/tokens.css`: day/night design tokens (昼 = #fdf6f4 淡奶油底 + 纯白卡 with soft rose 软玫瑰粉 as the interactive primary, 夜 = gilt-on-near-black 描金; 古金描线与玫瑰软木板只在记忆网络视图内使用) — one tree, two palettes swapped via `<html> data-theme`. Includes the role-semantic palette (你 = soft rose 软玫瑰粉 `--sy-self`, 沈予 = deep pine 深松绿 `--sy-resident`, 系统 = ink/paper gray `--sy-sys-*`; gilt only draws lines) — new elements must join an existing role instead of introducing new colors. View styles read these variables (`var(--sy-ink)` etc.) instead of hardcoding day-only hexes, so night mode stays legible everywhere. `admin/src/theme/theme.ts`: `useTheme()` toggle + localStorage persistence; naive-ui overrides in `App.vue` read the same palette, and `AppShell.vue`'s global naive skin applies to day only.

- `admin/src/demo/`: 演示数据模式（`?demo=1`）——`fixtures.ts` 编造样本（锚点/便签/一池可"想起"的原件），`index.ts` 在 axios 适配器层拦截读取请求返回样本、写操作假成功；生产构建带此代码但不开关完全不生效。页头"演示数据"徽章在 `AppShell.vue`。
- `scripts/project_delivery.py`: records and validates one coherent owner-facing delivery outcome in `project_delivery_log.jsonl`; use it after the final verification round, not once per small commit.
- `scripts/vps_gateway_logs.py`: content-light request/cache log reader with public-API and VPS/SSH fallbacks; POSIX `--via-ssh` keeps its OpenSSH control socket under a private `/tmp` directory so a read-only `~/.ssh` cannot block diagnostics.
- `admin/scripts/mobile-shots.mjs`: mobile-viewport acceptance shots — boots the isolated preview with demo data, walks home → mem → memory graph → recall board → reading overlay at 390×844 and saves PNGs to `admin/.shots/`. 前端风格与手感基线见 `docs/frontend/STYLE_AND_CRAFT.md`。
- `admin/e2e/smoke.spec.ts`: read-only Chromium smoke checks for every Admin route and a few core interactions.
- `admin/playwright.config.ts`: isolated local gateway, temporary SQLite, authentication, and browser settings for Admin smoke tests.
- `scripts/admin_preview.py`: isolated built-Admin preview launcher that disables repository `.env`, external stores, archives, and background workers.

### PWA chat frontend

- `pwa/src/App.vue`: ChatNest-inspired mobile chat surface with real-time response rendering, Thinking/tool/echo process strips fixed above each intact assistant reply, per-trace detail sheet, Claude-style Projects/Artifacts/Memory/Diary workspace shells, gateway-backed Recents, edit/retry actions, local assistant roll variants with arrow switching, clean cold-start recovery, image previews, an expandable image/Room `+` menu, and one shared gray reply-meta line for Room time plus context/cache/first-round-hit/heartbeat status. Echo content is retained in the PWA transcript and rendered through the existing process sheet with a soft-pink detail surface; it is not a standalone panel. The Vue shell owns UI state and orchestration only; protocol, history, and persistence logic live in the modules below.
- `pwa/src/echo.ts`: leading echo marker parsing and model-facing tagged-content reconstruction for handoff and outbound history.
- `pwa/src/types.ts` / `pwa/src/utils.ts`: shared domain types (messages, variants, sessions, process timeline, presets) and id/Unicode-safe text-offset helpers.
- `pwa/src/api/client.ts` / `pwa/src/api/presets.ts` / `pwa/src/api/upstreamHeaders.ts`: gateway HTTP layer — PWA identity headers, models/sessions/config/chat fetchers for streaming and non-streaming requests, outbound message wiring, deployed-build fetches — plus reading the Console-shared `shenyu_upstream_presets` storage and the browser-local per-request upstream-header preset/editor state.
- `pwa/src/buildInfo.ts`: validates the build identity embedded in the active client and the protected deployed `build-info.json` manifest; the settings sheet compares the two exact build ids.
- `pwa/src/meta/statusSuffix.ts` / `pwa/src/meta/roomEntry.ts`: generates and parses the normal user-status suffix and the exact timestamped Room-entry contract used for hidden entry rows and `HH:mm · 房间` reply labels.
- `pwa/src/session/history.ts`: thread-handoff history source selection (context snapshots → legacy snapshot field → inspection-stream fallback), cold-start clean baseline rows, exact-duplicate detection, and recovery dedupe.
- `pwa/src/session/reconcile.ts`: tail-only reconciliation after a background disconnect — anchors the local last user turn against the session detail's raw `recent_messages` rows and adopts the server-drained reply only when it is strictly longer; never replaces the whole transcript.
- `pwa/src/session/toolHydration.ts`: rebuilds tool start/end events for snapshot-restored assistant rows from raw `tool` rows (tail-first, one group per assistant row, only when local events are empty).
- `pwa/src/session/variants.ts` / `pwa/src/session/persistence.ts`: local assistant roll-variant state machine and the localStorage transcript window save/restore.
- `pwa/src/stream/sse.ts` / `pwa/src/stream/completion.ts` / `pwa/src/stream/timeline.ts`: streaming and non-streaming OpenAI-compatible response parsing (including `shenyu.tool_event`, `shenyu_echo`, and content-free `shenyu.response_meta` data), echo/thinking/tool offset bookkeeping and stream pump, and grouping process events into inline strips and detail timelines.
- `pwa/tests/` + `pwa/vitest.config.ts`: Vitest unit suite (`cd pwa && npm test`) covering history source priority, dedupe recovery, roll variants, persistence window limits, SSE parsing, timeline grouping, and per-request upstream-header persistence/payload mapping.
- `pwa/src/ChatNestSprite.vue`: ChatNest status-sprite player using the demo's Web Animations API and per-mode frame loop configuration.
- `pwa/src/chatnestSprite.ts`: user-supplied private ChatNest status sprite set for the personal PWA deployment.
- `pwa/src/markdown.ts`: sanitized Markdown rendering with Highlight.js code highlighting.
- `pwa/src/toolLanguage.ts`: gateway tool-name normalization and resident-facing warm action copy.
- `pwa/src/styles.css`: responsive chat layout, bundled Anthropic Sans/Serif typography, ChatNest-matched composer geometry, animated status mark, bottom sheets, message actions, Markdown typography, and tool trace states.
- `pwa/public/manifest.webmanifest` / `pwa/public/sw.js` / `pwa/src/main.ts`: installable PWA shell; the service worker never caches `/v1/`, `/api/`, or the deployment-proof `/chat/build-info.json` response, and each build registers its worker with its own build id.
- `shenyu_gateway/middleware.py`: gives `/chat/sw.js`, `/chat/build-info.json`, and the admin shell pages (`/`, `/admin`, `/admin/`) explicit browser/CDN `no-store` headers so an outer cache cannot impersonate an old deployment or mix stale JS with fresh CSS.
- `pwa/vite.config.ts` / `pwa/scripts/`: isolated development server on port `5174`, build-time identity injection plus `build-info.json` emission, and a local build assertion that the active bundle contains that identity.
- `Dockerfile` + `gateway.py`: production PWA build and protected static `/chat/` mount served by the same gateway origin as `/admin/`; `SOURCE_COMMIT` is passed into the PWA builder so a deployed manifest can prove its source revision.
- Cross-client handoff uses the existing `X-Shenyu-Session-Tag`: `X-Shenyu-Client` identifies the surface, while the session tag keeps Operit and PWA on one gateway thread. PWA's `接入线程` action loads the newest trimmed client transcript from `context_snapshots` before sending (falling back to the legacy inspection stream only when no snapshot exists), using the Admin `客户端上下文保留` value for its history request, and `/chat/?session_tag=<tag>` supports an exact handoff. The PWA keeps roughly the gateway high-water window locally; once it sends a full client window, the gateway retires any temporary cold-start bridge for that session and uses the PWA transcript directly.

### 按产品对象反查

`Maintenance Map` 解决“文件在哪里”；这张小表解决“我看到产品里的哪个东西，应该从哪里进去”。它是反查索引，不替代路径地图，也不要求为每个私有 helper 再建一条记录。

这里的“产品对象”是有稳定维护入口的主导航桶，可以是一块用户表面或一项长期能力，不是每个按钮、字段或单次修改。施工记录用它表示主要归属；更细的功能写在 `title` / `touchpoint`，跨区影响由 `paths` / `docs` 表达，不为一项小功能临时新增产品对象。

| 产品对象 | 常用叫法 / 旧名 | 后端入口 | Admin/API | 现行文档 |
|----------|-----------------|----------|-----------|----------|
| 共享书架 | `家现在`、`我是谁`、`来历书`（旧内部名：矛盾书） | `resident_books.py`、`conflict_books.py` | `admin/src/api/books.ts`、`ConflictView.vue`、`bookshelf/HomeBookModal.vue` | `REQUEST_CONTEXT.md` § Generated home and living identity / Origin books |
| 家里地图 | 给圆圆的项目地图、Owner map | `project_map.py` | `GET /api/project-map`、`admin/src/api/books.ts`、`bookshelf/ProjectMapBookModal.vue` | `SYSTEM_ZONES.md`、`REQUEST_CONTEXT.md` § Owner-only project map |
| Admin 控制台 | 管理后台、家里后台 | `admin/src/App.vue`、`admin/src/views/` | `admin/src/`、`scripts/admin_preview.py` | `docs/frontend/STYLE_AND_CRAFT.md`、`START_HERE.md` |
| PWA 聊天端 | 手机聊天、独立 PWA、`shenyu-pwa` 客户端 | `pwa/src/App.vue`、`shenyu_gateway/chat_pipeline.py`、`streaming.py` | `GET /v1/models`、`POST /v1/chat/completions`、`X-Shenyu-Tool-Events`、`shenyu_upstream_presets` | `SYSTEM_ZONES.md` § 客户端表面、`REQUEST_CONTEXT.md` § External Frontend Contracts |
| Memory Island | Stars + Mem 当前岛 | `memory_island.py`、`context_builder.py` | `admin/src/api/logs.ts`、`LogsView.vue` | `REQUEST_CONTEXT.md`、`MEMORY_ROOM.md` |
| Stars | 星星 / 关联记忆 | `shenyu_gateway/stars/` | `admin/src/api/stars.ts`、`StarsView.vue`、`views/stars/` | `MEMORY_ROOM.md` § Star Memory Layer |
| Mem | Mem Notes / 便签 | `shenyu_gateway/mem_notes/`、`mem_notes_relevance.py` | `admin/src/api/mem0.ts`、`Mem0View.vue` | `MEMORY_ROOM.md` § Mem Note Layer |
| 记忆网络 | 人物 / 地点 / 物件 / 主题锚点 | `memory_graph.py`、`shenyu_gateway/recall/` | `admin/src/api/memoryGraph.ts`、`MemoryGraphView.vue`、`Mem0View.vue` | `MEMORY_ROOM.md` § Personal Memory Graph |
| Room | 房间 / 窗台 | `private_capture.py`、`room_context.py`、`room_tools.py`、`room_newspaper.py` | `pwa/src/App.vue`、`pwa/src/meta/roomEntry.ts`、`admin/src/api/room.ts`、`RoomView.vue`、`views/room/` | `MEMORY_ROOM.md` § Room Mode |
| 请求日志 / 工具报错 | 日志页、工具报错页 | `request_logs.py`、`tool_loop.py`、`store/_admin.py` | `admin/src/api/logs.ts`、`toolErrors.ts`、`LogsView.vue`、`ToolErrorsView.vue` | `DEBUGGING_GUIDE.md`、`LOGS_GUIDE.md` |
| Calendar | 日历 / 日周月页 | `calendar_service.py`、`gateway_tools/_calendar.py` | `admin/src/api/calendar.ts`、`CalendarView.vue` | `REQUEST_CONTEXT.md` § Calendar |

When cleaning or refactoring, preserve behavior first and move code by boundary:

1. Route handlers should stay thin and call service classes.
2. SQLite reads/writes belong in `GatewayStore`; do not query SQLite directly from route handlers.
3. Supabase HTTP mechanics belong in `SupabaseClient`; table-specific behavior can live in service classes.
4. Context data fetching belongs around `ContextBuilder`; layer rendering and message-window assembly belong in `shenyu_gateway/context_layers.py`.
5. Private response tag filtering and capture helpers belong in `shenyu_gateway/response_capture.py` and `shenyu_gateway/private_capture.py`. When adding a new private block type, update both parser paths and the empty-reply fallback wording.
6. Gateway-native tool behavior belongs in `shenyu_gateway/gateway_tools/` (one mixin per tool category); tool schemas, merge logic, and name dispatch belong in `shenyu_gateway/tool_registry.py`. Keep tool descriptions short: one-line purpose plus backing table/pool.
7. Star memory ranking and learning behavior belongs in `shenyu_gateway/stars/`; tool exposure belongs in `tool_registry.py`; admin-only API routes belong in `gateway_admin_routes.py`; frontend controls belong in `admin/src/views/StarsView.vue` and `admin/src/views/stars/`.
8. Upstream protocol conversion belongs in `shenyu_gateway/upstream_adapter.py`; request routing, HTTP calls, and streaming iteration belong in `shenyu_gateway/upstream_client.py`.
9. External frontend contracts below are not dead code just because admin UI does not import them.

## Subsystem Guides

README 只保留项目入口、维护地图、外部硬契约、配置与运行方式。现行子系统细节按责任区维护：

- `docs/architecture/REQUEST_CONTEXT.md`：上下文层、prompt cache、流式与工具、SQLite、Supabase、召回索引、cold start、Calendar、外部前端契约和归档。
- `docs/architecture/MEMORY_ROOM.md`：Mem Notes、Star Memory、Room Mode 和 private capture fallback。
- `docs/architecture/SYSTEM_ZONES.md`：八个系统区、跨区桥梁和审计入口。
- `docs/architecture/AUDIT_MATRIX.md`：风险、测试缺口、已确认修改和后续顺序。
- `DESIGN.md`：长期设计原则和语义边界；准备修改记忆内核时阅读。

历史专题稿和审查快照的状态见 `DOCS_MAP.md`。

## Configuration

Important environment variables:

```text
UPSTREAM_URL=https://api.treegpt.cc
ANTHROPIC_API_KEY=
UPSTREAM_PROTOCOL=openai
UPSTREAM_PROXY=
UPSTREAM_TRUST_ENV=false
ENABLE_OPENAI_CACHE_CONTROL=true
ENABLE_ANTHROPIC_CACHE_CONTROL=true
OPENAI_CACHE_TTL=5m
ANTHROPIC_CACHE_TTL=1h
ENABLE_ANTHROPIC_AUTO_THINKING=false
ANTHROPIC_AUTO_THINKING_EFFORT=
UPSTREAM_EXTRA_BODY=
UPSTREAM_PASSTHROUGH_HEADERS=

ENABLE_COLD_START=true
COLD_START_MESSAGE_LIMIT=
MAX_CLIENT_MESSAGES=75

INJECT_MEM_NOTES=true

ENABLE_HEARTBEAT_ARCHIVE=true
HEARTBEAT_ARCHIVE_RECONCILE_DELETIONS=false

INJECT_STARS=true
ENABLE_STAR_EMBEDDINGS=false
STAR_INJECT_LIMIT=3
STAR_REVIEW_NEW_LIMIT=4
STAR_REVIEW_CANDIDATES_PER_STAR=2
STAR_REVIEW_TOTAL_CANDIDATE_LIMIT=8
STAR_CHAT_EXPLICIT_FALLBACK_LIMIT=1
STAR_MIN_SCORE=0.008
STAR_RELATED_MIN_SCORE=0.22
STAR_RECENT_FATIGUE_HOURS=6
STAR_RECENT_FATIGUE_PENALTY=0.14
STAR_SOFT_DIRECT_COOLDOWN_TURNS=8

ROOM_NEWSPAPER_QA_ENABLED=false
ROOM_NEWSPAPER_LLM_MODEL=
ROOM_NEWSPAPER_LLM_URL=
ROOM_NEWSPAPER_LLM_API_KEY=
ROOM_NEWSPAPER_LLM_PROTOCOL=

DEFAULT_SURFACE_LIMIT=3

ENABLE_UPSTREAM_TOOLS=true
ENABLE_GATEWAY_TOOLS=true
ENABLE_MEM0_MANAGEMENT_TOOLS=true
EXPOSE_SUPABASE_TOOLS=true
GATEWAY_TOOL_MODE=broker
GATEWAY_TOOL_SURFACE=full
CLIENT_TOOL_SURFACE=all
MAX_INTERNAL_TOOL_ROUNDS=15
```

`UPSTREAM_PROXY` is optional. Use it when the gateway host can only reach the upstream API through a local proxy, for example:

```text
UPSTREAM_PROXY=http://127.0.0.1:7897
```

When `UPSTREAM_PROXY` is set, upstream LLM requests use that explicit proxy and ignore ambient proxy environment variables. If you prefer to inherit `HTTP_PROXY` / `HTTPS_PROXY` from the process environment, leave `UPSTREAM_PROXY` empty and set `UPSTREAM_TRUST_ENV=true`.

Cloudflare Tunnel only handles inbound traffic to the gateway. It can make `https://your-domain` reach `localhost:8010`, but it does not by itself make the gateway's outbound connection to `UPSTREAM_URL` work. If requests fail with `无法连接上游 ... All connection attempts failed`, check the gateway machine's outbound route to the upstream host, local proxy/TUN mode, and `UPSTREAM_PROXY`.

`UPSTREAM_EXTRA_BODY` is a JSON object merged into every upstream request body. It is the single customization point for request-body fields the gateway does not manage itself, including `provider`:

```text
# Pin the upstream provider (Pioneer-style string):
UPSTREAM_EXTRA_BODY={"provider":"Amazon Bedrock"}
# Or an ordered provider list (OpenRouter-style order object):
UPSTREAM_EXTRA_BODY={"provider":{"order":["Amazon Bedrock","OpenAI"]}}
# Extra non-provider fields, e.g. a custom model list:
UPSTREAM_EXTRA_BODY={"models":["claude-opus-4-7"]}
```

The merge is a shallow `payload.update(extra_body)`, so an explicit `model`, `messages`, or `tools` key would override the gateway-built body. The admin UI warns on save when one of those core fields is present; treat such overrides as deliberate only. The provider field is honored on OpenAI-compatible upstreams and is dropped on the Anthropic protocol (Anthropic has no provider concept).

`UPSTREAM_PASSTHROUGH_HEADERS` is a comma-separated or JSON-array whitelist of client request headers forwarded to the upstream. Defaults to `x-api-key` when unset. Reserved headers are always excluded even if listed: `authorization`, `content-type`, hop-by-hop headers, and the gateway's own identification headers (`X-Shenyu-*`, `X-Session-Tag`, `X-Client-Name`) — the gateway rebuilds or isolates those itself.

`ChatRequest.upstream_headers` is the per-request counterpart used by the PWA's model sheet. The PWA stores its editable key/value rows only in that browser and ships completed rows with chat requests; the gateway validates and maps them to actual OpenAI-compatible or Anthropic upstream headers. The Claude Code preset mirrors the locally captured CLI/SDK identity layer: `User-Agent: claude-cli/2.1.201 (external, sdk-cli)`, `Accept`, `Anthropic-Beta`, `X-App`, `X-Claude-Code-Session-Id`, the observed `X-Stainless-*` fields, and the direct-browser-access marker. It also sends the standard Anthropic `metadata.user_id` shape with a random browser-local device id, empty account UUID, and the same session UUID. Device and session ids remain fixed to preserve upstream prompt-cache continuity; only the explicit model-sheet refresh action rotates the session UUID. The preset deliberately does not copy Claude Code's coding system prompt or tool schemas, which would change Shenyu's identity and tool semantics. Gateway authentication, protocol version, cookie, hop-by-hop, and `X-Shenyu-*` headers remain gateway-owned. Header values are not request-log fields or persistent history; simulated metadata can appear only in the live full payload when `GATEWAY_LOG_FULL_PAYLOADS=true`, not in the safe persistent request-log tier. The safe summary records only five identity-shape booleans so production logs can prove what was emitted without exposing header values, UUIDs, device ids, or metadata text. When omitted, upstream requests are unchanged.

Legacy `UPSTREAM_PROVIDER_ORDER` / `UPSTREAM_PROVIDER_FORMAT` / `UPSTREAM_PROVIDER_ORDER_ENABLED` are deprecated: on startup they are auto-migrated into `UPSTREAM_EXTRA_BODY["provider"]` (OpenAI-compatible only) and a warning is logged. Move the value into `UPSTREAM_EXTRA_BODY`; these legacy variables will be removed in a future release.

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

# Build both browser frontends
cd admin && npm ci && npm run build && cd ..
cd pwa && npm ci && npm run build && cd ..

# Start the gateway (serves built Admin and PWA frontends)
python gateway.py
```

Supabase schema migrations are deliberately not run by gateway startup. Before deploying a feature that adds a table, index, or RPC, apply its named file from `supabase/migrations/` in the project's Supabase migration workflow, then deploy the code that depends on it. Verify the new table/RPC and its Admin/API route before using the feature with resident data.

UI routes:

```text
http://localhost:8010/admin
http://localhost:8010/chat/
```

`/` redirects to `/admin`, so the admin login is the single main browser entrypoint. The same gateway key protects `/admin` and `/api/*`.

`/admin` is the formal Vue/Vite admin app. `/chat/` is the installable PWA client. They share the gateway origin, so the PWA can reuse the Admin login cookie/token and the Admin Config page's `shenyu_upstream_presets` localStorage entries.

`/admin` is organized by feature:

- `admin/src/api/config.ts`: gateway and upstream configuration.
- `admin/src/api/mem0.ts`: Mem config, mem-note review APIs, and old atomic read-only lookup.
- `admin/src/api/memoryGraph.ts`: personal memory-graph management and source-anchor APIs.
- `admin/src/api/stars.ts`: Star list/search/create/review/feedback/connect APIs.
- `admin/src/api/sessions.ts`: local SQLite session browser.
- `admin/src/api/logs.ts`: request log list and detail APIs.
- `admin/src/api/calendar.ts`: read-only calendar month grid and page detail.
- `admin/src/views/ConfigView.vue`: configuration page.
- `admin/src/views/Mem0View.vue`: Mem injection/tool controls, full-set two-state recall-eligibility management, Shenyu-write provenance badges, mem-note attributes, and old atomic read-only lookup. The "静音但保留工具" preset turns off automatic Mem injection while leaving gateway tools available.
- `admin/src/views/MemoryGraphView.vue`: entity/alias/relation management, historical source-link backfill, and read-only Recall preview at `/memory-graph`.
- `admin/src/views/StarsView.vue`: standalone Star entry shell at `/stars`, with split Star panels under `admin/src/views/stars/` and a lazy-loaded memory star map at `/stars/map`.
- `admin/src/views/SessionsView.vue`: session inspection page.
- `admin/src/views/LogsView.vue`: request log viewer with expandable detail tabs, per-round normalized input/cache badges, cache-structure evidence, and raw-versus-normalized upstream response-shape verdicts.
- `admin/src/views/CalendarView.vue`: day/week/month diary reading view.
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

- After a resident-facing runtime or configuration change, run `python scripts/resident_home.py check`; review affected entries with `python scripts/resident_home.py review <component> --summary ... --impact ...` or explicitly acknowledge `--no-impact`.
- Search the active code paths for retired summary/window env vars and the removed short-lived notes table; they should not appear.
- `GET /api/gateway/context/preview` should show `stable`, optional `slow`, optional `mem`, `heartbeat`, `tool_policy`, and `format`.
- When `INJECT_STARS=true`, relevant stars that clear `STAR_RELATED_MIN_SCORE` and `STAR_MIN_SCORE` should appear in the `mem` layer before mem notes; `STAR_INJECT_LIMIT` is an upper bound, not a promise to always inject that many.
- `GET /api/gateway/logs` should show prompt cache breakpoints and cold-start metadata.
- `GET /api/gateway/logs/{id}` should show `response_full` for retained payloads; the list view should keep using short previews.
- `GET /api/books` should expose the lightweight unified overview; `/api/books/home` reads the generated home snapshot, `/api/books/identity` owns revisioned writes, and origin books stay behind the frozen conflict-book service.
- After star-memory edits, run `pytest -q test_star_memory.py test_gateway_tool_registry.py test_response_capture.py test_gateway_tags.py`.
- Run `python -c "import test_gateway_streaming as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]"` after streaming/tool-loop edits when `pytest` is unavailable.
- Run `python -c "import test_upstream_adapter_stream as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]"` after upstream stream adapter edits when `pytest` is unavailable.
- Run `cd admin && npm run build` after Admin UI edits unless the required check is `npm run test:e2e`, which already includes the production build.
- Run `cd admin && npm run test:e2e` after Admin routes, page loading, or core interactions change. Install Chromium and its system libraries once with `npm run test:e2e:install`; if the official browser CDN stalls on the current WSL network, use `npm run test:e2e:install:mirror`. The suite checks that pages are alive and interactive, not that they are visually identical.
- Run `python -m py_compile gateway.py shenyu_gateway/*.py` after edits.

## Active Review Plan

当前分区风险、证据、已确认修复和后续审计顺序统一维护在 `docs/architecture/AUDIT_MATRIX.md`。

旧 Claude code-review 的逐项执行清单已迁到 `docs/history/CLAUDE_REVIEW_FOLLOW_UP.md`，仅用于理解历史背景，不作为当前待办来源。

## DevOps Plan | 部署计划

### Deploy to Coolify

1. Push this repo to a git remote (GitHub/GitLab).
2. In Coolify, create a new service → select this repo.
3. Use the `Dockerfile` — Coolify detects it automatically.
4. Set environment variables in Coolify's dashboard (`.env` content).
5. Port mapping: `8010:8010`.
6. Coolify auto-deploys on every git push.

For the resident home snapshot to show the deployed revision inside the image, pass the source SHA as the Docker build argument `SOURCE_COMMIT` (or set the runtime environment variable with the same name). The image intentionally omits `.git`.

If local sessions, context snapshots, pending tool turns, persisted request-log summaries, or Admin configuration overrides must survive container replacement, mount a persistent volume at `/app/data` (or the parent directory configured by `GATEWAY_DB_PATH`). The Dockerfile does not declare a volume, so the default `/app/data/shenyu_gateway.db` otherwise belongs to the disposable container filesystem. Supabase archives are independent of this local volume. `GATEWAY_REQUEST_LOG_RETENTION` controls the bounded history size and defaults to `200`; full debug payloads are never written to this history.

### Frontend workflow

| Environment | Command | URL |
|---|---|---|
| Local dev | `cd admin && npm run dev` | `http://localhost:5173` (hot reload) |
| PWA dev | `cd pwa && npm run dev -- --host 0.0.0.0` | `http://localhost:5174/chat/` (the only mapped PWA development server; gateway proxy on `8010`) |
| Isolated full preview | `cd admin && npm run preview:isolated` | `http://127.0.0.1:18112/admin/` (no `.env`, Supabase, archives, or workers) |
| Production | Docker builds `admin` + `pwa` → served by Python from `dist/` | `https://your-domain/admin/`, `https://your-domain/chat/` |

Any other local port is an ad-hoc preview, not a defined PWA environment. It may serve a stale `dist/`, a different process, or no gateway at all; identify its build from the PWA settings before using it for diagnosis, and never use it as production acceptance.

**Before each deploy to Coolify:**
1. Make frontend changes in `admin/` or `pwa/`.
2. Run the matching frontend build locally (`npm run build`) before handoff.
3. Commit and push the reviewed change. Coolify rebuilds the Dockerfile when its Git service has auto-deploy/webhooks enabled for the tracked branch; the Dockerfile now runs both frontend builds, so no `dist/` directory needs to be committed.
4. Ensure Coolify passes the full source SHA as Docker build arg `SOURCE_COMMIT`; the PWA builder records it in the protected deployment manifest.
5. Open `/admin/` once to log in, then open `/chat/` on the same domain. In PWA「聊天设置」confirm that the current running build and deployed build match before accepting a user-visible PWA fix; then reproduce the original scenario on the affected device. If that observation is unavailable, report the change as unverified. The PWA's preset selector reads the same-origin Admin preset store.

### Future improvements (when needed)

- Keep the Dockerfile's Admin/PWA build stages aligned with their `package-lock.json` files.
