# Shenyu Gateway Debugging Guide

This guide is the quick entrypoint for future debugging windows. Read it together with `README.md` before changing gateway logic.

## Error Log Quickstart

For live triage, start with the helper script before changing code:

```powershell
python scripts\vps_gateway_logs.py api --via-ssh --errors --detail
```

Set these in the shell when checking the deployed gateway:

```powershell
$env:SHENYU_GATEWAY_URL="https://gateway.example.com"
$env:SHENYU_GATEWAY_TOKEN="gateway-api-token"
```

The helper also auto-loads a local ignored config file at `.shenyu-gateway-debug.local.json`, a home config at `~/.shenyu-gateway-debug.json`, or the path in `SHENYU_GATEWAY_LOG_CONFIG`.

Example local config:

```json
{
  "gateway_url": "https://gateway.example.com",
  "gateway_token": "gateway-api-token",
  "vps_host": "example.com",
  "vps_user": "root",
  "vps_port": 22,
  "vps_identity": "C:/Users/曾/.ssh/cyberboss_vps_ed25519",
  "container_match": "shenyu|gateway"
}
```

Useful variants:

```powershell
# Watch new gateway request errors
python scripts\vps_gateway_logs.py api --via-ssh --watch --errors --interval 5

# Inspect one request by log id or request id
python scripts\vps_gateway_logs.py api --via-ssh --id 84f8b85a

# Parse a retained local JSON log
python scripts\vps_gateway_logs.py local tmp_gateway_log_84f8b85a.json --detail

# Tail VPS/Coolify/Docker logs when SSH is configured
$env:SHENYU_VPS_HOST="root@example.com"
python scripts\vps_gateway_logs.py ssh --list-containers
python scripts\vps_gateway_logs.py ssh --match "shenyu|gateway" --tail 300 -f
```

Use `api` without `--via-ssh` only when public gateway API access is not blocked by Cloudflare.

The script separates `tools_offered` from `gateway_tools_executed`. If tools were offered but zero gateway tools executed, the model/upstream failed before the gateway got any tool call. In that case, inspect upstream errors, relay retries, streaming behavior, request payload shape, and prompt-cache compatibility before editing `gateway_tools.py`.

Do not put gateway tokens, VPS hosts, SSH keys, or API keys into repo files. Use shell environment variables or ask the user for the missing value.

## First Rule

Preserve behavior before cleanup. This gateway has browser-facing contracts outside this repo, and code can look unused from the admin UI while still being used by `home-frontend`.

Do not commit one-off test files. Prefer `python -c`, temp directories, or existing `test_*.py` files. If a temporary test script is created in the repo, delete it before committing unless it is intentionally promoted into a permanent regression test and documented.

## Module Map

- `gateway.py`: FastAPI app, middleware, routes, service orchestration, upstream HTTP calls, tool loop, response filtering, and public API contracts.
- `shenyu_gateway/config.py`: environment-backed runtime config.
- `shenyu_gateway/store/`: SQLite runtime state (mixin package). Routes and services should call `GatewayStore` instead of writing SQL directly.
- `shenyu_gateway/supabase.py`: low-level Supabase REST mechanics.
- `shenyu_gateway/sessions.py`: session and message logging facade.
- `shenyu_gateway/calendar.py`: calendar date/key helpers and JSON parsing.
- `shenyu_gateway/calendar_sources.py`: day/week/month source collection for calendar generation.
- `shenyu_gateway/context_layers.py`: stable/slow/mem/heartbeat/tool-policy/format layer rendering, client message trimming, tool-safe trimming, and cold-start bridge insertion.
- `shenyu_gateway/gateway_tools.py`: gateway-native tool implementations. Look here for Supabase table tools, recall compatibility helpers, heartbeat reads, notebook helpers, and memory helper behavior.
- `shenyu_gateway/tool_registry.py`: gateway-native tool schemas, enablement/merge logic, and tool-name dispatch into `GatewayToolService`.
- `shenyu_gateway/response_capture.py`: private assistant tag filtering for `<heartbeat>`, heartbeat persistence helper.
- `shenyu_gateway/mem_notes.py`: note CRUD with memory_kind alias resolution, auto-enrichment (only `content` required), heat exposure, and old atomic read-only lookup.
- `shenyu_gateway/mem_notes_relevance.py`: pure helpers for recall scoring, anchor matching, auto-extraction (people/places/objects/keywords/summary/memory_kind), `compute_heat()`, and `running_joke_serendipity_rate()`.
- `shenyu_gateway/upstream_adapter.py`: pure OpenAI/Anthropic payload, cache, stream, and model URL conversion helpers.

