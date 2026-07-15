# Shenyu Gateway Agent Notes

新线程先读 `START_HERE.md`，再按任务进入对应现行文档；不要默认把所有设计稿和 Debug 文档全文读完。

## Environment

- The active repository is `/home/yuan/shenyu-gateway` inside **Ubuntu 24.04 LTS on WSL2** (user `yuan`). Treat this Linux path as the source of truth.
- Run Bash, Python, Git, Docker, tests, and helper scripts directly inside Ubuntu. Do not route ordinary work through Windows CMD or PowerShell.
- Windows 11 is the host. Enter Ubuntu from Windows with `wsl` or `wsl -d Ubuntu-24.04 --exec bash -lc "<command>"` only when starting outside WSL.
- The old Windows checkout at `C:\Users\曾\Desktop\shenyu-gateway` and its `/mnt/c/...` mapping are not the active working copy. Do not edit or deploy from them unless the user explicitly asks.
- `.wslconfig` is configured at `~/.wslconfig` (`networkingMode=mirrored`, `autoProxy=true`, memory capped at 8GB) to avoid the "localhost proxy not mirrored" warning.
- VS Code should open the Linux repository through the official WSL extension.

## Project Memory and Collaboration

- `AGENTS.md` is the repository-wide instruction file for coding agents. Keep durable cross-tool rules here so Codex, Claude Code, GLM, and other agents can share them. Tool-specific global memory is optional and must not be the only place where project knowledge lives.
- The owner works from product experience and is not expected to translate observations into code or architecture terminology. Convert their description into technical hypotheses, explain unfamiliar terms in plain language, and never treat non-technical wording as an unclear requirement by default.
- For gateway-core changes—message history, trimming, context assembly, memory, cache breakpoints, streaming, tool loops, or provider adaptation—do not rush into implementation. First restate the intended user-visible behavior, inspect the relevant flow, explain what will and will not change, and align with the owner before editing.
- Clearly separate facts proven by logs or code, likely explanations, and items that still need verification. Do not present an upstream guess as a gateway fact.
- Prefer provider-independent behavior and standard protocol semantics. Do not permanently specialize core logic around one relay's unusual reporting without explicit agreement.
- Treat wording, layout, and daily readability of the admin UI and logs as product behavior. The owner uses these views directly; engineering-only labels are not automatically useful.
- In user-facing cache logs, distinguish cache-prefix reuse, provider-reported total-input coverage, cross-request hit rate, and bill savings. The compact percentage should use reported cache read versus cache creation; keep unstable total-input coverage diagnostic-only and label every metric plainly.
- The per-round `input` badge is provider-normalized total input and excludes output tokens: use Anthropic uncached input + cache read + cache creation, but use OpenAI-compatible `prompt_tokens`/`input_tokens` as reported because cached tokens are already a subset. Normalize this in backend `cache_usage.total_input_tokens`; do not re-add cached tokens in the frontend.
- Treat cache-prefix fingerprints as provider-independent evidence. Matching path/fingerprint pairs prove that the gateway emitted the same cacheable prefix; they do not identify a specific upstream node or justify provider-specific cache behavior without additional evidence and explicit agreement.
- Request logs have two retention tiers: the live process keeps 30 mutable entries, while SQLite keeps a bounded safe history (default 200) for Admin/API/helper reads across container replacement. Full Messages, upstream payloads, responses, images, raw Thinking, and opaque signatures remain live-process-only and must never be added to the persistent history. `ssh` mode still reads only the current container's stdout/stderr.
- In Memory Island logs, Stars and Mem are peer lanes. When showing current contents or changes, apply the same current/added/updated/removed semantics to both; do not make one lane less inspectable than the other.
- The Room window newspaper is a manual RSS workflow, not personalized recommendation. Fetch only the fixed feed allowlist, keep source titles/summaries/URLs unchanged apart from HTML cleanup and a three-sentence excerpt, reject entries whose feeds provide no real summary, and let the optional quality model return drop ids only. Never let that model crawl pages, translate, summarize, or rewrite feed content.
- Keep the old-newspaper basket reader-facing: list archived issues in reverse order by their Asia/Shanghai publication date, mark an issue read only when its full date is opened, and search stored titles and RSS summaries with literal case-insensitive matching only. Never include drafts, discarded issues, or the current windowsill issue, and do not replace this grep-style lookup with semantic search.
- History branch detection must compare normalized semantic content, not client representation details. Expired images, dynamic extra bundles, and equivalent string versus text-block forms must not reset the context epoch; only a real earlier conversation edit should be classified as `branch`.
- If a command, dependency, environment detail, missing document, or repeated manual step makes work slower or less reliable, tell the owner promptly and suggest a concrete improvement. Improving the agent workflow is part of maintaining the project.
- Before pushing or handing off a meaningful change, consider whether `README.md`, `DESIGN.md`, `DEBUGGING_GUIDE.md`, `LOGS_GUIDE.md`, or `DOCS_MAP.md` must be updated. Update only documentation whose current truth changed; do not create a new design document by default.
- When a feature develops a clear, independently maintained boundary, extract the smallest coherent module or frontend component and update the existing code map or owning architecture document in the same change. Structure-only extraction must preserve user-visible behavior, and small features should not each receive a duplicate standalone design document.
- Preserve unrelated working-tree changes. Never stage or commit the whole tree without reviewing the exact diff.

