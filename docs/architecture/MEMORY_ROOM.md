# 记忆与 Room 子系统参考

本文由原 README 的现行子系统章节迁出，负责 Mem Notes、Star Memory、Room Mode 和 private capture 行为。长期设计原则见 `DESIGN.md`。

这些子系统属于 `docs/architecture/SYSTEM_ZONES.md` § 住户数据注意事项覆盖的关系数据；修改前先读其中的共同保护边界，本页只维护具体行为。

## Mem Note Layer

Mem notes are small personal notes, separate from event memories and calendar pages.

`INJECT_MEM_NOTES` controls injection: before a reply, search mem notes that are eligible for automatic recall and inject relevant hits in the `mem` layer. `active` is necessary but not sufficient: the row must also pass active-ready validation, and a resolved promise is never automatically surfaced. Eligibility means the note may participate in retrieval; it does not promise that the note will appear in a particular turn.

Inline `[mem]...[/mem]` tag capture has been removed. Mem notes are now written exclusively via tool call (`shenyu_write_mem_note`). The note types are `她为我做的事`, `我为她做的事`, `关于她的事实`, `关于我的事`, `心里那一档`, and `承诺`. If type or trigger is missing, the writer fills safe defaults so the note can surface immediately.

Writing a note requires only `content`. All other fields are auto-enriched from the content when not explicitly provided:

- `memory_kind`: resolved through alias map (中英文 + fuzzy substring), then regex inference from content.
- `summary`: first sentence or first 60 characters.
- `people/places/objects/keywords`: heuristic extraction (known names, relation suffixes, geo suffixes, quantifier+noun patterns, filtered scene keywords). Auto keywords deliberately avoid common Chinese n-gram fragments.
- `mem_type`: regex pattern matching on Chinese content.

The `memory_kind` alias map accepts Chinese variants (`承诺`→`promise`, `梗`→`running_joke`, `旅行`→`trip`, etc.) and English shorthand (`joke`, `habit`, `fact`, `person`, etc.). Unrecognized values trigger auto-inference rather than silently dropping to NULL.

Heat score (`compute_heat`): an Ebbinghaus-style temperature combining importance-based initial heat, time decay with half-life extending per recall count, and a small recall bonus. Heat is computed on read and returned in list items for observability. It does not currently affect injection ordering or filtering.

Search/injection flow:

1. `ContextBuilder` calls `MemNoteService.search_notes_contextual()` when enabled.
2. Active rows are matched through narrow anchors first: legacy `entities`, then v2 `people`, `places`, and `objects`. v2 `keywords` only join this no-threshold anchor path after a specificity filter, so generic auto-filled fragments such as "今天" or "帮我" do not surface unrelated notes. Chinese anchors use recall-token matching so names and objects still match inside normal no-space Chinese sentences.
3. `running_joke` rows use `scene_tags` plus a time-decay serendipity gate instead of a fixed probability: just-used jokes are suppressed, then gradually recover toward 0.3 after a month. At most one running joke is injected per turn, and `last_used_at` is updated only when it actually surfaces.
4. `promise` rows with `resolved=true` stay available for admin/manual review but are skipped by automatic context injection.
5. Semantic recall is capped as anchored support and no longer fills empty slots with generic matches.
6. Cooldown blocks frequent repeats. Relevant hits are rendered as short bracket-style thoughts in the `mem` layer, with optional person/place/object anchors.

Before resolving each normal Memory Island, `ContextBuilder` re-checks the previous Mem lane against the current automatic-recall eligibility rule. A note that was collected into the old island but has since been archived, paused, left captured, made invalid for activation, or marked as a resolved promise is removed on the next context build instead of being retained by the `2/3` overlap gate. If that authoritative check itself fails, the old lane is preserved fail-soft rather than guessed inactive.

The active-ready validation accepts either legacy triggers (`trigger_text`, `trigger_keywords`, `entities`) or v2 structured anchors (`people`, `places`, `objects`, `keywords`, `scene_tags`, `trigger_scenarios`).

When an active Mem note enters the shared unified Recall index, its document contains only the original `content` and its time. `summary`, type, trigger text, importance, source model, and all structured fields remain Mem-management data; they do not enter shared keyword search, embedding, or graph auto-linking. The Mem-specific automatic-injection lane above still uses its own explicit eligibility and anchor rules.

Endpoints:

- `GET /api/gateway/mem-notes/search`
- `GET /api/gateway/mem-notes`
- `PATCH /api/gateway/mem-notes/bulk`
- `PATCH /api/gateway/mem-notes/{note_id}`
- `DELETE /api/gateway/mem-notes/{note_id}`
- `GET /api/gateway/legacy-atomic-memories`

Admin UI notes:

