-- L0 verbatim chat archive: the durable source of truth for what was actually
-- said, message by message. Indexes (recall) and books (conflict books) are
-- derived from this; this table itself must never depend on index strategy.
-- Messages are archived from the client window on the next request, so
-- re-rolled assistant replies (which never reappear in the window) are
-- naturally excluded.

create table if not exists shenyu_chat_archive (
  id uuid primary key default gen_random_uuid(),
  session_tag text not null,
  thread text not null,
  client_name text,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  content_hash text not null,
  event_at timestamptz,
  archived_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists idx_shenyu_chat_archive_thread_event
  on shenyu_chat_archive (thread, event_at desc);

create index if not exists idx_shenyu_chat_archive_tag_hash
  on shenyu_chat_archive (session_tag, content_hash);

create index if not exists idx_shenyu_chat_archive_alive
  on shenyu_chat_archive (thread, event_at desc)
  where deleted_at is null;
