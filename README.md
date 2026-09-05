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

The codebase is partly layered already. Entries owe a path and a responsibility: a restyle changes this map only when it invalidates a layout, component, or effect that an entry names.

### Core entrypoint

- `gateway.py`: FastAPI app entrypoint, lifespan, CORS, route registration, and model listing. Chat, calendar, admin, archive, and config routes have been extracted into dedicated modules. The PWA upstream-auth preflight headers are allowed here because the PWA may call a gateway on a different origin.

### Config & runtime

- `shenyu_gateway/config.py`: environment-backed runtime config.
- `shenyu_gateway/runtime.py`: shared runtime utilities (logger, `now_ts`, `iso_now`, `json_dumps`, dotenv loading, and the repository's single local-timezone definition plus its day helpers).
- `shenyu_gateway/schemas.py`: Pydantic data models (`ChatMessage`, request/response shapes).

### Storage

- `shenyu_gateway/store/`: SQLite runtime state (package split into mixins: `_base`, `_sessions`, `_messages`, `_pending`, `_snapshots`, `_cold_start`, `_heartbeats`, `_room`, `_album`, `_admin`, `_window_state`, `_request_log_history`).
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
- `shenyu_gateway/context_layers.py`: stable/slow/mem/island-bumps/heartbeat/tool-policy/format layer rendering (including the optional echo prompt immediately before Heartbeat), client message trimming, and cold-start bridge insertion.
- `shenyu_gateway/project_map.py`: owner-only live project map assembled from the current system zones, maintenance/product indexes, resident component fingerprints, and change ledger; it derives one-hop component links only from mapped source files claimed by exactly two components, while broader shared hubs remain cross-zone bridge evidence.
- `shenyu_gateway/project_delivery.py` / `project_delivery_log.jsonl`: structured owner-facing delivery ledger and validation/append helpers; one entry represents one coherent completed outcome and links it to a product, paths, docs, verification, and optional reusable lesson.
- `shenyu_gateway/resident_home.py`: resident-facing component manifest, source fingerprints, review acknowledgements, and weekly change records.
- `shenyu_gateway/resident_books.py`: unified bookshelf facade for the generated read-only home snapshot, the revisioned `我是谁` document, append-only annotations, and legacy origin-book storage.
- `shenyu_gateway/resident_profile.py`: stable wake/profile text for memory practice and the origin book.
- `shenyu_gateway/context_snapshots.py`: context snapshot creation and helpers for cold-start sources.
- `shenyu_gateway/context_window.py`: semantic history-event classification, chunk-safe client-history windowing with high-water/epoch/anchor state, and cold-start bridge overlap deduplication.
- `shenyu_gateway/system_prefix_buffer.py`: system-prefix buffer gate — holds newly written heartbeat/calendar layers behind the configured cache window (or until the next trim) so a fresh receipt does not rewrite the `system.end` cache prefix every turn; buffered removals are applied when the window expires or the next trim rebuilds the epoch.
- `shenyu_gateway/client_extra.py`: shared recognition/stripping of client-injected per-message extras (Operit `message_insert_extra_bundle` attachments and the PWA tail status suffix) plus the expired-photo placeholder contract, imported by trimming, archiving, history normalization, and recall-query cleaning.
- `shenyu_gateway/memory_island.py`: Stars/Mem island rendering and per-lane retain/rewrite state, including overlap decisions and current/added/updated/removed log summaries.
- `shenyu_gateway/island_bumps.py`: 小突起 — stateless one-line receipts for the memory writes Shenyu already made this waking day (stars, mem notes, calendar, and 盼圃's `plant` action only), rendered as a block trailing the island so repeats stop happening.
- `shenyu_gateway/prepare_messages.py`: cold-start snapshot preparation, runtime state pruning, pending gateway tool turn injection, and message/tool-call helpers.

### Upstream communication

- `shenyu_gateway/upstream_adapter.py`: pure OpenAI/Anthropic message, cache, stream, and model URL conversion helpers.
- `shenyu_gateway/upstream_client.py`: upstream HTTP client construction, protocol detection, URL routing, request building, streaming chunk iteration, model listing, and connection error formatting.
- `shenyu_gateway/upstream_response_evidence.py`: content-free counters for raw upstream response shapes and their OpenAI-compatible normalized output, shared by streaming, non-streaming, and tool-loop paths.

### Tools

- `shenyu_gateway/gateway_tools/`: gateway-native tool implementations (`GatewayToolService`, package split into mixins like stars/: `_supabase`, `_recall`, `_mem_notes`, `_stars`, `_books`, `_calendar`, `_sessions`, `_windowsill`, `_album`, `_notebook`, `_web`, `_compat`, plus shared `_runtime`/`_helpers`/`_base`). `__init__.py` assembles the service and re-exports `configure_gateway_tools` / `get_runtime`. `_web` is the 窗外 pair: `shenyu_web_search` (Serper, `SERPER_API_KEY`) and `shenyu_web_read` (Jina Reader, `JINA_API_KEY` — required from datacenter IPs).
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

### Album

沈予's own album: images he chose to keep, each with the words he wrote about it. Deliberately split across two homes.

- `shenyu_gateway/store/_album.py`: local SQLite `album_books` / `album_photos` — image bytes as BLOBs on the mounted volume, plus `album_notes_by_fingerprints` for expiry backfill. Listing queries never select the blob column, so browsing the album does not move megabytes. Image bytes never reach Supabase or the request log.
- `shenyu_gateway/gateway_tools/_album.py`: `shenyu_album_save` / `shenyu_album_list`, image-block decoding for both the OpenAI data-URL and Anthropic `source.data` shapes, and the note sync to Supabase `shenyu_album_notes` plus Recall indexing. `latest_turn_images()` reads the newest image turn from the messages instead of requiring a marker in the body — writing one would change history normalization and make branch detection reset the prompt-cache epoch. A failed note sync leaves the photo saved; only its searchability is lost.
- `supabase/migrations/20260830_shenyu_album_notes.sql`: the note half. Recall's adapters all read Supabase only, so text must live here to be recallable; keeping it separate also means a lost volume costs the images, not the words.
- `shenyu_gateway/recall/_sources.py` `_load_album_notes` / `index_album_note_row`: indexes only the text, carrying `photo_id` in metadata so a hit can reopen the image.
- `shenyu_gateway/client_extra.py` `EXPIRED_IMAGE_MARKER` / `expired_image_note_text` / `is_expired_image_note`: the one home for the expired-photo placeholder contract, shared verbatim by the PWA wire format, trimming, and history normalization. The replacement text is `prefix。——his words`; the fixed prefix is load-bearing, not decoration — normalization matches on it, so changing what he wrote never alters the normalized history and cannot be mistaken for an edit.
- `shenyu_gateway/context_layers.py` `trim_client_image_blocks`: an expired-photo marker is replaced unconditionally, outside the newest-two-turns exemption, because there is no image in it to keep — leaving one in forwards a block the upstream rejects. Saved photos get his own words (appended as a text block when the turn also has text, so it still reaches the model); unsaved ones keep the generic placeholder. `expired_image_fingerprints()` collects the request's fingerprints for one batched album lookup in `prepare_messages`, which degrades to the generic placeholder on any store error rather than blocking the conversation.
- `shenyu_gateway/gateway_admin_routes.py` `GET /api/gateway/album` and `GET /api/gateway/album/photo/{id}`: read-only listing and one immutable, id-addressed bytes route.

### 盼圃 (Orchard)

The wall where things that have not happened yet hang. 圆圆 named it. Green fruits hang above, picked ones are turned over and pinned to the row below, so over time that row is everything they got to.

Its defining property is what it does **not** do: 盼圃 never fires. A fruit with no `due_on` hangs indefinitely, a fruit past its `due_on` still does not expire, and nothing here writes to any context layer — the only way it reaches a prompt is 沈予 calling the tool. This is the whole point of the wall as opposed to a mem note's `remind_on`, which forces a Memory Island rewrite on its day; `AGENTS.md` § Project Memory and Collaboration states the prohibition, and `tests/test_orchard.py` greps the context-assembly modules so an accidental injection path goes red.

- `shenyu_gateway/orchard.py`: the condition buckets and their wording, plus the pure functions that pick one. A fruit's condition is derived from its own history (days hung, days since anyone posted a note, note count, distance to `due_on`, the month) and then chosen deterministically from `(fruit_id, today)`. Two consequences are both deliberate: posting three notes in one day does not change what the fruit says, and the line still moves day to day in the direction its history points. `pick_condition()` uses the same measures without the day, so the picked wording is what the fruit grew into rather than a roll at pick time. This file also owns the weather layer — `classify_weather` (QWeather's Chinese `text` plus `temp_c` to an extreme-weather kind), `garden_line` (what the garden is like today), `fruit_took_scar`, and `weather_scar`.
- `shenyu_gateway/orchard_service.py`: the four actions and the three Supabase tables. `pick` is a conditional update on `status=eq.green`, so when both of them pick at once the loser is told who picked it and what they wrote instead of overwriting it. The picked condition is frozen into the row and never recomputed on read. Every action returns `garden` and records the day's extreme weather on the way through; the whole weather path is fail-soft, because a broken weather API must never be able to close the wall.

**Weather.** 盼圃 reads 圆圆's local observed weather (`WEATHER_CITY`, default 邵阳) through the existing `QWeatherService` — his weather, not the sea outside 沈予's room, because the wall is the one thing the two of them share. It works in two layers. Every action comes back with one true line about the garden today. Separately, weather that leaves a mark (hail, downpour, strong thunderstorm, gale, snow, dust, cold snap, heat wave) is recorded one row per `(on_day, kind)`, and at pick time a fruit that hung through such a day may wear it: hail gives `half_good`, a downpour `watered_down`, a cold snap `sweetened`.

Those rows live in local SQLite (`orchard_weather`, created in `store/_base.py`), **not** Supabase, on the same test the album uses: only what needs to be recalled later earns Supabase quota. Fruits and notes qualify — once picked they are things the two of them got to. Weather does not; nobody searches for "that hailstorm", it is only the material that decides what a picked fruit looks like. Reading it is also confined to `pick`: computing per-fruit weather while glancing at the whole wall would be work nobody asked for. With no local volume at all the whole weather layer is silently absent and the wall still works — weather makes 盼圃 feel real, it is not a precondition for it.

The thresholds are tuned against noise, not against meteorology. Ordinary overcast and plain rain are never recorded, and the two that would otherwise dominate are held back deliberately: a bare 雷阵雨 does not count (只有 强雷阵雨 does) because 邵阳 gets one most other days in summer, and the heat/cold bars sit at 38°C/0°C rather than 35°C/2°C for the same reason. The question each rule answers is "is this day worth entering into a fruit's history", not "is this extreme". Measured against a rough 邵阳 year that lands on about 24 rows — 7% of days — so a fruit hanging a month meets ~2 events and wears ~0.6 of them. A scar that were routine would not be a scar.

`pick` reports only the weather that actually marked **this** fruit (`_scar_story`, same `fruit_took_scar` verdict as the condition itself). Listing every event it hung through would hand back a dozen lines of weather that never touched it — those are the garden's business, not the fruit's.

Which fruit a given storm hit is **not** stored: `fruit_took_scar` derives it from `hash(fruit_id + on_day + kind)` at roughly one in three, so the same hail hits some fruits and not others and always the same ones. A stored per-fruit scar would just be a second copy that can disagree with the weather record. A scar overrides the history verdict, because weather is the only input here that neither of them controls — and waiting is waiting precisely because some things are not yours to decide.
- `shenyu_gateway/gateway_tools/_orchard.py`: `shenyu_orchard(action=plant|note|pick|look)`. Who planted or picked follows the entry point — the gateway tool is 沈予, the Admin API is 圆圆 — so it is never a model-supplied parameter.

**Naming a fruit.** `note` and `pick` accept either `fruit_id` or the fruit's `name`, resolved through `_resolve_fruit`, so nobody has to `look` first just to copy a uuid — a fruit's name is already a sentence, which is what `shenyu_books` `read origin` does with `book_id` or an exact title. A name matches green fruits first (a picked one must not be reopened by its name), and an ambiguous name is **never guessed**: it returns `error_kind=ambiguous` listing the candidates, `409` over HTTP. A misfiled note is a sentence said about the wrong thing, which is worse than one more question.

**Two grains, deliberately different.** `look` renders each fruit through `_wall_fruit`: name, who hung it and on what day, how many notes are under it, how long until its day (`还有 10 天` / `就是今天` / `过了 6 天，还挂着`), and what it looks like now. No note bodies, no uuids, no full timestamps. Touching one fruit — `plant`, `note`, `pick` — renders it through `_render_fruit` instead, with note bodies, the pick words, and the weather it wore.

The split is about size. Ten fruits with three notes each came to ~2300 tokens of mostly uuids and timestamps, when glancing at the wall only needs to know what is hanging there; it is now ~580. Notes carry `author`/`content`/`at` only — their own ids address nothing, since notes can be neither edited nor deleted. When `_render_fruit` caps the list at `NOTES_PER_FRUIT` it **says what it left out** via `earlier_notes`, because a short array under a larger `note_count` reads as "this is all there is" and the omitted ones are usually the beginning of the wait. `pick` returns the complete run inside `fruit.notes` and does not repeat it at the top level.
- `supabase/migrations/20260830_shenyu_orchard.sql`: `shenyu_orchard_fruits` and `shenyu_orchard_notes`. Notes are rows, not a JSONB array on the fruit, because two people writing at once would otherwise lose one — and the waiting is the half worth keeping. There is deliberately no expiry or archival cleanup on either.
- `shenyu_gateway/store/_orchard.py` plus the `orchard_weather` table in `store/_base.py`: the weather half, on the mounted volume. `(on_day, kind)` uniqueness with `ON CONFLICT DO NOTHING` is what lets every action record opportunistically without duplicating or racing.
- `shenyu_gateway/recall/_sources.py` `_load_orchard` / `index_orchard_fruit_row`: indexes **picked** fruits only, body being the pick words plus every note that was on it. A green fruit is still being waited on and must not be surfaced mid-conversation.
- `shenyu_gateway/gateway_admin_routes.py` `GET /api/gateway/orchard`, `POST /api/gateway/orchard/fruits` plus its per-id `notes`/`pick` routes, and `POST /api/gateway/orchard/notes` / `pick` for naming a fruit instead: 圆圆's side of the same four actions. Six routes total, and no reminder or due-polling route by design — `tests/test_orchard.py` asserts that count so adding one has to come edit the assertion first.

### Auth & sessions

- `shenyu_gateway/auth.py`: admin auth middleware, API key verification, login page HTML, and `ADMIN_PROTECTED_PREFIXES`.
- `shenyu_gateway/sessions.py`: bridge from request handling to SQLite session/message persistence.

### Route modules (extracted from gateway.py)

- `shenyu_gateway/gateway_admin_routes.py`: admin API routes (stars, mem notes, room, overview, prune, etc.).
- `shenyu_gateway/calendar_routes.py`: read-only calendar API routes (month grid, page detail).
- `shenyu_gateway/archive_routes.py`: archive reader (days/messages/literal `search`), origin-book, shared resident-book, and owner-only project-map API routes. `/api/archive/search` is case-insensitive substring over the verbatim archive — deliberately not semantic, same rule as the window-newspaper basket.
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
- `admin/src/views/MemoryGraphView.vue`: personal memory-graph console — the anchor net (anchors sharing confirmed/suggested relations form connected clusters; layout is id-sorted so a refresh does not reshuffle the net) plus a recent-activity stream. Picking an anchor runs a real recall and pins the result on the recall board (`RecallBoard.vue`); picking a ghost name opens the reading overlay (`AnchorOriginalsOverlay.vue`) of the originals that mention it, with a pin-it action. Entity/alias/relation management with candidate confirmation, an archived-anchor drawer, unanchored name candidates, and historical exact-alias backfill stay on the management side.
- `admin/src/views/memory-graph/RecallBoard.vue`: the 描金线索板 for 想起的一瞬间 — a read-only preview of what the model actually receives for one recalled word, grouping per-source papers by recall strength (脱口而出 direct / 由此及彼 related / 浮想 other) with evidence highlighting and source-anchor linking, built from the same `OriginalPaper` + `AttachAnchors` as the net's reading overlay. Positions are seeded by source key so a board stays put across refreshes. The preview response only adds the query terms used for highlighting, never scoring internals.
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
- `admin/src/components/AppShell.vue`: shared admin navigation and layout, and the home of the day/night theme switch, the online indicator, and the demo-data badge.
- `admin/src/theme/tokens.css`: the single home for all design tokens — one tree, two palettes (day/night) swapped via `<html> data-theme`, including the role-semantic palette every new element must join instead of introducing its own color. View styles read these variables rather than hardcoding hexes, so night mode stays legible everywhere. Actual values live in `docs/frontend/STYLE_AND_CRAFT.md` § 一 视觉基线, whose 金的边界 clause is the authority on where gilt and cork are allowed. `admin/src/theme/theme.ts`: `useTheme()` toggle + localStorage persistence; naive-ui overrides in `App.vue` read the same palette, and `AppShell.vue`'s global naive skin applies to day only.

- `admin/src/demo/`: 演示数据模式（`?demo=1`）——`fixtures.ts` 编造样本（锚点/便签/一池可"想起"的原件），`index.ts` 在 axios 适配器层拦截读取请求返回样本、写操作假成功；生产构建带此代码但不开关完全不生效。页头"演示数据"徽章在 `AppShell.vue`。
- `scripts/project_delivery.py`: records and validates one coherent owner-facing delivery outcome in `project_delivery_log.jsonl`; use it after the final verification round, not once per small commit.
- `scripts/vps_gateway_logs.py`: content-light request/cache log reader with public-API and VPS/SSH fallbacks; POSIX `--via-ssh` keeps its OpenSSH control socket under a private `/tmp` directory so a read-only `~/.ssh` cannot block diagnostics.
- `admin/scripts/mobile-shots.mjs`: mobile-viewport acceptance shots — boots the isolated preview with demo data, walks home → mem → memory graph → recall board → reading overlay at 390×844 and saves PNGs to `admin/.shots/`. 前端风格与手感基线见 `docs/frontend/STYLE_AND_CRAFT.md`。
- `admin/e2e/smoke.spec.ts`: read-only Chromium smoke checks for every Admin route and a few core interactions.
- `admin/playwright.config.ts`: isolated local gateway, temporary SQLite, authentication, and browser settings for Admin smoke tests.
- `scripts/admin_preview.py`: isolated built-Admin preview launcher that disables repository `.env`, external stores, archives, and background workers.

### PWA chat frontend

- `pwa/src/App.vue`: the mobile chat surface (ChatNest-derived; `docs/frontend/STYLE_AND_CRAFT.md` § 风格血统声明 records what was borrowed and the private asset pack's boundary) — session/model/preset state, streaming orchestration, per-trace detail view, sidebar links into the same-origin console (星星 / 房间 / 日志 / 配置, names matching the console's own home cards), gateway-backed Recents, edit/retry actions, local assistant roll variants, clean cold-start recovery, an image/Room `+` menu, and the shared reply-meta line for Room time plus context/cache/first-round-hit/heartbeat status. Echo content is retained in the transcript and rendered through the existing process view, not a standalone panel. The Vue shell owns UI state and orchestration only; protocol, history, and persistence logic live in the modules below, one transcript row's own rendering lives in `pwa/src/components/`, and self-contained blocks that do not write the transcript have moved into composables (`api/useUpstream.ts`, `session/useComposer.ts`). What remains in the shell is what genuinely writes `messages`: send/retry/edit, streaming orchestration, session switching, and the sheets that read across all of it — extracting those would mean passing most of the shell's state back in, which trades one large file for a wide interface.
- `pwa/src/components/ChatMessageRow.vue` / `pwa/src/components/ChatMessageBody.vue` / `pwa/src/components/MarkdownBody.vue`: one transcript row per component, so a parent state change (a composer keystroke) no longer re-renders every message, and `onErrorCaptured` on the row confines a render failure to that row instead of unmounting the whole tree. Row and body are deliberately two components: `onErrorCaptured` does not catch its own render. `MarkdownBody` renders during streaming too, so a finished reply does not reflow; only highlighting is deferred to completion.
- `pwa/src/components/ReviewSheet.vue`: 回看 bottom-sheet — 搜索 / 按天翻 / 收藏三 tab，一个自洽块，只读档案、只写本地收藏，绝不碰 transcript（入口在侧栏 Recents 上方的「搜索」）。搜索走字面子串，结果点开跳到「按天翻」并高亮定位到那句；气泡复用 `MarkdownBody`。因为它不写 `messages`，整体在组件里而不是主壳。
- `pwa/src/api/archive.ts`: 回看的读取层 — days/messages/search 三个 fetcher，全部打网关既有的 `/api/archive/*`（数据源是逐字档案 `shenyu_chat_archive`），不新建存储。
- `pwa/src/session/savedStore.ts`: 收藏只存本地，复用 `shenyu_pwa_*` localStorage 约定（key `shenyu_pwa_saved`）。存整条快照而非仅 id，因为档案那条随时可能软删或滑出窗口，收藏仍要能显示；收藏是圆圆私人的、惰性的，不注入上下文也不进沈予召回。
- `pwa/src/api/errors.ts`: turns a failed gateway response into one readable sentence at the HTTP boundary — an upstream proxy's HTML error page is reduced to its status code and never carried into a message. `clampErrorText` bounds whatever still reaches the transcript or localStorage, including errors stored before this module existed.
- `pwa/src/echo.ts`: leading echo marker parsing and model-facing tagged-content reconstruction for handoff and outbound history.
- `pwa/src/types.ts` / `pwa/src/utils.ts`: shared domain types (messages, variants, sessions, process timeline, presets) and id/Unicode-safe text-offset helpers.
- `pwa/src/api/useUpstream.ts`: the upstream-configuration block lifted out of the shell — models, reasoning effort, presets, custom request headers, runtime upstream info. It talks to the chat only through injected `status` / `errorNotice` / `busy`, so editing preset copy no longer means opening the file that owns streaming.
- `pwa/src/session/useComposer.ts`: composer and scroll feel — auto-grow, soft-keyboard lift (`translateY` only, per `docs/frontend/STYLE_AND_CRAFT.md` § 出生清单), and the scroll helpers. `jumpToBottom` positions instantly for first paint; `scrollToBottom` waits a tick for streaming updates; `atBottom` must be sampled *before* inserting content above, because a taller document with an unchanged `scrollTop` no longer reads as bottom. The delay ladder and the 8px margin were tuned on a real device; the extraction copied them verbatim.
- First paint renders only the newest `FIRST_PAINT_MESSAGES` (20) rows, then lifts the cap on the next frame. Measured 2026-08-30 on a 240-message transcript: 227ms → 21ms. The window carries each row's absolute index, since retry/edit/variant all address messages by it. `.message-stream` deliberately has no `scroll-behavior: smooth` — it turned a JS `scrollTop` jump into a visible slide from the top.
- `pwa/src/api/client.ts` / `pwa/src/api/presets.ts` / `pwa/src/api/upstreamHeaders.ts`: gateway HTTP layer — PWA identity headers, models/sessions/config/chat fetchers for streaming and non-streaming requests, outbound message wiring, deployed-build fetches — plus reading the Console-shared `shenyu_upstream_presets` storage and the browser-local per-request upstream-header preset/editor state. `wireContent` sends real bytes only for photos this device still holds; once one is evicted locally it sends an `EXPIRED_IMAGE_MARKER` block carrying just the fingerprint. Both of the gateway's image-block detectors accept that shape, so history normalization treats it as identical to the original image and branch detection cannot mistake local expiry for an edit — see `docs/architecture/REQUEST_CONTEXT.md` § Prompt Cache. Measured on a ten-photo conversation: 3.82MB → under 1MB per request.
- `pwa/src/buildInfo.ts`: validates the build identity embedded in the active client and the protected deployed `build-info.json` manifest; the settings sheet compares the two exact build ids.
- `pwa/src/demo/`: PWA 演示数据模式（`?demo=1`，与 admin `src/demo/` 同哲学）——`fixtures.ts` 编造一份逐字档案对话 + 首屏示例 transcript，`index.ts` 读 `?demo=1` flag 并在 `api/archive.ts` 的 days/messages/search fetch 前拦截返回样本；`App.vue` 在 demo 且本地无历史时铺种子对话。生产构建带此代码但不开 `?demo=1` 完全不生效。目的是让 PWA 视觉改动能不连真网关、不上线就在浏览器验收。
- `pwa/src/meta/statusSuffix.ts` / `pwa/src/meta/roomEntry.ts`: generates and parses the normal user-status suffix and the exact timestamped Room-entry contract used for hidden entry rows and `HH:mm · 房间` reply labels.
- `pwa/src/session/history.ts`: thread-handoff history source selection (context snapshots → legacy snapshot field → inspection-stream fallback), cold-start clean baseline rows, exact-duplicate detection, and recovery dedupe.
- `pwa/src/session/reconcile.ts`: tail-only reconciliation after a background disconnect — anchors the local last user turn against the session detail's raw `recent_messages` rows and adopts the server-drained reply only when it is strictly longer; never replaces the whole transcript.
- `pwa/src/session/toolHydration.ts`: rebuilds tool start/end events for snapshot-restored assistant rows from raw `tool` rows (tail-first, one group per assistant row, only when local events are empty).
- `pwa/src/session/variants.ts` / `pwa/src/session/persistence.ts`: local assistant roll-variant state machine and the localStorage transcript window save/restore. Attachment rows keep metadata only — id, name, mime, and byte fingerprint — because base64 images in localStorage are why attachments used to be dropped entirely. Persisting rebuilds each row, so unknown keys are carried over from the previous entry by id: an installed PWA runs the cached bundle for the first moments of a launch, and a stale bundle must be able to skip a field it does not know, never erase it (2026-08-30: it erased one).
- `pwa/src/session/photoStore.ts`: IndexedDB store for chat photo bytes, keeping the newest `STORED_PHOTO_LIMIT` (30) and reporting which ids it evicted. `photoDataUrl()` rebuilds a data URL for restoring a bubble — deliberately not `URL.createObjectURL`, whose `blob:` address is valid only inside that browser process and reached upstream as an unfetchable link once written into `attachment.dataUrl` (2026-08-30 production 500: `illegal base64 data at input byte 0`). Bytes are stored as `ArrayBuffer` rather than `Blob` (structured clone is uniform for it, and Blob-in-IndexedDB has a history of engine bugs) and re-wrapped as a Blob on read. `photoFingerprint` is SHA-256 over the bytes, the same algorithm as `shenyu_gateway/store/_album.py::photo_fingerprint`; both sides assert the same known digest so a change to either goes red. This bounds only what this device can still show — what reaches the upstream is still the gateway's newest-two-turns rule, and album photos are exempt from expiry entirely.
- `pwa/src/stream/sse.ts` / `pwa/src/stream/completion.ts` / `pwa/src/stream/timeline.ts`: streaming and non-streaming OpenAI-compatible response parsing (including `shenyu.tool_event`, `shenyu_echo`, and content-free `shenyu.response_meta` data), echo/thinking/tool offset bookkeeping and stream pump, and grouping process events into inline strips and detail timelines. `assistantParts` interleaves process strips with the reply again — each strip sits on a Markdown block boundary, and the body is emitted one block per part.
- `pwa/src/components/PhotoViewer.vue` / `pwa/src/viewer/gestures.ts`: full-screen photo viewer — pinch zoom, double-tap, horizontal paging, drag-to-dismiss. The gesture arithmetic (fit size, pan bounds, anchored zoom, swipe intent) is pure functions in `gestures.ts` because those edge cases are slowest to verify on a device. The viewer locks page zoom only while open, since its own double-tap and pinch would fight the browser's; the chat page keeps zoom because that is an accessibility feature.
- `pwa/src/components/PhotoStackCard.vue` / `pwa/src/viewer/photoStack.ts`: WeChat-style merged photo card — stacking, edge peeking, finger-scrubbed page turning, fling. Ported from PhotoStack by Wren036 (PolyForm Noncommercial 1.0.0; notice in the module header, lineage in `docs/frontend/STYLE_AND_CRAFT.md` § 风格血统声明). Every constant was measured frame-by-frame upstream — copy the numbers, do not retune by feel. `photoStack.ts` holds the layout math as pure functions; the component only wires events, and the port was checked against upstream's own code at a mid-flight frame.
- `pwa/src/stream/blocks.ts`: Markdown block spans from `marked.lexer`, and snapping a process offset onto a boundary. Splitting the body by character offset is what broke rendering in 2026-07 (a blank line inside a code fence is legal, so cutting there yields two fences and loses the language); the lexer's token boundaries are the only safe cut points. Offsets are converted to code points because `textOffset` counts code points while `raw.length` counts UTF-16 units — one emoji is enough to shift every boundary. Splitting per block also lets `MarkdownBody`'s cache seal finished blocks: measured 4.578ms → 0.715ms per streaming chunk.
- `pwa/tests/` + `pwa/vitest.config.ts`: Vitest unit suite (`cd pwa && npm test`) covering history source priority, dedupe recovery, roll variants, persistence window limits, SSE parsing, timeline grouping, per-request upstream-header persistence/payload mapping, gateway error-text extraction, the transcript row's render containment, the IndexedDB photo store's eviction, the full local photo lifecycle (capture → refresh → restore → expire → fingerprint upload), the local saved-store round-trip (回看收藏), and the demo fixtures' shape and literal-search behavior. The config loads `@vitejs/plugin-vue` because the row guard has to be tested against the real component, and `fake-indexeddb` because happy-dom has no IndexedDB.
- `pwa/src/ChatNestSprite.vue`: ChatNest status-sprite player using the demo's Web Animations API and per-mode frame loop configuration.
- `pwa/src/chatnestSprite.ts`: user-supplied private ChatNest status sprite set for the personal PWA deployment.
- `pwa/src/markdown.ts`: sanitized Markdown rendering with Highlight.js code highlighting, a bounded result cache keyed by source text, and an optional highlight-free mode for streaming frames. Language-less blocks fall back to `highlightAuto`, which costs about 33× a known language, so it is skipped above a size ceiling.
- `pwa/src/toolLanguage.ts`: gateway tool-name normalization and the resident-facing action copy — what 沈予 says he just did. Matching is by **exact tool name** with a prefix fallback, never `includes`: substring matching made `search_mem_notes` say he wrote a note (it contains `note`), made `delete_mem_note` say the same, and collapsed every room door into one line. Reading, writing, editing and deleting are four different actions, and so are hugging the octopus pillow and opening the locked drawer. `tests/toolLanguage.spec.ts` asserts no real tool falls through to the generic line.
- `pwa/src/styles.css`: responsive chat layout, bundled Anthropic Sans/Serif typography, ChatNest-matched composer geometry, animated status mark, bottom sheets, message actions, Markdown typography, tool trace states, and the line clamps that keep an error notice from pushing the transcript and composer off screen.
- `pwa/public/manifest.webmanifest` / `pwa/public/sw.js` / `pwa/src/main.ts`: installable PWA shell; the service worker never caches `/v1/`, `/api/`, or the deployment-proof `/chat/build-info.json` response, and each build registers its worker with its own build id. `main.ts` also installs the app-level `errorHandler`, the last stop for anything the per-row guard does not cover.
- `shenyu_gateway/middleware.py`: gives `/chat/sw.js`, `/chat/build-info.json`, and the admin shell pages (`/`, `/admin`, `/admin/`) explicit browser/CDN `no-store` headers so an outer cache cannot impersonate an old deployment or mix stale JS with fresh CSS.
- `pwa/vite.config.ts` / `pwa/scripts/`: isolated development server on port `5174`, build-time identity injection plus `build-info.json` emission, and a local build assertion that the active bundle contains that identity.
- `Dockerfile` + `gateway.py`: production PWA build and protected static `/chat/` mount served by the same gateway origin as `/admin/`; the `Dockerfile` declares `ARG SOURCE_COMMIT` for the PWA builder, but production deliberately supplies it only at runtime, so `build-info.json` identifies a build by timestamp rather than commit — see § Deploy to Coolify for why.
- Chat photos live on the device that sent them: bytes in IndexedDB (newest 30), metadata in localStorage, so a refresh keeps the transcript and the recent images while older bubbles show 图过期了. This is separate from the gateway's own newest-two-turns image trim and from the album, which never expires. A message accepts up to 9 photos.
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
| Memory Island | Stars + Mem 当前岛、小突起（今天已经记下的、工具回执） | `memory_island.py`、`island_bumps.py`、`context_builder.py`、`context_layers.py` | `admin/src/api/logs.ts`、`LogsView.vue`、`Mem0View.vue` | `REQUEST_CONTEXT.md`、`MEMORY_ROOM.md`、`DESIGN.md` § 小突起 |
| Stars | 星星 / 关联记忆 | `shenyu_gateway/stars/` | `admin/src/api/stars.ts`、`StarsView.vue`、`views/stars/` | `MEMORY_ROOM.md` § Star Memory Layer |
| Mem | Mem Notes / 便签 | `shenyu_gateway/mem_notes/`、`mem_notes_relevance.py` | `admin/src/api/mem0.ts`、`Mem0View.vue` | `MEMORY_ROOM.md` § Mem Note Layer |
| 记忆网络 | 人物 / 地点 / 物件 / 主题锚点 | `memory_graph.py`、`shenyu_gateway/recall/` | `admin/src/api/memoryGraph.ts`、`MemoryGraphView.vue`、`Mem0View.vue` | `MEMORY_ROOM.md` § Personal Memory Graph |
| Room | 房间 / 窗台 | `private_capture.py`、`room_context.py`、`room_tools.py`、`room_newspaper.py` | `pwa/src/App.vue`、`pwa/src/meta/roomEntry.ts`、`admin/src/api/room.ts`、`RoomView.vue`、`views/room/` | `MEMORY_ROOM.md` § Room Mode |
| 相册 | 沈予的相册、收藏的图 | `shenyu_gateway/store/_album.py`、`gateway_tools/_album.py` | `GET /api/gateway/album`、`GET /api/gateway/album/photo/{id}` | 本文件 § Album |
| 盼圃 | 果子、青果子、摘果子、那面等的墙、园子里的天气 | `shenyu_gateway/orchard.py`、`orchard_service.py`、`gateway_tools/_orchard.py` | `GET /api/gateway/orchard`、`POST /api/gateway/orchard/fruits` | 本文件 § 盼圃 (Orchard) |
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

The PWA model sheet also has two empty, mutually exclusive upstream-auth slots: `x-api-key` and `Authorization`. A non-empty slot is sent to both `GET /v1/models` and chat as the upstream authentication override; with both empty, the configured upstream key and protocol default remain unchanged. This auth pair is separate from the Claude Code identity headers, so one auth method can be used alongside that preset without replacing it. The gateway never treats these values as its own client login key and never stores them in persistent request logs.

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

`/admin` is organized by feature: every `admin/src/api/*.ts` and `admin/src/views/*` boundary is listed once in § Maintenance Map above. Do not restate those files here — a second list drifts silently, because `tests/test_project_map.py` only guards the § Maintenance Map section.

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
6. Coolify auto-deploys the tracked branch, which is `master`. **A `master` push is a production deployment**, not merely a repository update: the resident gateway, its Supabase project, and the mounted data volume are the live ones. Feature branches are not deployed. `docs/DELIVERY.md` § 交付状态梯 is the authority for what must pass before pushing `master` and why a push receipt is not yet a deployment.

`SOURCE_COMMIT` reaches the deployment two different ways, and they are not interchangeable. As a **runtime** environment variable it feeds `shenyu_gateway/resident_home.py::current_commit`, whose fallback chain ends at `os.getenv("SOURCE_COMMIT")` — Coolify already injects it there, so the resident-home snapshot shows the deployed revision with no extra configuration. As a **Docker build argument** it would additionally be baked into the PWA bundle, because `vite.config.ts` reads it while `npm run build` runs; a runtime value arrives too late for that.

Only `/chat/build-info.json`'s `revision` field depends on the build-arg form, and it is currently `"unknown"` in production **by choice**. Enabling it in Coolify (the app-level `include_source_commit_in_build` switch, not a missing field) makes Coolify insert an `ARG` line after every `FROM`, which invalidates the layer cache for both the admin and PWA `npm ci` steps on every deploy — Coolify's own hint reads "Disable to preserve cache across different commits". Measured 2026-08-30: a deploy takes about 40 seconds with those caches warm.

The trade was declined because `buildId` already carries a build timestamp, which is what the settings sheet actually compares to tell a device whether it is running the current bundle. A commit SHA would only make that label easier to read against git history; it adds no capability. Revisit only if a question comes up that the timestamp genuinely cannot answer.

An installed PWA does not switch versions the moment you deploy. The Service Worker paints the cached shell first, then fetches the new one, activates it, and only then does `main.ts` force a reload. So a device can run the previous bundle for the first moments of a launch — long enough for it to persist state. That is why `pwa/src/session/persistence.ts` carries unknown fields through a round-trip instead of rebuilding rows from scratch: a stale bundle must be able to skip a field, never erase it.

Local sessions, context snapshots, pending tool turns, persisted request-log summaries, Admin configuration overrides, and album image bytes all live in SQLite, so they survive container replacement only on a mounted volume — the Dockerfile declares none. The live deployment mounts the named volume `shenyu-gateway-data` at `/data` with `GATEWAY_DB_PATH=/data/shenyu_gateway.db`; `docs/architecture/REQUEST_CONTEXT.md` § SQLite Retention And Cleanup records what was observed and how to re-verify it. Supabase archives are independent of this local volume. `GATEWAY_REQUEST_LOG_RETENTION` controls the bounded history size and defaults to `200`; full debug payloads are never written to this history.

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
4. `SOURCE_COMMIT` needs no setup: Coolify injects it as a runtime variable, which is where the resident-home snapshot reads it. The build-arg form is deliberately left off — see the note below on why the layer-cache cost was not worth a more readable build label.
5. Open `/admin/` once to log in, then open `/chat/` on the same domain. In PWA「聊天设置」confirm that the current running build and deployed build match before accepting a user-visible PWA fix; then reproduce the original scenario on the affected device. If that observation is unavailable, report the change as unverified. The PWA's preset selector reads the same-origin Admin preset store.

### Future improvements (when needed)

- Keep the Dockerfile's Admin/PWA build stages aligned with their `package-lock.json` files.