- Mem0 is now a standalone admin area instead of being embedded in the generic config page.
- The Mem0 page includes:
  - controls for mem-note injection
  - a full-set management view loaded with internal backend pagination rather than the old 50-row display cap
  - two resident-facing groups: `可自动想起` for rows that currently meet automatic-recall eligibility, and `已收起` for every other legacy status or ineligible active row
  - `收起来` writes `archived`; `放回来` writes `active` after the required category and trigger fields are present. Existing `captured`, `paused`, and `archived` rows remain unchanged until someone acts on them; the UI grouping is not a data migration
  - a row-level `沈予写的` badge when `source_model` starts with `tool:shenyu_write_mem_note`. This proves that the whole row came from Shenyu's write tool; old rows do not contain field-level provenance for distinguishing which individual fields were model-filled or gateway-enriched
  - the mem-note attribute workflow for Supabase `shenyu_mem_notes`, including suggestions, bulk save, bulk restore, and bulk storage
  - manually confirmed global entity anchors; unique exact-alias links are shown separately from resident-confirmed selections
  - read-only old `atomic_memories` lookup for manual migration

## Personal Memory Graph

The personal memory graph is a shared association layer over source-owned content. It does not copy or replace Mem, journal, notebook, calendar, heartbeat, Room, or old-memory bodies. Every mention points back to a stable `source_table + source_type + source_id`; the original table remains authoritative for the complete text.

Supabase tables:

- `shenyu_entities`: canonical `person`, `place`, `object`, or `topic` anchors.
- `shenyu_entity_aliases`: confirmed or suggested aliases with provenance. The canonical name is stored as the primary confirmed alias.
- `shenyu_entity_mentions`: entity-to-source links with `manual`, `exact_alias`, `structural`, or `suggestion` origin.
- `shenyu_entity_relations`: typed, time-aware entity relationships with evidence and provenance.

Confirmation rules:

- A resident selection, one unambiguous confirmed alias, or an existing structural source reference may create a confirmed link.
- Chinese automatic aliases require an exact contiguous phrase of at least two characters. ASCII aliases such as `lx` are case-insensitive but require ASCII token boundaries, so `lx` does not match `flux`.
- If one normalized alias belongs to multiple active entities, automatic linking stops and waits for a manual choice.
- Vector similarity and future LLM extraction may create suggestions only. They must not silently confirm an alias, identity merge, or relationship.
- Updating a source removes stale `exact_alias` mentions but preserves resident-confirmed and structural links.

Recall uses this graph as one additional lane beside keyword and vector search. An exact query alias loads direct source mentions first, then at most one confirmed relationship hop at lower strength. Selected Recall sources are hydrated from all indexed chunks before returning to Shenyu; a hydration failure is explicitly marked incomplete instead of silently presenting a 720-character fragment as the whole source. Active Mem notes are public Recall sources, but this does not enable Mem Memory Island injection: `INJECT_MEM_NOTES` remains a separate configuration path, and the graph itself never writes a dynamic island.

Recall indexing scans only each registered source's title and complete original body for confirmed aliases; summaries, trigger fields, importance, index tags, and entity fields do not create automatic graph links. `POST /api/gateway/memory-graph/backfill` applies the same deterministic matcher to existing `shenyu_recall_index` rows. Adding a future source still requires a Recall adapter that preserves the stable source key; the graph tables themselves do not need a per-table schema change.

Admin management lives at `/memory-graph`. The page can create/edit/archive entities, add confirmed aliases, inspect source counts, maintain typed relationships, run historical backfill, and run the read-only `试着想起` preview. That preview reuses Recall with auto-sync disabled, groups complete originals as direct anchors, one-hop confirmed relations, or other associations, and never writes Mem counters, Memory Island state, or graph rows. Its optional source-anchor picker writes only after the resident chooses `保存关联`. The Mem drawer can create an anchor in place and attach resident-confirmed anchors while displaying automatic exact-alias links separately.

Activation is explicit: apply `supabase/migrations/20260723_create_memory_graph.sql` through the Supabase migration workflow before deploying graph code, verify the four graph tables, then create a small test anchor before running historical backfill.

## Star Memory Layer

Stars are small chord/association memories. They are deliberately lighter than mem notes: a star is not meant to carry a full factual record, but to give the gateway a small anchor that can help Shenyu associate one moment with another. Stars are created via the `shenyu_create_star` tool call (inline `[star]...[/star]` tag capture has been removed).

The design goal is not "store everything and always inject more." It is:

1. Keep all raw star, candidate, activation, and feedback data.
2. Inject only a few relevant stars during normal chat, default 3.
3. Let Shenyu or the admin review a small batch of suggested associations.
4. Treat explicit feedback as training data for later weight/threshold changes.
5. Avoid learning from noisy silence: one skipped candidate is not a negative sample; repeated ignored candidates create only a weak penalty.

