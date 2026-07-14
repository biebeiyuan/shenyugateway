# Shenyu Gateway

Shenyu Gateway is the single OpenAI-compatible provider entrypoint for Operit. It prepares context, exposes tools, routes tool calls, and adapts requests to Anthropic or OpenAI-compatible upstreams.

The gateway is not a persona layer or roleplay wrapper. It is a context and memory gateway: current conversation text stays primary, long-form primary text can surface softly, and durable memory is handled by explicit layers.

## 新线程阅读顺序

如果只想读一个入口，先读 **`START_HERE.md`**。它用人话解释常见术语，并按任务指向对应现行文档。

| 顺序 | 文档 | 用途 |
|------|------|------|
| 1 | **`AGENTS.md`** | 当前环境、协作方式、编码与排障规则 |
| 2 | **`DOCS_MAP.md`** | 文档职责和状态；避免把历史方案当成当前事实 |
| 3 | **`docs/architecture/SYSTEM_ZONES.md`** | 八个系统区、跨区桥梁和审计入口 |
| 4 | 本文件 `README.md` § Maintenance Map | 文件地图、API 清单、配置参考 |
| 改内核前 | `DESIGN.md` | 记忆系统设计哲学、核心逻辑和改动边界 |
| 按需 | `DEBUGGING_GUIDE.md` | 排错时的日志命令和验证清单 |
| 忘记日志页怎么看时 | `LOGS_GUIDE.md` | 粉色/绿色轮次、小岛、缓存原始值和来源指纹速查 |

专题设计稿、实施计划和审查快照不要求新线程全部阅读。先在 `DOCS_MAP.md` 确认它们的用途和时效，再结合当前代码判断。

## Current Architecture

```text
Operit
  -> Shenyu Gateway
       -> ContextBuilder
       -> GatewayStore (SQLite runtime state)
       -> GatewayToolService (Supabase tools, surface, memory)
       -> CalendarService (day/week/month pages)
       -> MemNoteService (small personal notes)
       -> StarService (small chord/association memories)
       -> Upstream adapter (Anthropic / OpenAI-compatible)
  -> Upstream model
  -> gateway tool loop when needed
```

## Maintenance Map

The codebase is partly layered already:

### Core entrypoint

- `gateway.py`: FastAPI app entrypoint, lifespan, CORS, route registration, and model listing. Chat, calendar, admin, hisense, archive, and config routes have been extracted into dedicated modules.

### Config & runtime

- `shenyu_gateway/config.py`: environment-backed runtime config.
- `shenyu_gateway/runtime.py`: shared runtime utilities (logger, `now_ts`, `iso_now`, `json_dumps`, dotenv loading).
- `shenyu_gateway/schemas.py`: Pydantic data models (`ChatMessage`, request/response shapes).

### Storage

- `shenyu_gateway/store/`: SQLite runtime state (package split into mixins: `_base`, `_sessions`, `_messages`, `_pending`, `_snapshots`, `_cold_start`, `_heartbeats`, `_cache`, `_room`, `_admin`).
- `shenyu_gateway/supabase.py`: low-level Supabase REST client.

### Chat pipeline & streaming

- `shenyu_gateway/chat_pipeline.py`: main chat request orchestration (context build → upstream call → tool loop → response).
- `shenyu_gateway/streaming.py`: SSE streaming helpers, chunk serialization, keepalive logic.
- `shenyu_gateway/stream_proxy.py`: plain pass-through streaming with `<heartbeat>` filtering.
- `shenyu_gateway/tool_loop.py`: internal gateway tool loop (`_run_internal_tool_loop_stream`).
- `shenyu_gateway/middleware.py`: FastAPI middleware registration (global exception handler, request-id injection, HTTP event logging).

### Context assembly

- `shenyu_gateway/context_builder.py`: async parallel gathering of all memory sources into a context package.
- `shenyu_gateway/context_layers.py`: stable/slow/mem/heartbeat/tool-policy/format layer rendering, client message trimming, and cold-start bridge insertion.
- `shenyu_gateway/context_snapshots.py`: context snapshot creation and helpers for calendar/cold-start sources.
- `shenyu_gateway/prepare_messages.py`: cold-start snapshot preparation, runtime state pruning, pending gateway tool turn injection, and message/tool-call helpers.

### Upstream communication

