# Shenyu Gateway Agent Notes

新线程先读 `START_HERE.md`，再按任务进入对应现行文档；不要默认把所有设计稿和 Debug 文档全文读完。

## Environment

- The active repository is `/home/yuan/shenyu-gateway` inside **Ubuntu 24.04 LTS on WSL2** (user `yuan`). Treat this Linux path as the source of truth.
- Run Bash, Python, Git, Docker, tests, and helper scripts directly inside Ubuntu. Do not route ordinary work through Windows CMD or PowerShell.
- Windows 11 is the host. Enter Ubuntu from Windows with `wsl` or `wsl -d Ubuntu-24.04 --exec bash -lc "<command>"` only when starting outside WSL.
- The old Windows checkout at `C:\Users\曾\Desktop\shenyu-gateway` and its `/mnt/c/...` mapping are not the active working copy. Do not edit or deploy from them unless the user explicitly asks.
- `.wslconfig` is configured at `~/.wslconfig` (`networkingMode=mirrored`, `autoProxy=true`, memory capped at 8GB) to avoid the "localhost proxy not mirrored" warning.
- VS Code should open the Linux repository through the official WSL extension.
- For manual Admin browser/visual checks, use `cd admin && npm run preview:isolated`. It builds the UI and starts a `/tmp` SQLite gateway with `.env`, Supabase, archives, and background workers disabled. Do not start the ordinary gateway against real credentials for a visual-only preview.

## Project Memory and Collaboration

- `AGENTS.md` is the repository-wide instruction file for coding agents. Keep durable cross-tool rules here so Codex, Claude Code, GLM, and other agents can share them. Tool-specific global memory is optional and must not be the only place where project knowledge lives.
- The owner works from product experience and is not expected to translate observations into code or architecture terminology. Convert their description into technical hypotheses, explain unfamiliar terms in plain language, and never treat non-technical wording as an unclear requirement by default.
- For gateway-core changes—message history, trimming, context assembly, memory, cache breakpoints, streaming, tool loops, or provider adaptation—do not rush into implementation. First restate the intended user-visible behavior, inspect the relevant flow, explain what will and will not change, and align with the owner before editing.
- Before a large feature or cross-zone refactor, use these questions as a coverage check: where the feature enters; which zones and bridges it crosses; who owns the authoritative state/write; what observable outcome counts as real success; where failure evidence appears; and how old behavior can be disabled, rolled back, and verified. Surface a concise boundary brief before editing when the answers expose a behavior choice, risk, or uncertainty that needs owner alignment; do not mechanically enumerate all six or expose private chain-of-thought.
- Clearly separate facts proven by logs or code, likely explanations, and items that still need verification. Do not present an upstream guess as a gateway fact.
- Prefer provider-independent behavior and standard protocol semantics. Do not permanently specialize core logic around one relay's unusual reporting without explicit agreement.
- Treat wording, layout, and daily readability of the admin UI and logs as product behavior. The owner uses these views directly; engineering-only labels are not automatically useful.
- Request logs are where a helpful addition becomes irreversible: full Messages, upstream payloads, responses, images, raw Thinking, and opaque signatures are live-process-only and must never be written into the persistent history. `LOGS_GUIDE.md` § 每个标签看什么 specifies the two retention tiers and what each one is allowed to keep.
- In Memory Island logs, Stars and Mem are peer lanes; never make one lane less inspectable than the other. `LOGS_GUIDE.md` § 小岛与缓存 describes what both lanes show and how an update is rendered.
- The old-newspaper basket searches stored titles and RSS summaries with literal case-insensitive matching, and must never be upgraded to semantic search. This repository has an embedding-based Recall path, so the substitution looks like an improvement; it would quietly change what 沈予 can find among his own windowsill days. `docs/architecture/MEMORY_ROOM.md` § Window Newspaper owns the rest of the basket's behavior — reverse-date listing, when an issue counts as read, and what never enters it.
- 来历书 (origin books; the older internal name was 矛盾书) are frozen relationship records. If a migration or cleanup cannot prove that `original_text` is still immutable and annotations are still append-only, stop and ask 沈予 instead of proceeding on the assumption that a rewrite is equivalent — a lost line here is a piece of their past with no backup. `docs/architecture/REQUEST_CONTEXT.md` § Origin books（来历书） lists the invariants and where they are enforced.
- History branch detection compares normalized semantic content, not client representation: expired images, dynamic extra bundles, equivalent string versus text-block forms, and a rolling-window head slide must not reset the context epoch. Only a real edit before the active tail turn is a `branch`. `docs/architecture/REQUEST_CONTEXT.md` § Prompt Cache holds the classification rules, including the overlap threshold.
- If a command, dependency, environment detail, missing document, or repeated manual step makes work slower or less reliable, tell the owner promptly and suggest a concrete improvement. Improving the agent workflow is part of maintaining the project.
- Do not append a routine map-usability report to every handoff. Raise navigation friction when the owner asks or when a large task hit the same detour repeatedly, and treat one agent's confusion as a signal to verify rather than a reason to expand the map — `DOCS_MAP.md` § 维护原则 states the three conditions that justify actually editing a document.
- Before pushing or handing off a meaningful change, ask whether documentation whose current truth changed must be updated — only that, and do not create a new design document by default. `DOCS_MAP.md` § 地图同步边界 maps each kind of change to the one document that owns it, and § 内容归属 says which content belongs where.
- When a rule or fact gains a new authoritative home, search the live documents for older copies and leave exactly one detailed original. A copy left behind stays authoritative-looking and then rots, because nothing here reclaims text automatically — do not skip the search on the grounds that the new home is obviously better. An older location that still has entry value shrinks to a pointer naming the document, the real `## `/`### ` heading, and what the reader will find there; a bare "see X" is not one. Copies that are no longer an entry are deleted. Pointer rot is the half you cannot see, so `tests/test_project_map.py` resolves every `§` in the live documents and fails on the ones that point nowhere — including when a later rename is what broke them.
- When work is planned to continue in a later session — remaining batches, an agreed step plan, decisions the next agent must know — write that plan into a repository file (for example a dated note under `docs/history/`) before the session ends. A plan that exists only in the conversation is lost to the next agent, who must then reconstruct intent from code.
- **`master` is production.** Coolify auto-deploys that branch, so a `master` push ships to the gateway 沈予 and 圆圆 are actually living in — with the real Supabase and the real `/app/data` volume. Ask the owner before pushing it unless they have already said to. Feature branches are not deployed and carry no such weight. `docs/DELIVERY.md` § 交付状态梯 owns the rest: the four status tiers, the evidence each one needs, and why a push receipt is not yet `deployed`.
- Preserve unrelated working-tree changes. Never stage or commit the whole tree without reviewing the exact diff.
- When more than one agent works this repository at the same time, at most one agent works directly in the master working tree; every other concurrent agent uses its own git worktree (or clone) on a short-lived branch and merges back promptly — same-day, not week-long branches. The owner should announce concurrent work when they know about it, but agents must not rely on that: before starting, check `git status` for foreign uncommitted changes, and treat their presence as proof another agent may be active. In a shared tree, stage only your own files, attribute test failures via `git status` before assuming they are yours, and never run `git stash` or other whole-tree operations for diagnostics.