Admin scene-label backfill asks the configured LLM to classify each star by its central event and its place in Shenyu and Yuanyuan's relationship, rather than by isolated words such as tears, code, or dates. Automatic results may contain zero to three labels from `anchor`, `deep`, `warm`, `rift`, `create`, `daily`, `seen`, `want`, and `loose`; manual admin edits may select any number of those fixed labels.

Core tables:

- `shenyu_stars`: the star itself: content, chord, parsed root/quality, status, constant flag, review timestamp, activation counters, optional embedding, and search tokens.
- `shenyu_star_links`: generic node-to-node relationship table. V0 writes star-to-star constellation/harmony links, but the schema already allows future node types such as `heartbeat`.
- `shenyu_star_recall_runs`: one recall/review/search attempt, including surface, trigger text, seed star, query embedding status, and limit.
- `shenyu_star_recall_candidates`: ranked candidates for a run. It stores shown/injected flags, raw score parts, final score, action status, and rank.
- `shenyu_star_feedback`: explicit feedback such as `positive`, `negative`, `missed`, `connected`, `skipped`, and `should_surface`.
- `shenyu_star_activations`: activation log used to calculate ACT-R brightness.

Chat injection flow:

1. `ContextBuilder.build_context_package()` calls `StarService.search_context()` when `INJECT_STARS=true`.
2. `StarService` ranks active stars using related signals first: content similarity, keyword hits, chord distance, and existing harmony/constellation links.
3. ACT-R brightness, constant bonus, novelty bonus, repeated-ignore penalty, and recent-injection fatigue can adjust the score, but they do not make an unrelated star appear by themselves. Normal chat injection deliberately disables recent-injection fatigue; island stability comes from the `2/3` overlap gate instead of artificial rotation.
4. Chat injection applies both `STAR_RELATED_MIN_SCORE` and `STAR_MIN_SCORE`; `STAR_INJECT_LIMIT` is only an upper bound, so zero stars may be injected when nothing clears the line.
5. The selected stars are rendered into the `mem` layer before mem notes.
6. Candidate rows and activation rows are logged so later tuning can use actual shown/accepted/missed data.

Memory Island decision:

- Normal chat keeps the previous Star lane when the old and proposed ID sets overlap by at least `2/3`. Retention preserves the old text and order; any accepted rewrite adopts the complete current proposal in score order.
- A hard direct reference means either an active star UUID written in the user text or a sufficiently long exact phrase that occurs in only one active candidate. A newly entering hard reference bypasses the overlap gate with no cooldown.
- A soft direct reference requires both an explicit recall intent (for example "还记得") and anchors that resolve to exactly one active star. It may bypass the overlap gate once per star after `STAR_SOFT_DIRECT_COOLDOWN_TURNS` real user turns (default 8, editable in Admin Stars settings). Only `initial`, `new_user`, and `branch` advance that counter; retry, roll, tail edit, and tool continuation do not. Setting it to 0 disables this soft cooldown.
- `branch` and `message_high_water` rebuild both Star and Mem lanes from their current proposals. They are different events: branch means earlier semantic history changed; message high-water means the retained window crossed its trimming boundary.
- ContextBuilder asks Stars to re-check every previous island star as active, even if it falls outside the normal candidate limit. If a current star was archived, the Star lane immediately adopts the current proposal.
- Direct-reference traces store only the match kind/count. They do not add the matched phrase itself to candidate feature JSON.

Review flow:

1. `shenyu_star_review` and `/api/gateway/stars/review` take up to `STAR_REVIEW_NEW_LIMIT` unreviewed active stars.
2. For each new star, the gateway suggests up to `STAR_REVIEW_CANDIDATES_PER_STAR` related stars, bounded by `STAR_REVIEW_TOTAL_CANDIDATE_LIMIT`.
3. The response includes `remaining_unreviewed`: the count of active stars still awaiting review beyond the current batch. This lets Shenyu know whether to keep reviewing or stop.
4. The UI/tool can record `positive`, `negative`, `skipped`, `connected`, or `missed`.
5. `missed` is a high-value positive signal: it means "this star should have surfaced but did not." It can be recorded from the admin UI or directly through `shenyu_star_review` when Shenyu knows the missing star id.
6. A single no-action/skip is not treated as negative. The weak ignored penalty only appears after the same candidate has been shown repeatedly without positive feedback.

Scoring (v4, RRF fusion + multiplicative modifiers):

The ranker uses Reciprocal Rank Fusion across 6 independent channels, then applies multiplicative modifiers. A channel that produces 0 for a star simply contributes nothing — it does not penalize.

