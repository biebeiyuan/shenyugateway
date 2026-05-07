# Shenyu Gateway

Shenyu Gateway is the single OpenAI-compatible provider entrypoint for Operit. It prepares context, exposes tools, routes tool calls, and adapts requests to Anthropic or OpenAI-compatible upstreams.

The gateway is not a persona layer or roleplay wrapper. It is a context and memory gateway: current conversation text stays primary, long-form primary text can surface softly, and durable memory is handled by explicit layers.

## Current Architecture

```text
Operit
  -> Shenyu Gateway
       -> ContextBuilder
       -> GatewayStore (SQLite runtime state)
       -> GatewayToolService (Supabase tools, surface, memory)
       -> CalendarService (day/week/month pages)
       -> AtomicMemoryService (small durable facts)
       -> Upstream adapter (Anthropic / OpenAI-compatible)
  -> Upstream model
  -> gateway tool loop when needed
```

## Context Layers

Context is assembled from low-change to high-change content:

| Layer | Placement | Contents | Cache policy |
|---|---|---|---|
| `tools` | request tools | client tools + `shenyu_*` / `supabase_*` tools | breakpoint at `tools[-1]` |
| `stable` | first system message | stable charter, active meta summaries, gateway tool policy, heartbeat instructions | breakpoint |
| `summary` | second system message when present | latest injected heartbeat digest | breakpoint |
| `cold_start` | third system message when present | cross-window bridge snapshot for a new or stale window | breakpoint |
| client history | original messages | trimmed client messages when `MAX_CLIENT_MESSAGES` is set | fallback breakpoint only if one is free |
| `volatile` | inserted before latest user message | first-turn briefing, surfaced primary text, active atomic memories | no breakpoint |
| current user | latest user message | current request | no breakpoint |

The retired rolling and frozen context layers have been removed from the active flow. Their legacy SQLite tables are only cleaned up during session deletion when they exist in an older database.

## Prompt Cache

The gateway adds Anthropic-compatible `cache_control` markers on stable prefixes. With a full set of layers, the intended breakpoints are:

```text
tools[-1]
messages[0].stable
messages[1].summary
messages[2].cold_start
```

If `summary` or `cold_start` is empty, the gateway may use the remaining breakpoint on the previous stable conversation message. Volatile retrieval results are deliberately left uncached so random or query-dependent content does not poison the prefix cache.

Real cache hits still depend on the upstream or OpenAI-compatible relay honoring Anthropic `cache_control`. Check:

```text
usage.prompt_tokens_details.cached_tokens > 0
```

or the normalized gateway log field:

```text
cache_usage.cache_read_input_tokens > 0
```

## SQLite Runtime State

SQLite stores only gateway runtime state:

- `gateway_sessions`
- `gateway_messages`
- `request_context_snapshots`
- `cold_start_snapshots`
- `surface_events`
- `cache_entries`
- `heartbeat_entries`

`request_context_snapshots` is the replacement for the old rolling/frozen context path. Each request stores the prepared client window before gateway layers are inserted. Calendar generation and cold-start bridge both read these snapshots.

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
- `atomic_memories`
- `atomic_extraction_runs`

The short-lived notes table is no longer used by gateway code.

## Cold Start Layer

Cold start bridges context across windows without reintroducing the retired frozen context layer.

Flow:

1. `_prepare_messages()` opens the session and stores a `request_context_snapshot`.
2. `_maybe_prepare_cold_start_snapshot()` checks whether the request is a new window or a stale window.
3. It reads recent request snapshots from other sessions via `recent_cross_session_context()`.
4. It writes a `cold_start_snapshot` with a bounded message budget.
5. `ContextBuilder.render_layered_additions()` renders it as the `cold_start` system layer.
6. The snapshot is marked injected until `COLD_START_TURNS` is exhausted.

Config:

- `ENABLE_COLD_START`
- `COLD_START_TURNS`
- `COLD_START_MESSAGE_LIMIT`
- `COLD_START_IDLE_MINUTES`
- `MAX_CLIENT_MESSAGES`

Debug endpoints:

- `GET /api/gateway/overview`
- `GET /api/gateway/cold-start/preview`
- `GET /api/gateway/sessions/{session_tag}`

## Calendar Layer

The calendar layer writes private day/week/month memory pages. It is manually triggered from the admin/debug UI.

Tables:

- `calendar_prompt_configs`: active prompt versions for day/week/month.
- `calendar_pages`: versioned generated pages.
- `calendar_generation_runs`: generation logs and source refs.

Source collection:

