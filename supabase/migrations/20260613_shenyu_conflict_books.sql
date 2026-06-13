-- Conflict books ("矛盾书"): frozen verbatim excerpts of arguments, curated by
-- the user, readable and annotatable by Shenyu.
--
-- Invariants enforced by gateway code (no API path may violate them):
--   * original_text is frozen at clip time and never updated afterwards.
--   * annotations are append-only with timestamps; no update or delete is exposed.
--   * reads are logged append-only so "翻过几次、什么时候翻的" is visible.

create table if not exists shenyu_conflict_books (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  thread text,
  span_start timestamptz,
  span_end timestamptz,
  message_refs jsonb not null default '[]'::jsonb,
  original_text text not null,
  epilogue text,
  user_notes text,
  status text not null default 'open' check (status in ('open', 'settled')),
  read_count integer not null default 0,
  last_read_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  deleted_at timestamptz
);

create index if not exists idx_shenyu_conflict_books_alive
  on shenyu_conflict_books (created_at desc)
  where deleted_at is null;

create table if not exists shenyu_conflict_annotations (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null references shenyu_conflict_books(id),
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_shenyu_conflict_annotations_book
  on shenyu_conflict_annotations (book_id, created_at asc);

create table if not exists shenyu_conflict_reads (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null references shenyu_conflict_books(id),
  read_at timestamptz not null default now()
);

create index if not exists idx_shenyu_conflict_reads_book
  on shenyu_conflict_reads (book_id, read_at desc);
