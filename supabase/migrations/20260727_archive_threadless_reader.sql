-- The archive reader now shows one merged timeline (thread is provenance
-- only), so day/message queries filter by event_at without a thread prefix.
-- Optional at current table size; keeps the alive-rows scan index-backed.

create index if not exists idx_shenyu_chat_archive_event_alive
  on shenyu_chat_archive (event_at desc)
  where deleted_at is null;

-- Reader-side twin folding also wants hash lookups without session_tag.
create index if not exists idx_shenyu_chat_archive_hash
  on shenyu_chat_archive (content_hash);