## Chat Request Flow

Main chat flow is centered in `gateway.py`:

1. Auth middleware allows `OPTIONS` and accepts both `Authorization` and `?token=...`.
2. Chat route calls `_prepare_messages()`.
3. `_prepare_messages()` opens the gateway session, stores a raw request window, trims client messages, writes a request context snapshot, builds a context package, renders context layers, and inserts them into the message list.
4. `ContextBuilder.build_context_package()` fetches runtime data: heartbeat digest, calendar context, Hisense notebook/recap, and active mem notes.
5. `shenyu_gateway.context_layers` renders the package into:
   - `stable`: charter and optional wake welcome message.
   - `slow`: calendar memory, Hisense notebook, wake recap.
   - `mem`: active mem notes headed by `## 我之前写下的便签，可能用的到。`, after `slow` and before heartbeat.
   - `heartbeat`: independent `## 我之前的心跳` block after `mem`.
   - `tool_policy`: compact `## 工具怎么用` reminder after heartbeat.
   - `format`: heartbeat and inline mem format reminders after tool policy.
6. `_build_upstream_request()` prepares the upstream payload.
7. `shenyu_gateway.upstream_adapter` converts OpenAI-compatible messages/tools to Anthropic when needed, adds cache markers, and converts responses/chunks back.
8. Tool loop may call gateway tools, then `shenyu_gateway.response_capture` filters private `<heartbeat>` and `[mem]...[/mem]` blocks before visible output is logged or sent.

Tool schemas and name dispatch live in `shenyu_gateway/tool_registry.py`; implementation methods live in `shenyu_gateway/gateway_tools.py`. If a tool is visible but behaves wrong, check `tool_registry.py` dispatch first, then the matching method in `gateway_tools.py`.

For quick live triage, call `GET /api/gateway/debug` from the admin session. It returns masked config, upstream routing, tool mode, store overview, and latest request/error IDs without dumping the full prompt payload.

Gateway tool descriptions are intentionally short because they enter the model tool context. Keep them to one-line purpose plus backing pool/table. Put detailed usage notes in `shenyu_supabase_guide` or docs, not in every parameter description.

Useful boundary map:

- Broker mode exposes only `shenyu_gateway_tool`; call it with `tool` set to the full gateway tool name, including the `shenyu_` or `supabase_` prefix, and put the selected tool's arguments in the `params` object, not a JSON-encoded string. The old `arguments` field is still accepted for compatibility.
- `shenyu_recall`: visible unified recall tool; returns a bounded excerpt and source id. Indexed document sources cover `memory`, `journal`, `windowsill`, settled normal `heartbeat`, `room`, `board`, `calendar`, and `notebook`; stars, active mem notes, and recent live heartbeats are federated through their specialized paths. Full recall traces stay in gateway logs.
- `shenyu_recall_read`: reads the full original selected by `source_type + source_id`.
- `shenyu_list_mem_notes`: visible mem-note browse/review tool; reads Supabase `shenyu_mem_notes`.
- `shenyu_ask_memory`: deprecated compatibility name; direct or broker calls are rejected with `error_kind=validation`. Use `shenyu_recall` with `source_types=["memory"]`.
- `shenyu_search_primary_texts`: deprecated compatibility name; direct or broker calls are rejected with `error_kind=validation`. Use `shenyu_recall` with the matching source types.
- `shenyu_surface_passages`: hidden/internal compatibility handler. Calendar generation still uses its random room/message-board surfacing, but it is not part of the visible model tool schema.
- `shenyu_search_mem_notes`: visible mem-note search tool; reads Supabase `shenyu_mem_notes`.
- `shenyu_read_heartbeat`: gateway tool; reads SQLite `heartbeat_entries` or `hisense_heartbeat`.
- `supabase_*`: gateway fallback tools for direct Supabase table operations.
- `GATEWAY_TOOL_MODE=broker`: exposes one compact `shenyu_gateway_tool` that dispatches to the same gateway-native tools. Use `full` when the model needs stricter per-tool parameter schemas.
- `query_memory` and `get_memory_by_title`, when visible, are client-provided tools from outside the gateway; inspect the client/Operit tool definitions for their backing pool.

