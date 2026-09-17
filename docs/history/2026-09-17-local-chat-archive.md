# Local chat archive: approved boundary and implementation record

**Goal:** Move chat-original browsing and literal search to VPS-local SQLite without changing what 沈予 receives.
**Base:** master 01e08f57d55cc3921558ab123a4660fb8fa8dad0. Work only on work/local-chat-archive; master auto-deploys.
**Approval:** Owner approved storage/search migration and explicitly excluded changing the history source for model requests.

## Non-negotiable boundary

Keep client wire history, trimming, cold-start bridges, session identity, Memory Island, Stars/Mem/Recall, tool execution, private capture, and provider payloads unchanged. No historical-text rewriting. No production mutation, migration, or master push in this work session. Supabase remains the source for all non-chat-archive content, including frozen origin books. The archive must not become a model-context source.

## First delivery

1. Independent SQLite archive file beside the runtime database; no dependency on gateway_sessions, no pruning by runtime retention. Existing archive IDs, text, timestamps, hashes and tombstones are preserved exactly.
2. Keep /api/archive/days, /messages, /search and archive-only soft deletion contracts. SQL pagination filters before LIMIT and uses the existing opaque composite cursor. All sessions remain one timeline; every row keeps its source session.
3. Deployment-only CHAT_ARCHIVE_BACKEND=supabase|sqlite; supabase remains default. CHAT_ARCHIVE_DB_PATH overrides the sibling file path. The sqlite setting requires an already initialized/imported archive, never silently opens a blank archive. No Admin toggle: storage cutover is a migration, not a live preference.
4. Import/export/verify/backup command. Dry runs are read-only. Imports are idempotent by original row ID and reject changed immutable originals; no content-hash global cleanup. A source-consistent final export and explicit import verification are required before cutover. Plain backups are private files, not an encrypted or scheduled computer-backup solution.
5. For this first delivery, preserve the existing input-window capture and legacy dedup semantics when changing its destination. Do not claim per-message identity, immediate terminal-reply capture, or PWA switching has been fixed yet.

## Test sequence

- Baseline: `python -m pytest tests/ -x -q`: 1134 passed.
- Write failing local archive tests, including import conflicts/atomicity, tombstones, exact Unicode/short Chinese literal matching, A/B/A provenance, same-time pagination, runtime-prune isolation, and backup/restore.
- Implement storage and CLI; run the tests.
- Write failing backend contract tests; integrate only archive routing/writing; rerun existing archive and full Python suites.
- Confirm context/provider/PWA request files are byte-identical to the base. Run project-map, resident-home, encoding, and diff checks. Remove the temporary source-snapshot workflow before handoff.

## Subsequent work (not included in this first delivery)

Message identities must be carried out-of-band and excluded from upstream payloads before replacing legacy text dedup. Final visible replies need durable capture with correct Roll/edit selection. Any PWA switch repair must preserve the model-facing history contract and be independently replay-tested. Never roll back a sqlite-only writer to cloud-only reads without reconciling the locally written tail. Computer-side pull scheduling/encryption and real VPS volume/recovery verification remain deployment work.

## Verification recorded for the first delivery

- Local full Python suite: **1168 passed** (1134 existing + 34 new). New behavior was tested red before implementation; failure-isolation regression was likewise reproduced before its fix.
- Project/owner maps and config-default checks: 29 passed. Python compilation and `git diff --check` passed.
- Real preparation/window/layer code was replayed against both archive backends for a short and a trimmed window; prepared messages, snapshots, cache layers and history events matched. External memory responses were fixed test fixtures, not live resident data.
- PWA source, history/wire logic, preparation, context/window, provider, Stars and Mem source files are unchanged from the reviewed base. This is evidence for storage-only scope, not a claim of identical model-generated replies.
- Origin-book shared router was reviewed for no resident impact; original-text freezing and annotation behavior still use Supabase.
- No VPS login, data import, cloud deletion, production backend switch, encryption/scheduling or device-side check was performed. Frontend build/smoke verification is left to the repository CI on the draft PR.

## Review follow-up (storage only; identity work remains pending)

The owner supplied eight review points. Reproduced the full-window scan and limit drift; removed the reintroduced transfer-only workflow from the final tree. The earlier PR description had not been updated after the workflow was reintroduced for the next task. No dependency-packaging workflow belongs in the merge result.

