-- Living books for resident-authored identity and current-home documents.
-- Origin books remain in shenyu_conflict_books; this table is the new facade's
-- editable side and keeps every body revision before updating the current row.

create extension if not exists pgcrypto;

create table if not exists shenyu_books (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  title text not null,
  kind text not null default 'living' check (kind = 'living'),
  status text not null default 'active' check (status in ('active', 'archived')),
  body text not null default '',
  revision integer not null default 0 check (revision >= 0),
  updated_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists shenyu_book_revisions (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null references shenyu_books(id),
  revision integer not null check (revision > 0),
  body text not null,
  summary text not null default '',
  actor text not null default '',
  created_at timestamptz not null default now(),
  unique (book_id, revision)
);

create index if not exists idx_shenyu_book_revisions_book
  on shenyu_book_revisions (book_id, revision desc);

create table if not exists shenyu_book_annotations (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null references shenyu_books(id),
  target_revision integer not null default 0,
  content text not null,
  actor text not null default '',
  created_at timestamptz not null default now(),
  constraint shenyu_book_annotations_content_not_blank check (btrim(content) <> '')
);

create index if not exists idx_shenyu_book_annotations_book
  on shenyu_book_annotations (book_id, created_at asc);

insert into shenyu_books (slug, title, kind)
values ('identity', '我是谁', 'living'), ('home', '家现在', 'living')
on conflict (slug) do nothing;
