-- Durable backup of SQLite heartbeat pools (heartbeat_entries / hisense_heartbeat).
-- SQLite stays the live read path; this table is the disaster-recovery copy.
-- Rows are upserted by the gateway worker after a settle window, so manual
-- cleanup done in SQLite before settling never reaches the archive.
-- Rows removed from SQLite after archiving are soft-deleted here, never erased.

create table if not exists shenyu_heartbeat_archive (
  id text primary key,
  scope text not null check (scope in ('normal', 'hisense')),
  session_id text,
  content text not null,
  turn_number integer not null default 0,
  created_at timestamptz,
  archived_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists idx_shenyu_heartbeat_archive_scope_created
  on shenyu_heartbeat_archive (scope, created_at desc);

create index if not exists idx_shenyu_heartbeat_archive_alive
  on shenyu_heartbeat_archive (scope)
  where deleted_at is null;