- `archive_visible` originally ranked all live rows before date/LIMIT filtering. The public reader now uses an indexed correlated earlier-copy selection with the same representative rows. Existing v1 database files remain readable without mutation of originals or their stored view. A cursor must not resurrect a folded sibling; regressions cover that invariant and real SQLite VM-step budgets.
- A C-level literal fragment prefilter reduces Python regex callbacks for Chinese/punctuation queries. The suggested blind `LIKE` prefilter was not adopted because it loses valid Unicode case-insensitive matches. `instr` on an uncased fragment is conservative; pure cased queries still use regex without prefilter. Search remains potentially linear, not fully indexed full-text search.
- Cold WAL reopen succeeds in a fresh local process after a clean writer exit and absent sidecars, with a writable directory. Completed backups additionally use `DELETE` journal mode; an unprivileged process opened one on a non-writable directory with no sidecars. This is local evidence, NOT a VPS cold-start result.
- Archive configuration fields were already absent from the POST request schema; a real HTTP regression now proves no mutation or persisted override. Found and blocked an indirect switch through `gateway_db_path` when the archive path follows the runtime file. In-flight destination changes now fail symmetrically instead of silently writing the previously selected cloud backend.
- Search limits now match cloud (200 maximum; zero becomes one). Local exact calendar counts intentionally have no cloud 10,000-row fetch ceiling. Migration proof compares original rows, not UI counts.
- `verify` is explicitly frozen-snapshot/cutover proof and must fail after additions/deletions compared to an old export. It is not a health probe. Runtime inspection/backup recovery use separate checks.
- Python was already >=3.12. Added a linked SQLite >=3.30.0 build/runtime guard and explicit manual transactions. Import rejects unsafe cursor IDs atomically; UUIDs are unaffected.
- Additional deployment defect: Docker omitted the new archive CLI. The image now copies it, with a regression preventing another omission.

### Reproducible synthetic measurement

Run `python -m tests.archive_read_benchmark --rows 20861 100000`. The harness creates a disposable database only, no credentials or real chat text; about 0.8 KB text per row over one year, 10% legacy duplicate copies, median of three warm queries with instruction counting. It captures the replacement SQL from the real public methods and asserts results equal the old window query. Local environment: Python 3.13.5, SQLite 3.46.1. These numbers are not VPS latencies or promised speedups.

| Synthetic rows | Query | Old median ms | New median ms | Python callbacks old → new |
|---|---|---:|---:|---:|
| 20,861 | Month days | 38.308 | 1.522 | 0 → 0 |
| 20,861 | Latest 60 | 83.951 | 0.171 | 0 → 0 |
| 20,861 | Literal 沈予 | 72.681 | 18.082 | 18,775 → 42 |
| 100,000 | Month days | 192.239 | 8.251 | 0 → 0 |
| 100,000 | Latest 60 | 401.144 | 0.172 | 0 → 0 |
| 100,000 | Literal 沈予 | 300.340 | 30.689 | 90,000 → 68 |

Old EXPLAIN: `SCAN archive_messages USING INDEX archive_fold` plus window co-routines and a temporary B-tree for outer GROUP BY/ORDER BY. New month EXPLAIN: `SEARCH current USING INDEX archive_day (event_day>? AND event_day<?)` plus correlated `SEARCH earlier USING INDEX archive_fold`. New latest/search EXPLAIN: `SCAN current USING INDEX archive_time` plus that fold lookup, no temporary ORDER BY tree. The word SCAN in this ordered index plan does not mean the entire index is consumed: the LIMIT stops the latest-page read early; measured VM-step tests guard this.

### Review verification and remaining boundary

Local full Python suite: **1194 passed** (26 new review cases over 1168). New behavior was first reproduced failing; characterization tests also confirmed the already-correct POST field exclusion, WAL writable-directory cold start, snapshot verification, and atomic invalid-ID rejection. Model preparation, client wire history, PWA/source, providers, Stars/Mem and recovery code are unchanged by this review. The pending message-ID/reply-completion/recovery work is still pending; never mark it finished based on these storage tests. Actual VPS version/permissions, real source migration, deployment, and device verification were not performed.
