# Supabase Egress And Recall Worker Observation (2026-08-15)

## Status

Implemented locally, pending normal GitHub deployment and a 48-hour production observation. This is a historical investigation and handoff note, not a live billing dashboard.

## Confirmed Baseline

- The configured production worker interval was 900 seconds. The running container explicitly set `RECALL_SYNC_WORKER_INTERVAL_SECONDS=900`, so changing only the Python default would not have changed production behavior.
- The Recall worker rebuilds source adapters every interval. It reads source rows, upserts Recall index rows, and runs Memory Graph reconciliation.
- At the investigation snapshot, 631 active Recall index rows all had embeddings. Their aggregate serialized full-row JSON size was 13,403,178 bytes.
- A single current-minute update bucket contained 555 Recall index rows. PostgreSQL reported 1,689,360 updates for this table since its statistics reset on 2026-02-12.
- The prior client used `return=representation` for background upserts. A worker cycle could therefore receive full persisted Recall rows, including embeddings, even when its caller discarded the response.

## Change

`SupabaseClient.upsert_minimal()` sends `resolution=merge-duplicates,return=minimal`.

- Recall index rebuild upserts use it.
- Memory Graph batch mention upserts use it.
- Heartbeat archive upserts use it.
- User-facing and callers that need created or updated rows keep the existing representation-returning methods.

The worker interval remains 900 seconds. This preserves freshness and avoids a direct Coolify change. The expected saving is the removed mutation-response payload, not a behavior change to recall selection.

## Expected Effect

The latest observed 555-row batch was approximately 11.2 MiB when scaled from the full Recall index row representation. At 96 cycles per day, that response path alone could be about 1.05 GiB/day of uncompressed JSON before HTTP compression. `return=minimal` should remove that response body.

Source-table full reads and Memory Graph reads still exist. They are the next investigation target only if the billing trend remains high after this change.

## Observation Plan

1. After the GitHub deployment, confirm the running version contains this change through the normal deploy evidence. Do not change the Coolify worker interval for this observation.
2. After at least two worker cycles, query aggregate-only Recall index statistics. `indexed_at` may still advance, while the gateway should no longer receive row representations for the background upserts.
3. Compare Dashboard Billing -> Usage -> Egress over two complete post-deploy days against the pre-deploy daily baseline. Record actual provider GB separately from the raw JSON estimate in this note or the delivery log.
4. Inspect gateway logs for `RecallIndexWorker` cycle summaries only. Do not enable full payload logging or inspect private source content for this check.
5. If Egress remains materially high, measure the source-table `select=*` responses and redesign rebuild as a true incremental sync. Do not combine that semantic change with this response-suppression fix.

## Rollback

Reverting this code restores representation-returning background upserts. No data migration, deletion, table change, or worker configuration change is involved.