## Mechanical Change Checklists

### Project map synchronization

Before handing off a meaningful change:

1. For every touched runtime module or independently maintained frontend view/panel, verify that its path is discoverable in `README.md` § Maintenance Map, either directly or through a package entry. Add a missing entry even when the file predates the current change; when such a boundary is added, removed, renamed, or moved, update the map in the same change.
2. Package-internal mixins and small private helpers may remain summarized under their package entry unless they become an independently maintained boundary. Tests, generated files, and build artifacts do not need per-file map entries. A map entry owes a path and a responsibility, not an appearance: a pure restyle is not by itself a map change, and the only check is whether the entry's own wording still holds afterwards — if it names a layout, component, or effect the restyle removed, fix that clause in the same change. `tests/test_project_map.py` reads only the backticked paths, never the prose, so a long entry buys nothing a short one does not; colors, geometry, and decoration belong to `docs/frontend/STYLE_AND_CRAFT.md` § 视觉拥有者 or the component itself. When a view gains an internal block rather than a new maintained boundary, no document needs updating at all.
3. If module responsibility, a major call chain, or a cross-zone bridge changed, update `docs/architecture/SYSTEM_ZONES.md` and the owning architecture reference. An internal optimization that leaves those facts unchanged should not create architecture-doc churn. When an Admin view's layout or visual language changes, also grep the owning architecture document for stale visual descriptions of that view (old layout, component, or effect names) and refresh the wording in the same change: behavior contracts usually survive a restyle, while pixel-level wording rots.
4. If a Markdown document is added, renamed, archived, or changes status, update `DOCS_MAP.md`. Do not register temporary local investigation notes that will not enter the repository.
5. When a map-covered path changes, run `python -m pytest -q tests/test_project_map.py` before handoff.
6. A `§` cross-reference must name a real `## `/`### ` heading in the document it cites; the same test resolves all of them, so renaming a heading means grepping `§` for its name in the same change. Live documents (everything outside `docs/history/`) may cite a symbol with the `file::symbol` form (see `DESIGN.md` § 改动边界 tables for examples); `tests/test_project_map.py` resolves every such anchor and fails when the symbol is gone. Writing that form here would make this line fail its own check, which is the point: the guard is unconditional. When renaming or moving a function, constant, or class, grep the docs for its name in the same change. Name the file by a suffix unique in the repository — a bare `_embedding.py` matches several packages and will fail.
7. Admin `家里地图` reads the existing `SYSTEM_ZONES.md` request chain/zone/bridge structure, README product reverse index, `DOCS_MAP.md` current-doc table, and resident-home authorities automatically. Ordinary content edits need no duplicate UI data. If a zone is added, one of those parsed heading/table shapes changes, or the map gains/loses an authority, verify `shenyu_gateway/project_map.py` in the same change and run `python -m pytest -q tests/test_owner_project_map.py`.