- `shenyu_gateway/upstream_adapter.py`: pure OpenAI/Anthropic message, cache, stream, and model URL conversion helpers.
- `shenyu_gateway/upstream_client.py`: upstream HTTP client construction, protocol detection, URL routing, request building, streaming chunk iteration, model listing, and connection error formatting.

### Tools

- `shenyu_gateway/gateway_tools.py`: gateway-native tool implementations (`GatewayToolService`), including Supabase table tools, recall compatibility helpers, heartbeats, notebook, and memory helpers.
- `shenyu_gateway/tool_registry.py`: gateway-native tool schemas, enablement/merge logic, and tool-name dispatch into `GatewayToolService`.
- `shenyu_gateway/tool_schemas.py`: tool JSON schema definitions (separated from registry logic).

### Memory subsystems

- `shenyu_gateway/stars/`: Star memory service (package split into mixins: `_helpers`, `_chord`, `_scene`, `_weights`, `_crud`, `_recall`, `_activity`, `_review`, `_feedback`, `_logging`, `_render`, `_embedding`). ACT-R activation, chord/content/harmony scoring, review candidates, feedback logging, and constellation links.
- `shenyu_gateway/mem_notes/`: note service package (mixin pattern, like stars/): `_helpers` (constants), `_validation` (field validation), `_suggestions` (auto mem_type/keyword inference), `_search` (keyword/semantic/entity matching, scoring, cooldown, rendering), `_crud` (create/update/delete/list/legacy-atomic). `__init__.py` assembles `MemNoteService` and re-exports backward-compat symbols.
- `shenyu_gateway/mem_notes_relevance.py`: pure-function helpers for mem-note recall scoring, anchor matching, auto-extraction (people/places/objects/keywords/summary/memory_kind inference), `compute_heat()`, and `running_joke_serendipity_rate()`.
- `shenyu_gateway/recall.py`: unified recall index — keyword + vector hybrid search across 7 data sources.
- `shenyu_gateway/embeddings.py`: embedding client (SiliconFlow / BAAI/bge-m3).

### Capture & private content

- `shenyu_gateway/response_capture.py`: private assistant tag filtering for `<heartbeat>`, heartbeat persistence helper.
- `shenyu_gateway/private_capture.py`: private assistant content finalization (`<heartbeat>` extraction), context-consumed marking, fallback text generation, and free-time detection.

### Durable archive

- `shenyu_gateway/chat_archive.py`: L0 verbatim chat archive service (fire-and-forget archival to Supabase `shenyu_chat_archive`).
- `shenyu_gateway/heartbeat_archive.py`: heartbeat disaster recovery archive to Supabase (`shenyu_heartbeat_archive`), settle window, soft-delete reconciliation.
- `shenyu_gateway/conflict_books.py`: conflict books CRUD, invariant enforcement (frozen original_text, append-only annotations).

### Calendar

- `shenyu_gateway/calendar.py`: date/key helpers and calendar JSON parsing.
- `shenyu_gateway/calendar_service.py`: `CalendarService` — calendar page generation orchestration.
- `shenyu_gateway/calendar_sources.py`: day/week/month source collection for calendar generation.

### Room mode

- `shenyu_gateway/room_text.py`: all room mode copy — charter, atmosphere scenes, door descriptions, trace phrases. Change text here only.
- `shenyu_gateway/room_context.py`: room mode charge calculation, layer rendering, door filtering logic.
- `shenyu_gateway/room_tools.py`: room mode tool definitions, compatibility broker, execute dispatch, and door count collection.
- `shenyu_gateway/room_scenes.py`: window scenes (weather, atmosphere, landscape). Change scene copy here only.
- `shenyu_gateway/room_newspaper.py`: fixed RSS sources, feed parsing, issue rolling, optional quality checks, and draft generation.

### Auth & sessions

- `shenyu_gateway/auth.py`: admin auth middleware, API key verification, login page HTML, and `ADMIN_PROTECTED_PREFIXES`.
- `shenyu_gateway/sessions.py`: session/message logging facade.

### Route modules (extracted from gateway.py)