## Context Layer Debugging

When context looks wrong, inspect in this order:

1. `cfg` flags: `MAX_CLIENT_MESSAGES`, `ENABLE_COLD_START`, `CALENDAR_INJECT_*`, `INJECT_MEM_NOTES`, `ENABLE_GATEWAY_TOOLS`, `GATEWAY_TOOL_MODE`.
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
mem system
heartbeat system
tool_policy system
format system
cold-start bridge messages, when active
trimmed client history
latest user
```

Prompt-cache markers target request tools, `stable`, `slow`, and `format` when those layers exist. The `format` marker follows the reading order and therefore includes any preceding mem/heartbeat/tool-policy blocks; a changing mem note can invalidate that marker without affecting the earlier stable/calendar markers.

## Calendar Debugging

Calendar generation uses `CalendarService` in `gateway.py`, but source collection lives in `calendar_sources.py`.

Current source rules:

- Day: latest 10 `request_context_snapshots`, latest 8 normal heartbeats, recent day/week/month pages, and a small surface pass.
- Week: latest 8 context snapshots, latest 5 normal heartbeats, and recent day/week/month pages.
- Month: latest 6 context snapshots, latest 5 normal heartbeats, and recent day/week/month pages.

If generated pages look empty, check `request_context_snapshots` first, then `heartbeat_entries`, then Supabase `calendar_pages`.

## Response Capture Debugging

Private assistant tags are parsed in `response_capture.py`:

- `AssistantTagFilter` supports chunked streaming input. It withholds partial `<heartbeat>` tags until they close or are flushed. Inline `[mem]` and `[star]` tags are left visible in assistant output (capture is now via tool calls only).
- `split_private_assistant_tags()` is the non-streaming helper.
- `store_heartbeat()` writes normal or Hisense heartbeat rows through `GatewayStore`.

Visible output should never include closed private blocks:

- `<heartbeat>...</heartbeat>` is removed and written to `heartbeat_entries` or `hisense_heartbeat`.
- `[mem]` and `[star]` tags are left visible in assistant output; mem notes and stars are created exclusively via tool calls (`shenyu_write_mem_note`, `shenyu_create_star`).
- Incomplete heartbeat is captured and hidden on flush.

When this area breaks, check `test_gateway_tags.py` and `test_response_capture.py` first.

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
python -m py_compile gateway.py shenyu_gateway\store\__init__.py shenyu_gateway\stars\__init__.py shenyu_gateway\calendar_sources.py shenyu_gateway\context_layers.py shenyu_gateway\response_capture.py shenyu_gateway\upstream_adapter.py test_external_contracts.py test_gateway_hisense_context.py test_gateway_tags.py test_gateway_trim.py
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
- Keep private response tag filtering and heartbeat capture helpers in `response_capture.py`.
- Keep upstream protocol conversion in `upstream_adapter.py`.
- Add comments only where they protect external contracts or explain non-obvious behavior.