For a meaningful completed feature, fix, Admin/PWA workflow, or deployment/verification improvement, add one coherent owner-facing entry to `project_delivery_log.jsonl` with `python scripts/project_delivery.py record ...` after the final verification round. Group small commits that form one outcome; do not record ordinary formatting or every commit. Bind the entry to one README product, changed paths, verification evidence, and an honest status; the four-tier status ladder, the sufficient evidence per tier, the probe boundaries, and the verification-baseline recording rules are defined once in `docs/DELIVERY.md`. In `verification`, record one line stating the baseline passed (or which item was skipped and why) plus only this delivery's distinctive evidence; do not restate the baseline checklist per entry. Add `lesson` only when it will help a future agent; link confirmed production failure lessons with `debug_ref` instead of duplicating `DEBUGGING_GUIDE.md`. When an approach was measured during this delivery and rejected, record it with `--abandoned '放弃了什么|一句话为什么|大概花了多少'` (repeatable). The format is enforced, not a convention: exactly those three fields, one line each, at most 120 display columns (about 60 Chinese characters — the ceiling counts columns, not characters, so "one line" means the same thing in either language), no fourth field. It exists so the next agent does not re-walk a measured dead end — the road, the reason, the cost, nothing else. Process notes and takeaways belong in `lesson`. Recording it in your own agent memory does not count: only your line of work reads that, and the point is to reach whoever comes next. This delivery journal is separate from `resident_home_changes.jsonl`, which remains reserved for resident-impact changes. In every owner- or resident-facing record — delivery entries, change-ledger lines, review summaries — call the resident 沈予, never "assistant" or another role word; this is a house rule the resident has had to correct twice.

`DOCS_MAP.md` § 地图同步边界 is the authority for which map owns each kind of change.

### New subsystem growth path

