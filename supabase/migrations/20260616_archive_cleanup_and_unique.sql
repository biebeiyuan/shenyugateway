-- Clean up 2020 duplicate rows from backfill pass-2 (raw_request_windows).
-- These duplicates share a telltale fallback event_at and batch archived_at;
-- the good copies (from pass-1 gateway_messages) have accurate per-message
-- timestamps. Soft-delete the bad copies, then document an optional partial
-- unique index for deployments that prefer rejecting exact duplicate imports.
--
-- Verified on 2026-06-16 after cleanup:
--   active rows: 4866
--   soft-deleted rows from this bad fallback batch: 2020
--   active duplicate (session_tag, content_hash) keys: 0
--   bad fallback batch active rows: 0
--
-- Preflight before adding any uniqueness guard:
-- SELECT session_tag, content_hash, count(*) AS duplicate_count
-- FROM shenyu_chat_archive
-- WHERE deleted_at IS NULL
-- GROUP BY session_tag, content_hash
-- HAVING count(*) > 1;

-- Step 1: soft-delete backfill duplicates
UPDATE shenyu_chat_archive
SET deleted_at = now()
WHERE deleted_at IS NULL
  AND event_at = '2026-06-09T12:46:26.595526+00:00'
  AND archived_at = '2026-06-14T10:01:00.074115+00:00'
  AND content_hash IN (
    SELECT content_hash FROM shenyu_chat_archive
    WHERE deleted_at IS NULL
      AND NOT (event_at = '2026-06-09T12:46:26.595526+00:00'
               AND archived_at = '2026-06-14T10:01:00.074115+00:00')
  );

-- Step 2 (optional): prevent future exact duplicates per session.
-- Important: content_hash is role + exact message text. This index prevents
-- accidental duplicate imports, but it also prevents archiving a genuinely
-- repeated identical line in the same session_tag later. Leave commented unless
-- that tradeoff is acceptable.
--
-- CREATE UNIQUE INDEX IF NOT EXISTS idx_shenyu_chat_archive_unique_content
--   ON shenyu_chat_archive (session_tag, content_hash)
--   WHERE deleted_at IS NULL;