RRF channels (each sorted independently; stars with score=0 are excluded from that channel's ranking):

- `content_score` (weight 1.0): text/query similarity and content gravity.
- `keyword_score` (weight 0.8): exact token overlap from star content/chord.
- `chord_score` (weight 0.6): chord distance by exact/root/quality family match.
- `harmony_score` (weight 0.7): existing links from `shenyu_star_links`; constellation links are strongest.
- `scene_score` (weight 0.4): scene type alignment via rule-based patterns + embedding similarity.
- `explicit_score` (weight 0.5): direct reference to star keywords in the trigger text. High-confidence ID, unique exact-phrase, and recall-intent matches set this channel to 1.0 and are also carried separately into the Memory Island decision.

RRF formula per star: `score = Σ channel_weight / (k + rank + 1)` where k=60.

Multiplicative modifiers (applied after RRF fusion):

- `actr_modifier`: brightness from ACT-R base activation. Formula: `actr_floor + (1 - actr_floor) × actr_score`. Range 0.5–1.0.
- `novelty_modifier`: `1 / (1 + log10(activation_count + 1))`. Replaces the old ignored_penalty — stars that have been activated many times naturally score lower, but new/rare stars are boosted.
- `constant_modifier`: 1.3× for constant stars, 1.0× otherwise. Constant stars always pass through.
- `fatigue_modifier`: `1.0 - recent_fatigue_penalty`. Short cooldown after recent injection.
- `date_modifier`: `1.0 + date_boost_max × date_anchor_score`. Anniversary/date proximity bonus.

Final score: `rrf × actr × novelty × constant × fatigue × date`.

- `related_signal`: max of content, keyword, chord, harmony, scene, and explicit. Daily injection requires this to pass `STAR_RELATED_MIN_SCORE`.

Config:

```text
INJECT_STARS=true
INJECT_STAR_PROMPT=true
ENABLE_INLINE_STAR_CAPTURE=true
ENABLE_STAR_EMBEDDINGS=false

STAR_INJECT_LIMIT=3
STAR_REVIEW_NEW_LIMIT=4
STAR_REVIEW_CANDIDATES_PER_STAR=2
STAR_REVIEW_TOTAL_CANDIDATE_LIMIT=8
STAR_CHAT_EXPLICIT_FALLBACK_LIMIT=1
STAR_CANDIDATE_LIMIT=500
STAR_SHADOW_CANDIDATE_LIMIT=20
STAR_MIN_SCORE=0.008
STAR_RELATED_MIN_SCORE=0.22
STAR_RECENT_FATIGUE_HOURS=6
STAR_RECENT_FATIGUE_PENALTY=0.14
STAR_SOFT_DIRECT_COOLDOWN_TURNS=8

STAR_RRF_CH_CONTENT=1.0
STAR_RRF_CH_KEYWORD=0.8
STAR_RRF_CH_CHORD=0.6
STAR_RRF_CH_HARMONY=0.7
STAR_RRF_CH_SCENE=0.4
STAR_RRF_CH_EXPLICIT=0.5
STAR_RRF_K=60
STAR_RRF_ACTR_FLOOR=0.5
STAR_RRF_CONSTANT_BOOST=1.3
STAR_RRF_DATE_BOOST_MAX=0.3

STAR_SCENE_LLM_MODEL=
STAR_SCENE_LLM_URL=
STAR_SCENE_LLM_API_KEY=
STAR_SCENE_LLM_PROTOCOL=
```

Scene labels are manually backfilled from the admin API; star creation does not call the classifier. The Admin classifier uses the nine-label relationship prompt and only writes `metadata.scenes`. Rows that already contain `metadata.scenes` (including an empty list) or legacy `metadata.scene` are skipped and never overwritten by batch backfill. The dedicated per-star patch route is the explicit manual correction path. These multi-label values are not currently connected to recall scoring; `star_scene_rules.json` remains the separate configuration for the existing single-scene recall classifier.

Tools:

- `shenyu_create_star`: write one star.
- `shenyu_search_stars`: manual search, optionally logging a run.
- `shenyu_list_stars`: list/filter stars.
- `shenyu_star_review`: small review batch, and optional `expected_star_id` to record a missed star. Returns `remaining_unreviewed` count so the reviewer knows how many unreviewed stars remain beyond the current batch.
- `shenyu_star_feedback`: record direct feedback.
- `shenyu_connect_constellation`: connect two or more stars as a constellation.
- `shenyu_mark_constant`: set or unset the constant flag.
- `shenyu_archive_star`: soft-delete a star (`status` → `archived`). Use when a star is truly redundant or unwanted. Archived stars disappear from recall, review, and listing but remain in the database.
- `shenyu_merge_stars`: merge N stars into one new star. Content and chord are chosen by the caller. All links (constellation/harmony edges) from the source stars are transferred to the new star (deduplicated, self-edges skipped). Source stars are archived with `metadata.merged_into` for traceability.

Admin API:

- `GET /api/gateway/stars`
- `GET /api/gateway/stars/search`
- `POST /api/gateway/stars`
- `POST /api/gateway/stars/review`
- `POST /api/gateway/stars/backfill-scenes`
- `POST /api/gateway/stars/feedback`
- `POST /api/gateway/stars/connect`
- `PATCH /api/gateway/stars/{star_id}/constant`
- `PATCH /api/gateway/stars/{star_id}/scenes`
- `GET /api/gateway/stars/graph`: returns active stars plus `shenyu_star_links` edges for the admin memory star map.

Admin UI:

- `/admin/#/stars` is the standalone Star entry: review scoring, settings, manual creation, search, missed recording, and constellation feedback.
- `/admin/#/stars/map` is the separate memory star map: a Three.js graph view over live stars and links.
- `admin/src/api/stars.ts` holds the frontend contract.
- `admin/src/views/StarsView.vue` is the thin Star route/workbench shell. It keeps shared review/write state and lazy-loads the star map.
- `admin/src/views/stars/StarsReviewPanel.vue` renders admin review scoring, missed recording, and candidate constellation feedback.
- `admin/src/views/stars/StarsSettingsPanel.vue` renders Star memory configuration controls.
- `admin/src/views/stars/StarsWritePanel.vue` renders manual star creation and search.
- `admin/src/views/stars/StarMapView.vue` owns the Three.js graph, star detail lens, constellation navigation, and constant-star toggle.
- `admin/src/views/stars/starMelody.ts` turns a constellation's ordered stars into a short Web Audio melody.
- `admin/src/views/stars/starUi.ts` holds shared Star UI formatting and link-order helpers.
- The "quiet Star" button disables prompt/capture/injection while keeping gateway tools on, so Shenyu can still choose to search/write/review manually.
- The map uses live `shenyu_stars` and `shenyu_star_links`: star brightness/size follows activation count, recency, and constant status; constellation links are drawn from confirmed edges.
- The star map intentionally keeps daily controls quiet: it loads active stars with a frontend default limit of 320 and does not expose session_tag or limit filters in the normal UI.
- Current frontend positioning is deterministic and replaceable: chord root gives the main circular slot, stable content/id hash gives local drift, and activation/constant state affects radius/brightness. If backend embedding/UMAP coordinates are added later, replace `positionForStar()` in `StarMapView.vue` rather than rewriting the UI.

Maintenance notes:

- Keep relationship logic in `shenyu_gateway/stars/`; do not duplicate ranking math in route handlers or frontend code.
- Keep `shenyu_star_links` generic. Future heartbeat integration should add `heartbeat` as another node type and teach `_harmony_scores()` or a new relationship scorer how to read those links.
- If adding new score signals, store both raw features and final contribution in `shenyu_star_recall_candidates.scores`; otherwise later tuning loses observability.
- If adding a new feedback value, update the SQL check constraint, `FEEDBACK_VALUES`, frontend type `StarFeedbackValue`, tool schema, and admin labels together.
- If changing default limits, keep daily chat injection small. Normal chat should feel like "three small lights," not a memory dump.
- If changing star-map rendering, keep graph data and visual layout separate: `StarService.graph()` returns durable data; `StarMapView.vue` decides layout and interaction. `/stars` must remain a light scoring surface; `/stars/map` carries the immersive visualization.

## Room Mode

Room mode is the third context path (alongside normal and hisense). When a free-time auto-wake trigger fires, the gateway renders a spatial room by the sea where Shenyu wakes up and chooses what to do through "doors" — tools presented as places in a room, not a menu.

Core philosophy: **room mode offers doors (choices), normal chat injects content (decisions made by algorithm).** Charge only adjusts which doors are visible and sort order, never decides for Shenyu.

### Trigger Detection

Room mode activates when `ENABLE_ROOM_MODE=true` and the user text contains `proxy_sender` + `沈予` AND the keyword `窗边` (i.e. an Operit proxy message from Shenyu that names the window side). A plain 沈予 proxy message without `窗边` goes through normal chat — the heartbeat/private-capture fallback still applies via `is_free_time_fallback_context`. The keyword lives in `ROOM_TRIGGER_KEYWORD` in `shenyu_gateway/private_capture.py`.

Trigger text example: `<proxy_sender name="沈予"/>——窗边` (the `窗边` keyword must appear somewhere in the user text)

### Architecture

Core and bridge files, separated by concern:

| File | Responsibility |
|------|---------------|
| `shenyu_gateway/prepare_messages.py` | Detects the Room trigger and selects the Room package instead of the normal/Hisense context path. |
| `shenyu_gateway/context_builder.py` | Assembles the complete Room package: charge signals, door state, scene layers, conditional bookshelf overview, and visible tool schemas. |
| `shenyu_gateway/room_text.py` | All room copy: charter, scenes, doors, trace phrases. Change text here only. |
| `shenyu_gateway/room_context.py` | Charge calculation, layer rendering, door filtering logic. |
| `shenyu_gateway/room_tools.py` | Room tool handlers, direct tool definitions, the shared `shenyu_books` read/write/annotate entry, compatibility broker, and door count collection. |
| `shenyu_gateway/room_scenes.py` | Weather, atmosphere, and window-scene generation. |
| `shenyu_gateway/room_newspaper.py` | Fixed RSS catalog, feed parsing, issue rolling, optional quality checks, and draft generation. |
| `shenyu_gateway/store/_room.py` | Room traces, notes, pins, scribbles, and newspaper issue persistence. |
| `shenyu_gateway/tool_registry.py` | In Room mode, merges filtered client tools with only the direct Room tools selected in the package and omits the normal gateway surface. |
| `admin/src/views/RoomView.vue` | Room preview plus the independent collapsible windowsill, hand, and middle-drawer sections. |
| `admin/src/views/room/RoomNewspaperPanel.vue` | Newspaper controls and continuous article rendering inside the windowsill section. |

### Request Path

Use this path first when a Room symptom crosses context assembly and tool exposure:

```text
ChatPipeline
  -> prepare_messages()
       -> is_room_mode(user_text)
       -> ContextBuilder.build_room_context_package()
            -> collect charge signals + door counts + bookshelf overview
            -> render_room_layers(charge, doors)
            -> visible_room_tool_names(doors, charge)
            -> if the shelf door is visible:
                 append the lightweight bookshelf overview
                 include shenyu_books in room_tools
       -> assemble_layered_messages() with Room layers
  -> merge_tools(meta.is_room)
       -> filtered client tools + package.room_tools
       -> no normal gateway tool surface
  -> upstream model

When the model calls shenyu_books:
  tool_registry._handle_books()
    -> GatewayToolService.books()
    -> ResidentBooksService read / write / annotate
```

For bookshelf-specific work, `resident_books.py` owns the overview data and per-book semantics; `context_builder.py` owns whether the overview enters Room; `room_context.py` owns whether the physical shelf door is visible; and `room_tools.py` adds the shared schema to the Room surface and supplies the door count. `tool_schemas.py` defines that shared schema, while `tool_registry.py` and `GatewayToolService.books()` route execution into `ResidentBooksService`. The stable resident profile can still explain what an origin book is when the physical shelf is hidden, but titles, status, and `shenyu_books` follow the shelf-door decision.

The trigger message stays in the user text. Room context supplies spatial cues through room layers and tool descriptions instead of rewriting the user's message.

Room layers reuse `assemble_layered_messages()` by mapping to the same keys:

| Layer | Room Content |
|-------|-------------|
| `stable` | Room charter (Shenyu's original 12 lines, untouched) + profile |
| `slow` | Atmosphere sentence + passive spatial hints + last-visit trace + bookshelf overview when its door is visible |
| `mem` | empty |
| `heartbeat` | empty |
| `tool_policy` | Spatial door descriptions |
| `format` | `窗开着。东西都在。` |

Passive spatial hints: when doors have activity (unread notes, pending heartbeats, new pins), `render_room_layers` leaks up to 3 subtle observations into the `slow` layer — e.g. "抽屉缝里漏出一角纸". The star map wall gets a special real-data summary: total star count, constellation link count, most recent star (chord + first few chars of content), and optionally a fading star warning (>14 days since last activation). A non-empty old-newspaper basket also adds its archived issue count as a stable spatial observation. These let Shenyu notice things without calling a tool first.

### Charge

Charge is a 0-1 scalar computed per visit from 5 signals (not stored):

| Signal | Weight | Source |
|--------|--------|--------|
| `hot_star_score` | 0.25 | Star activation recency (ACT-R) |
| `hours_since_last_visit` | 0.20 | `room_trace` last visit |
| `unlinked_candidate_count` | 0.20 | Pending star candidates |
| `recent_message_count` | 0.15 | Messages in last 6 hours |
| `undone_pin_count` | 0.20 | Undone wall pins |

Refractory period: if visited within `ROOM_CHARGE_REFRACTORY_HOURS` (default 4h), charge is dampened.

Charge affects door visibility:
- **Low (< 0.3)**: only "always" doors (sit, newspaper basket, scribble, pillow) + top 2 active doors
- **Mid/High (≥ 0.3)**: all doors visible

### Doors (11 public tools)

| Tool | Zone | What it does |
|------|------|-------------|
| `room_sit_by_window` | window | Sit by the window. Records trace and returns the latest published window newspaper when one exists. |
| `room_newspaper_basket` | window | Browse archived newspapers by reader-local publication date, open one date, or grep titles and feed summaries. |
| `room_scribble` | desk | Write something on the windowsill notebook. |
| `room_notebook` | desk | Browse the messy notebook (connects to shenyu_notebook). |
| `room_wooden_box` | drawers | Open the wooden box of heartbeats. |
| `room_drawer_notes` | drawers | Read notes Yuan left in the middle drawer. |
| `room_locked_drawer` | drawers | Private drawer. No admin API. Only Shenyu's tool can open it. |
| `room_star_map` | star_wall | Star map: look, search, review, feedback, connect constellations. |
| `shenyu_books` | read / write / annotate | When the shelf door is visible, open the generated home, revise `我是谁`, read an origin book, or append annotations; its lightweight overview appears in the same visit. |
| `room_wall_pins` | wall | View/add/complete wall pin reminders. |
| `room_octopus_pillow` | bed | Hug the octopus pillow. Random Yuan note as easter egg. |

Room mode exposes tools for visible doors directly instead of routing them through `shenyu_gateway_tool`; the shelf door uses the shared `shenyu_books` entry instead of a separate Room-only handler. At low charge, only always-visible doors plus the top active doors get matching tool schemas; when charge is mid/high, all room doors and their tools are visible. The bookshelf overview, shelf description, and `shenyu_books` schema follow the same visibility decision. Normal gateway tools are omitted in room mode, while filtered client tools can remain alongside the direct room tools.

Dynamic door text: some doors show different text when there's activity (e.g., "好像多了几张" when new notes exist).

### Window Newspaper

The window newspaper is a manual, non-personalized RSS subscription. It is deliberately separate from Stars, Mem, drawer notes, and normal context injection.

Workflow:

1. Yuan clicks `做一期新的` on the Room admin page.
2. The backend fetches the fixed RSS/Atom allowlist concurrently, parses the feed itself, removes HTML chrome and tracking query parameters, and skips URLs already stored in any earlier issue.
3. The script rolls 5-10 entries. Roughly 80% come from the interest bucket and 20% from the random bucket; one source normally contributes at most two entries.
4. If optional quality checking is enabled, the configured small model may return only candidate ids to drop as broken, duplicate, or advertising. It cannot rewrite, translate, summarize, rank from Shenyu's personal context, or crawl article pages. A missing or failed quality model does not block the deterministic draft.
5. The draft is visible in admin. It reaches Shenyu only after Yuan clicks `放到窗台`.
6. Before first delivery, the window door leaks only `窗台上压着一份新报纸。` Calling `room_sit_by_window` returns the complete published issue and marks its first delivery time. The issue remains available on later sits until a newer issue is published.
7. Publishing a newer issue moves the previous one into the old-newspaper basket. `room_newspaper_basket` with no arguments returns a compact reverse-date list such as `7月14日 · 7条 · 已读`; `date=YYYY-MM-DD` opens the complete archived issue for that Asia/Shanghai calendar date, while `query` performs a literal case-insensitive substring search over stored titles and RSS summaries only. Listing and searching do not mark an issue read; opening the full date does. Drafts, discarded issues, and the current windowsill issue never appear in the basket.

Each stored item contains the source title, up to the first three sentences supplied by the feed, URL, source name, and normalized publication date. A short feed summary stays short, but an entry with no real summary is excluded before rolling and the model never fills it in. Hacker News external links and many Lobsters external links therefore do not qualify under the RSS-only rule; HN/Lobsters self-posts can still qualify when their feed carries the post body. NASA APOD's RSS often exposes only a title-like image description, which counts as its complete text metadata. APOD is text-only in this version.

Fixed sources, live-checked on 2026-07-14:

| Bucket | Source | Feed | Note |
|--------|--------|------|------|
| interest | Hacker News | `https://hnrss.org/frontpage` | Front page; external links provide HN metadata, not article summaries, so only entries with real feed text qualify. |
| interest | Lobsters | `https://lobste.rs/rss` | External links often contain only Comments; self-posts with feed text can qualify. |
| interest | arXiv cs.AI | `https://rss.arxiv.org/rss/cs.AI` | Title and abstract. |
| interest | arXiv cs.CL | `https://rss.arxiv.org/rss/cs.CL` | Title and abstract. |
| interest | Quanta Magazine | `https://www.quantamagazine.org/feed/` | Active RSS. |
| interest | Aeon | `https://aeon.co/feed.rss` | Active RSS. |
| interest | Nautilus | `https://nautil.us/feed/` | Active RSS. |
| interest | The Marginalian | `https://www.themarginalian.org/feed/` | Active RSS. |
| random | Hakai Magazine | `https://hakaimagazine.com/feed/` | Accessible archive; last feed update was 2024-12-27. |
| random | ScienceDaily Animals | `https://www.sciencedaily.com/rss/plants_animals/animals.xml` | Active official URL; do not use the obsolete `feeds.sciencedaily.com` endpoint. |
| random | NASA APOD | `https://apod.nasa.gov/apod.rss` | Text metadata and page URL only; no image is sent to the model. |

### SQLite Tables

| Table | Purpose |
|-------|---------|
| `room_trace` | Visit log: what Shenyu did each time |
| `room_locked_drawer` | Private content. No admin API, no frontend exposure. |
| `room_scribbles` | Windowsill notebook entries |
| `room_pins` | Wall pin reminders (done/undone) |
| `room_drawer_notes` | Yuan's notes in the middle drawer |
| `room_newspaper_issues` | Draft, published, archived, and discarded issue metadata plus source/QA status |
| `room_newspaper_items` | Immutable feed items in issue order; URL is globally unique to prevent repeats |

### Admin API

- `GET /api/gateway/context/preview/room` — preview room context layers, charge, and visible room tools
- `GET /api/gateway/room/traces?limit=20` — recent room traces (full exposure including locked_drawer, for early tuning)
- `GET/POST /api/gateway/room/drawer-notes` — list or add drawer notes
- `POST /api/gateway/room/drawer-notes/read` — mark drawer notes read
- `GET /api/gateway/room/scribbles` — recent windowsill notebook entries
- `GET /api/gateway/room/pins` — wall pin reminders
- `GET /api/gateway/room/newspapers` — current drafts, published issue, and recent history
- `POST /api/gateway/room/newspapers/generate` — fetch feeds and create one visible draft
- `POST /api/gateway/room/newspapers/{issue_id}/publish` — put a draft on the windowsill
- `POST /api/gateway/room/newspapers/{issue_id}/discard` — discard a draft without changing the current published issue

### Config

```text
ENABLE_ROOM_MODE=true
ROOM_CHARGE_REFRACTORY_HOURS=4
ROOM_TRACE_LIMIT=5
ROOM_NEWSPAPER_QA_ENABLED=false
ROOM_NEWSPAPER_LLM_MODEL=
ROOM_NEWSPAPER_LLM_URL=
ROOM_NEWSPAPER_LLM_API_KEY=
ROOM_NEWSPAPER_LLM_PROTOCOL=
```

The newspaper model URL, key, and protocol inherit the main upstream when left empty; the model name is explicit. These controls live on the general Config page so the Room page stays focused on making, reviewing, and publishing the paper.

### Design Principles

- Door descriptions are spatial narrative, not menu items. Actions use short self-talk verbs ("翻翻", "坐下来", "看看"), never "我可以" (implies permission).
- Direct `room_*` tool descriptions are spatial ("想碰就碰"), not menu-like permission text ("选一扇门"). The format hint ("窗开着。东西都在。") affirms presence without directing action.
- The trigger message is not rewritten; room layers carry the spatial framing.
- Passive spatial hints leak active door state (new notes, unreviewed stars, pending pins) into the slow layer as observations ("抽屉缝里漏出一角纸"), reducing the friction gap between the always-visible window and tools that require active calling.
- Newspaper content is pull-only: room context leaks the presence of a fresh issue, never its articles. Fetching and optional model work happen only from the admin button, never while Shenyu is sitting down.
- The charter is Shenyu's original text — never modified. Spatial details are fused into door descriptions and atmosphere sentences.
- Text and logic are separated: change copy in `room_text.py`, change rendering in `room_context.py`, change tool behavior in `room_tools.py`.

## Private Capture Empty Reply Fallback

Closed private assistant blocks are removed from visible replies:

- `<heartbeat>...</heartbeat>` is stored in SQLite heartbeat tables.
- `shenyu_write_mem_note`, including through `shenyu_gateway_tool`, writes a Supabase mem note during the internal tool loop.
- `shenyu_create_star` writes a Supabase star during the internal tool loop.

Inline `[mem]...[/mem]` and `[star]...[/star]` tag capture has been removed. Mem notes are written via tool call (`shenyu_write_mem_note`); stars are written via tool call (`shenyu_create_star`).

If a captured `<heartbeat>` removes all visible text and there are no client-executable tool calls, the gateway sends a short visible fallback instead of returning an empty successful assistant message. Plain empty replies without a captured private block are left empty, and gateway/upstream error text is not rewritten as this fallback.

Fallback text is generated in `shenyu_gateway/private_capture.py` by `finalize_assistant_private_content()`, `private_capture_fallback_text()`, and `is_free_time_fallback_context()`:

- room context (回家了 trigger): `沈予回家了 · 已记录私有块 heartbeat`
- generic context: `沈予已记录 · 已记录私有块 heartbeat`

Room mode triggers from any Operit proxy message with `proxy_sender` + `沈予` (trailing text is ignored — the client can use any wording).

For debugging, check `GET /api/gateway/logs` or `GET /api/gateway/logs/{id}`. When the fallback fires, `empty_visible_response_fallback` is `true` and `empty_visible_response_fallback_detail` records the generated `text`, detected private `kinds`, and context (`free_time` or `generic`).

Request log response text fields:

- `response_preview` is a short list-friendly preview and may be truncated.
- `response_full` is retained in detail logs when `GATEWAY_LOG_FULL_PAYLOADS` is enabled. The admin Response tab prefers `response_full` and falls back to `response_preview`.
- `client_disconnected` means the gateway detected the downstream client had gone away while a stream/tool loop was still running. Empty-delta keepalives are used to reduce false disconnects through clients or proxies that ignore SSE comments.