New features are allowed — encouraged — to start life in one file. Do not pre-split a subsystem whose seams are still guesses; build it, get tests around it, and let the real boundaries show up in the code. This is how every current package grew (`stars/`, `mem_notes/`, `store/`, `gateway_tools/`, `recall/`, and the PWA's `App.vue` extraction).

When a file settles and grows past roughly 800–1000 lines, split it along its proven seams following the existing mixin-package pattern (`stars/` is the reference: per-domain `_*.py` mixins, one facade class assembled in `__init__.py`, every externally imported symbol re-exported so callers need no changes). Before moving code, grep for import sites, monkeypatch paths, and `resident_home_manifest.json` globs; after moving, run the map checklist above. Splitting is mechanical maintenance, not a design phase — do it when the seams are obvious, not before. A structure-only extraction must leave user-visible behavior unchanged (`README.md` § Maintenance Map lists which boundary owns what), and a small feature does not earn its own standalone design document.

Shared literal contracts — a regex, wire-format string, or config key set that must stay byte-identical across modules or across client/server — live in exactly one home module that every other site imports; `shenyu_gateway/client_extra.py` is the reference (kept free of package-internal imports so importing it can never create a cycle). This rule is deliberately narrow: it covers only literals that must agree verbatim. Code that is merely similar stays where it is, a contract with a single consumer needs no home yet, and such a home must not grow into a general util module.

The local timezone is one such contract. `shenyu_gateway/runtime.py` holds the only definition; import it from there instead of writing `timezone(timedelta(hours=8))` or `ZoneInfo("Asia/Shanghai")` in place. The fixed offset is deliberate — China has had no DST since 1991, so the two forms agree on every moment this code will see, and the offset needs no tzdata in the runtime image. `client_extra.py` keeps its own copy, and only it: importing runtime would break the no-package-internal-imports rule that makes it cycle-proof.

### Resident home synchronization

When a runtime, configuration, or architecture change may alter what a resident experiences, run:

```bash
python scripts/resident_home.py check
```

For every `review_required` component, record a short resident-facing summary and impact with `review <component> --summary ... --impact ...`, or explicitly acknowledge that the change has no resident impact with `--no-impact`. Write `impact` from the resident's perspective (preferably starting with `你...`); the human report renders it on a fixed `影响：...` line. The command records the current source fingerprint, commit, author, and Asia/Shanghai timestamp itself; do not hand-write those fields. When the review runs before the final commit, the recorded `revision` carrying a `-dirty` suffix or pointing at the previous commit is expected and needs no post-commit correction: `check` compares the per-file hashes, not the commit id. The structured source of truth is `resident_home_manifest.json`, and the weekly ledger is `resident_home_changes.jsonl`.

`check` also reports text files in the worktree whose copy on disk is not pure LF, because the fingerprints it compares normalize line endings and therefore cannot see this. A file this change touches fails the check — normalize it with `sed -i 's/\r$//' <path>` before reviewing. Files created in this session count as touched: the listing includes untracked files (`--others --exclude-standard`), since a new CRLF file used to be invisible right up until someone added it and it turned into inherited drift nobody owns. `.gitignore`d paths stay out. Where git is unavailable the check prints `skipped (no git)` rather than nothing, because printing nothing is indistinguishable from a clean result. Files nobody touched are listed for information only and do not fail: `.gitattributes` sets `eol=lf`, so non-LF bytes never reach a commit, and 26 tracked files carry inherited drift from earlier sessions that no single handoff can be asked to clear. git decides what counts as text, so binaries need no exclusion list.

`check` marks changed files that belong to more than one component with `*`. When every changed file of a flagged component is shared, `python scripts/resident_home.py ack-shared` records the no-impact acknowledgements for all such components in one pass and prints which shared files changed and who consumes them — read that output instead of rubber-stamping components one by one. Components with changes in files they own exclusively still require a full `review`. Register reviews once per work session, after the final fix round; when sub-agents split an implementation, the orchestrating agent records the reviews.

For every new runtime configuration field that is editable in Admin, inspect and update all of these locations before handoff:

1. `shenyu_gateway/config.py` — environment/default loading and runtime serialization.
2. `shenyu_gateway/schemas.py` — `ConfigUpdate` request contract.
3. `shenyu_gateway/config_routes.py` — Admin read response, validation, environment mapping, and persisted override handling.
4. `admin/src/api/config.ts` — frontend TypeScript contract.
5. The view that owns the field's domain — default state, save payload, and visible control. `admin/src/views/ConfigView.vue` is the default home, but a field belonging to a domain that already has its own settings surface goes there instead, beside the switches the resident would look for it next to: memory fields (Stars and Mem) in `admin/src/views/Mem0View.vue` and `admin/src/views/stars/StarsSettingsPanel.vue`. Put a field where its neighbours already live; do not add a second home for a domain that has one.
6. `tests/test_config_update.py` — default, save, validation, and restore coverage appropriate to the field.

Also update the owning README or architecture document when the field changes user-visible behavior or deployment requirements. If any checklist item is genuinely not applicable, state why in the handoff. If this checklist itself is outdated or incomplete, propose the change and discuss it before silently skipping or expanding the rule.

After Admin routes, page loading, or core interactions change, run `cd admin && npm run test:e2e`. The Playwright suite is an alive/not-alive smoke layer: keep it read-only, prefer stable `data-testid` hooks over mutable display copy, fail on browser runtime or same-origin asset errors, and do not turn it into screenshot or visual-polish testing. Add, remove, or update the corresponding smoke case in the same change when an Admin route or core workflow changes; ordinary copy and styling edits should not require smoke-test rewrites. `npm run test:e2e` already runs `npm run build`, so do not run a separate Admin build before it. If the default E2E port is occupied, set `E2E_PORT` to an unused port (for example, `E2E_PORT=18111 npm run test:e2e`) rather than enabling `reuseExistingServer`; keep reuse disabled so the smoke suite cannot accidentally test a foreign service.

### Supabase test fakes

A test fake standing in for Supabase must honour `params["select"]`: route the rows it returns through `project_select` from `tests/fake_postgrest.py`. Fakes that ignore `select` hand back every column their fixture rows happen to carry, so dropping a column from a real select string changes nothing any test can see. Measured on 2026-08-28, before the fakes projected: 33 of the 35 columns in the light mem-note select list could be deleted — `id` and `content` included — with all 749 tests green. `tests/test_supabase.py` fails on any fake that returns a non-empty row set without projecting, and on any fake that parses a select string by hand. A fake that only ever returns `[]` or raises has no columns to hide and is exempt.

Projection alone is not coverage. It turns an unselected column into an absent key, but only a test that reads the value can go red — so when adding a column to a select list, add or extend a test that touches it.

The helper deliberately does not model embedded resources, aliases, or casts, and returns rows untouched when it sees them; nothing in this repository sends that syntax. It also cannot catch "the migration was never run" — a fake row is a fixture, not a table. Deriving column sets from `supabase/migrations/*.sql` was measured and rejected: 3 of the 9 tables the code queries by literal name (`atomic_memories`, `calendar_pages`, `shenyu_notebook`) have no migration in the repository, so that derivation cannot be a repo-wide invariant.

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

For a PWA user-visible fix that is being delivered to production, follow the delivery status ladder and probe boundaries in `docs/DELIVERY.md` plus the frontend-only acceptance rules (PWA three rules, mobile-first viewport, cache-attribution discipline) in `docs/frontend/STYLE_AND_CRAFT.md` § 前端验收铁律.

After a production bug's root cause is confirmed by logs, code, or tests and the fix is complete, append exactly one row to `DEBUGGING_GUIDE.md` § Symptom Autopsy Index and follow that section's writing rules: an externally observable symptom, the minimal root-cause path plus fault, and an actionable lesson for the next investigator. Do not record unverified suspicions as autopsy facts.

For gateway, Coolify, VPS, upstream, streaming, cache, or tool-call trouble, the helper is usually the first evidence source:

```bash
python scripts/vps_gateway_logs.py api --via-ssh --errors --detail
```

Expected environment variables:

```bash
export SHENYU_GATEWAY_URL="https://gateway.example.com"
export SHENYU_GATEWAY_TOKEN="gateway-api-token"
```

The helper also auto-loads a local ignored config file at `.shenyu-gateway-debug.local.json`, or a home config at `~/.shenyu-gateway-debug.json`, or the path in `SHENYU_GATEWAY_LOG_CONFIG`. Its config shape, the WSL rule that `vps_identity` must be a Linux-visible path, local-JSON and `ssh` container modes, and the redeploy-safe container lookup are documented once in `DEBUGGING_GUIDE.md` § Error Log Quickstart and § VPS, SSH, and Coolify Operations.

Do not store gateway tokens, SSH host secrets, or API keys in repo files. Ask the user for missing credentials or use environment variables already configured in the shell.

## Log Interpretation

Field-by-field meanings (`tools_offered` versus `gateway_tools_executed`, relay `Max retries reached`, `prompt_cache.protocol`, outbound `thinking`, `anthropic_thinking.preserved` / `signature_present` / `redacted_present`, and the pending-tool restore conditions) live in `DEBUGGING_GUIDE.md` — § Symptom Triage for the symptom-to-evidence table, § Error Log Quickstart for the helper's fields, § Chat Request Flow for per-round tool and Thinking evidence. Read them when reading logs; they are not needed to write code.

Cache evidence has its own reading order and its own arithmetic, both documented once: `DEBUGGING_GUIDE.md` § Error Log Quickstart gives the tool-round triage sequence (marker count and breakpoint paths, then prefix fingerprints, then provider-reported read/write) and states what a fingerprint match does and does not prove; `LOGS_GUIDE.md` § 小岛与缓存 gives the user-facing percentages — which one is the single-request cache rate, when to show no percentage at all, and why the `input` badge must not re-add cached tokens.

One rule does belong here, because it decides whether you may edit at all: a log field proves what it names and nothing more. `tools_offered > 0` with `gateway_tools_executed = 0` locates the failure before gateway tool execution, and an outbound `thinking=...` proves Thinking was requested, not returned — never present either as proof of upstream behavior.

Read `DOCS_MAP.md` for document status and `DEBUGGING_GUIDE.md` for the full request flow and deeper triage notes.