- Day pages read recent `request_context_snapshots`, recent day/week/month pages, and a small surface pass.
- Week pages read recent context snapshots plus recent day/week/month pages.
- Month pages read recent day/week/month pages.

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

## Atomic Memory Layer

Atomic memories are small durable notes, separate from event memories and calendar pages.

Two independent switches control it:

- `EXTRACT_ATOMIC_MEMORIES`: after a reply, schedule a background extraction run.
- `INJECT_ATOMIC_MEMORIES`: before a reply, search active atomic memories and inject relevant hits in `volatile`.

Extraction flow:

1. Assistant reply is logged.
2. `_schedule_atomic_memory_extraction()` starts `AtomicMemoryService.process_turn()`.
3. The extractor model returns JSON candidates.
4. Candidates are written to `atomic_memories`.
5. High-confidence candidates become `active`; others stay `proposed`.
6. Runs are logged in `atomic_extraction_runs`.

Search/injection flow:

1. `ContextBuilder` calls `search_atomic_memories()` when enabled.
2. Active rows are scored by keyword overlap, tags/entities, importance, heat, tier, emotion signal, and recency.
3. Relevant hits are rendered in `volatile`.

Endpoints:

- `GET /api/gateway/atomic-memories/search`
- `GET /api/gateway/atomic-memories`
- `POST /api/gateway/atomic-memories/{memory_id}/review`

## Briefing And Surface

`build_briefing()` still exists as a first-turn briefing, but it is volatile and not part of the stable cache prefix. It includes:

- latest memo
- message board
- sampled journal entries
- recent medication records
- tool usage guide

Surface pass reads primary text candidates from:

- `journal`
- `room`
- `message_board`

Surface results are randomized by score and inserted in `volatile`, so they do not affect stable cache breakpoints.

## Configuration

Important environment variables:

```text
UPSTREAM_URL=
ANTHROPIC_API_KEY=
UPSTREAM_PROTOCOL=auto

CALENDAR_UPSTREAM_URL=
CALENDAR_API_KEY=
CALENDAR_PROTOCOL=auto
CALENDAR_MODEL=claude-opus-4-7

ENABLE_COLD_START=true
COLD_START_TURNS=3
COLD_START_MESSAGE_LIMIT=8
COLD_START_IDLE_MINUTES=120
MAX_CLIENT_MESSAGES=

INJECT_ATOMIC_MEMORIES=false
EXTRACT_ATOMIC_MEMORIES=false
ATOMIC_MEMORY_UPSTREAM_URL=
ATOMIC_MEMORY_API_KEY=
ATOMIC_MEMORY_PROTOCOL=auto
ATOMIC_MEMORY_MODEL=
DEFAULT_ATOMIC_MEMORY_LIMIT=3
ATOMIC_MEMORY_MIN_SCORE=0.42
ATOMIC_MEMORY_AUTO_ACTIVATE_MIN_CONFIDENCE=0.92

INJECT_BRIEFING=true
INJECT_SURFACE_PASSAGES=true
DEFAULT_SURFACE_LIMIT=3
DAILY_BRIEFING_TTL_MINUTES=60

ENABLE_GATEWAY_TOOLS=false
EXPOSE_SUPABASE_TOOLS=true
MAX_INTERNAL_TOOL_ROUNDS=3
```

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
http://localhost:8010/debug
```

`/` redirects to `/admin`, so the admin login is the single main browser entrypoint. The same gateway key protects `/admin`, `/debug`, and `/api/*`.

`/admin` is the formal Vue/Vite admin app. It is organized by feature:

- `admin/src/api/config.ts`: gateway and upstream configuration.
- `admin/src/api/sessions.ts`: local SQLite session browser.
- `admin/src/api/calendar.ts`: calendar prompts, month grid, previews, and generation.
- `admin/src/views/ConfigView.vue`: configuration page.
- `admin/src/views/SessionsView.vue`: session inspection page.
- `admin/src/views/CalendarView.vue`: day/week/month calendar memory workflow.
- `admin/src/components/AppShell.vue`: shared admin navigation and layout.

`/debug` is kept as the low-level single-file diagnostic console in `debug.html`. New user-facing admin features should go into `admin/src/views/*` and `admin/src/api/*`, not into `debug.html`.

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
- `GET /api/gateway/context/preview` should show `stable`, optional `summary`, optional `cold_start`, and `volatile`.
- `GET /api/calendar/send-preview?...` should show `Current Client Context Snapshots`, not rolling/frozen blocks.
- `GET /api/gateway/logs` should show prompt cache breakpoints and cold-start metadata.
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