## Mechanical Change Checklists

For every new runtime configuration field that is editable in Admin, inspect and update all of these locations before handoff:

1. `shenyu_gateway/config.py` — environment/default loading and runtime serialization.
2. `shenyu_gateway/schemas.py` — `ConfigUpdate` request contract.
3. `shenyu_gateway/config_routes.py` — Admin read response, validation, environment mapping, and persisted override handling.
4. `admin/src/api/config.ts` — frontend TypeScript contract.
5. `admin/src/views/ConfigView.vue` — default state, save payload, and visible control.
6. `tests/test_config_update.py` — default, save, validation, and restore coverage appropriate to the field.

Also update the owning README or architecture document when the field changes user-visible behavior or deployment requirements. If any checklist item is genuinely not applicable, state why in the handoff. If this checklist itself is outdated or incomplete, propose the change and discuss it before silently skipping or expanding the rule.

After Admin routes, page loading, or core interactions change, run `cd admin && npm run test:e2e`. The Playwright suite is an alive/not-alive smoke layer: keep it read-only, prefer stable `data-testid` hooks over mutable display copy, fail on browser runtime or same-origin asset errors, and do not turn it into screenshot or visual-polish testing. Add, remove, or update the corresponding smoke case in the same change when an Admin route or core workflow changes; ordinary copy and styling edits should not require smoke-test rewrites.

## Encoding Rules

- Treat source, Markdown, and config files as UTF-8.
- When reading files in Windows PowerShell, use `Get-Content -Encoding UTF8`.
- Do not use PowerShell redirection, default `Set-Content`, or default `Out-File` to write files that contain Chinese text.
- Prefer `apply_patch` for edits. Do not shell-concatenate large Chinese text into source files.
- If Python files changed, run `python -m py_compile` before handing off.
- If Chinese text changed, scan for mojibake markers: `淇`, `閺`, `鈹`, `銆`, `锛`, `紝`, `娌堜簣`.
- If garbled text appears, first decide whether it is terminal display trouble or real file damage.

## Debugging Approach

First listen to the complete symptom and restate the question being investigated. Use the gateway's architecture to identify the relevant boundaries, then inspect logs before assigning blame or changing code. Logs are evidence, not a substitute for understanding what the owner observed.

For gateway, Coolify, VPS, upstream, streaming, cache, or tool-call trouble, the helper is usually the first evidence source:

```bash
python scripts/vps_gateway_logs.py api --via-ssh --errors --detail
```

Expected environment variables:

```bash
export SHENYU_GATEWAY_URL="https://gateway.example.com"
export SHENYU_GATEWAY_TOKEN="gateway-api-token"
```

The helper also auto-loads a local ignored config file at `.shenyu-gateway-debug.local.json`, or a home config at `~/.shenyu-gateway-debug.json`, or the path in `SHENYU_GATEWAY_LOG_CONFIG`.

Config shape:

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

For a retained local JSON log:

```bash
python scripts/vps_gateway_logs.py local tmp_gateway_log_84f8b85a.json --detail
```

For VPS container logs:

```bash
export SHENYU_VPS_HOST="root@example.com"
python scripts/vps_gateway_logs.py ssh --list-containers
python scripts/vps_gateway_logs.py ssh --match "shenyu|gateway" --tail 300 -f
```

If public gateway API access is not blocked by Cloudflare, this also works:

```bash
python scripts/vps_gateway_logs.py api --errors --detail
```

Do not store gateway tokens, SSH host secrets, or API keys in repo files. Ask the user for missing credentials or use environment variables already configured in the shell.

## Log Interpretation

- `tools_offered` means tools were included in the request payload.
- `gateway_tools_executed` means the gateway actually received and ran gateway-native tool calls.
- If `tools_offered > 0` but `gateway_tools_executed = 0`, the failure happened before gateway tool execution. Check upstream, relay, payload shape, streaming, and prompt-cache compatibility first.
- `Max retries reached` from the upstream relay usually means the relay failed before the gateway received a usable model response.
- For OpenAI-compatible relays, `prompt_cache.protocol=openai` with `cache_control` breakpoints is a compatibility suspect if errors only appear with tools/streaming/cache together.
- An outbound `thinking=...` field proves only that Thinking was requested. It does not prove that the upstream returned native Thinking blocks.
- `internal_tool_rounds[].anthropic_thinking.preserved=true` proves that native Thinking or redacted Thinking blocks were captured for an unfinished Anthropic tool turn. `signature_present` and `redacted_present` are booleans only; never log or attempt to decode their opaque content.
- Pending Anthropic tool context may be restored only when the session, tool-call ids, visible assistant content, tool names, and arguments still match. A rolled, edited, or branched reply must not recover the original hidden blocks.

Read `DOCS_MAP.md` for document status and `DEBUGGING_GUIDE.md` for the full request flow and deeper triage notes.
