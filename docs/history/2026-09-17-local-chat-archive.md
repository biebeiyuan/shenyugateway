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