- `shenyu_gateway/gateway_admin_routes.py`: admin API routes (stars, mem notes, room, overview, prune, etc.).
- `shenyu_gateway/calendar_routes.py`: calendar API routes (prompts, month grid, generation, preview).
- `shenyu_gateway/hisense_routes.py`: Hisense API routes (preview, notebook, session).
- `shenyu_gateway/archive_routes.py`: archive reader and conflict book API routes.
- `shenyu_gateway/config_routes.py`: configuration API routes (get/set runtime config).
- `shenyu_gateway/admin_shell_routes.py`: admin shell/UI routes (static file serving, login page).

### Request logging

- `shenyu_gateway/request_logs.py`: live request log ring buffer, phase markers, HTTP event tracking, and the safe serializer used for persistent summaries.
- `shenyu_gateway/store/_request_log_history.py`: bounded SQLite request-log history used by Admin/API/helper after process or container replacement.

### Shared utilities

- `shenyu_gateway/utils.py`: shared utilities (`shorten`, `clean_config_text`, `normalize_text`) used across multiple modules.

### Admin frontend

- `admin/src/api/http.ts`: shared HTTP client (axios instance, auth token).
- `admin/src/api/config.ts`: gateway and upstream configuration.
- `admin/src/api/mem0.ts`: Mem config, mem-note review APIs, and old atomic read-only lookup.
- `admin/src/api/stars.ts`: Star list/search/create/review/feedback/connect APIs.
- `admin/src/api/sessions.ts`: local SQLite session browser.
- `admin/src/api/logs.ts`: request log list and detail APIs.
- `admin/src/api/calendar.ts`: calendar prompts, month grid, previews, and generation.
- `admin/src/api/hisense.ts`: Hisense preview, notebook CRUD, and session APIs.
- `admin/src/api/archive.ts`: chat archive reader and conflict book APIs.
- `admin/src/api/room.ts`: room mode APIs (traces, drawer notes, scribbles, pins, newspapers).
- `admin/src/api/toolErrors.ts`: tool error log APIs.
- `admin/src/views/HomeView.vue`: admin landing/dashboard page.
- `admin/src/views/ConfigView.vue`: configuration page.
- `admin/src/views/Mem0View.vue`: Mem prompt/capture/injection/tool controls, mem-note attribute workflow, and old atomic read-only lookup.
- `admin/src/views/StarsView.vue`: standalone Star entry shell at `/stars`, with split Star panels under `admin/src/views/stars/`.
- `admin/src/views/stars/StarsReviewPanel.vue`: admin review scoring, missed recording, and candidate constellation feedback.
- `admin/src/views/stars/StarsSettingsPanel.vue`: Star memory configuration controls.
- `admin/src/views/stars/StarsWritePanel.vue`: manual star creation and search.
- `admin/src/views/stars/StarsListPanel.vue`: star list/filter panel.
- `admin/src/views/stars/StarMapView.vue`: Three.js star graph view (memory star map at `/stars/map`).
- `admin/src/views/stars/starMelody.ts`: constellation → Web Audio melody.
- `admin/src/views/stars/starUi.ts`: shared Star UI formatting and link-order helpers.
- `admin/src/views/SessionsView.vue`: session inspection page.
- `admin/src/views/LogsView.vue`: request log viewer with expandable detail tabs and per-round normalized input/cache badges.
- `admin/src/views/CalendarView.vue`: day/week/month calendar memory workflow.
- `admin/src/views/HisenseView.vue`: Hisense slow-layer preview, notebook management, and session history.
- `admin/src/views/ArchiveView.vue`: chat archive reader and conflict book clip flow.
- `admin/src/views/ConflictView.vue`: conflict book management (edit title/notes/epilogue/status, soft delete).
- `admin/src/views/RoomView.vue`: room mode admin preview shell (charge, traces, drawer notes, pins, and newspaper placement).
- `admin/src/views/room/RoomNewspaperPanel.vue`: in-place Room newspaper panel (generate, review, publish, discard, and source status).
- `admin/src/views/ToolErrorsView.vue`: tool error log viewer.
- `admin/src/components/AppShell.vue`: shared admin navigation and layout.
- `admin/e2e/smoke.spec.ts`: read-only Chromium smoke checks for every Admin route and a few core interactions.
- `admin/playwright.config.ts`: isolated local gateway, temporary SQLite, authentication, and browser settings for Admin smoke tests.

When cleaning or refactoring, preserve behavior first and move code by boundary:

1. Route handlers should stay thin and call service classes.
2. SQLite reads/writes belong in `GatewayStore`; do not query SQLite directly from route handlers.
3. Supabase HTTP mechanics belong in `SupabaseClient`; table-specific behavior can live in service classes.
4. Context data fetching belongs around `ContextBuilder`; layer rendering and message-window assembly belong in `shenyu_gateway/context_layers.py`.
5. Private response tag filtering and capture helpers belong in `shenyu_gateway/response_capture.py` and `shenyu_gateway/private_capture.py`. When adding a new private block type, update both parser paths and the empty-reply fallback wording.
6. Gateway-native tool behavior belongs in `shenyu_gateway/gateway_tools.py`; tool schemas, merge logic, and name dispatch belong in `shenyu_gateway/tool_registry.py`. Keep tool descriptions short: one-line purpose plus backing table/pool.
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
HISENSE_UPSTREAM_URL=
HISENSE_API_KEY=
HISENSE_PROTOCOL=

CALENDAR_UPSTREAM_URL=
CALENDAR_API_KEY=
CALENDAR_PROTOCOL=auto
CALENDAR_MODEL=claude-opus-4-7

ENABLE_COLD_START=true
COLD_START_MESSAGE_LIMIT=
MAX_CLIENT_MESSAGES=75

INJECT_MEM_NOTES=true

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
- `admin/src/api/stars.ts`: Star list/search/create/review/feedback/connect APIs.
- `admin/src/api/sessions.ts`: local SQLite session browser.
- `admin/src/api/logs.ts`: request log list and detail APIs.
- `admin/src/api/calendar.ts`: calendar prompts, month grid, previews, and generation.
- `admin/src/api/hisense.ts`: Hisense preview, notebook CRUD, and session APIs.
- `admin/src/views/ConfigView.vue`: configuration page.
- `admin/src/views/Mem0View.vue`: Mem prompt/capture/injection/tool controls, mem-note attribute workflow, and old atomic read-only lookup. The "静音但保留工具" preset turns off mem prompt/capture/injection while leaving gateway tools available.
- `admin/src/views/StarsView.vue`: standalone Star entry shell at `/stars`, with split Star panels under `admin/src/views/stars/` and a lazy-loaded memory star map at `/stars/map`.
- `admin/src/views/SessionsView.vue`: session inspection page.
- `admin/src/views/LogsView.vue`: request log viewer with expandable detail tabs and per-round normalized input/cache badges.
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
- `GET /api/gateway/context/preview` should show `stable`, optional `slow`, optional `mem`, `heartbeat`, `tool_policy`, and `format`.
- When `INJECT_STARS=true`, relevant stars that clear `STAR_RELATED_MIN_SCORE` and `STAR_MIN_SCORE` should appear in the `mem` layer before mem notes; `STAR_INJECT_LIMIT` is an upper bound, not a promise to always inject that many.
- `GET /api/calendar/send-preview?...` should show `Current Client Context Snapshots`, not rolling/frozen blocks.
- `GET /api/gateway/logs` should show prompt cache breakpoints and cold-start metadata.
- `GET /api/gateway/logs/{id}` should show `response_full` for retained payloads; the list view should keep using short previews.
- After star-memory edits, run `pytest -q test_star_memory.py test_gateway_tool_registry.py test_response_capture.py test_gateway_tags.py`.
- Run `python -c "import test_gateway_streaming as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]"` after streaming/tool-loop edits when `pytest` is unavailable.
- Run `python -c "import test_upstream_adapter_stream as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]"` after upstream stream adapter edits when `pytest` is unavailable.
- Run `cd admin && npm run build` after admin UI edits.
- Run `cd admin && npm run test:e2e` after Admin routes, page loading, or core interactions change. Install Chromium once with `npm run test:e2e:install`; the suite checks that pages are alive and interactive, not that they are visually identical.
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

If local sessions, context snapshots, pending tool turns, persisted request-log summaries, or Admin configuration overrides must survive container replacement, mount a persistent volume at `/app/data` (or the parent directory configured by `GATEWAY_DB_PATH`). The Dockerfile does not declare a volume, so the default `/app/data/shenyu_gateway.db` otherwise belongs to the disposable container filesystem. Supabase archives are independent of this local volume. `GATEWAY_REQUEST_LOG_RETENTION` controls the bounded history size and defaults to `200`; full debug payloads are never written to this history.

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
