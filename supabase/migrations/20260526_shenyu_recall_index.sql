create extension if not exists vector;
create extension if not exists pg_trgm;

create table if not exists public.shenyu_recall_index (
  id uuid primary key default gen_random_uuid(),

  source_table text not null,
  source_id text not null,
  source_type text not null,
  chunk_index integer not null default 0,

  session_tag text,
  title text not null default '',
  body text not null default '',
  excerpt text not null default '',
  search_text text not null default '',
  search_tokens text[] not null default '{}',

  embedding_text text not null default '',
  embedding vector(1024),
  embedding_model text,
  embedding_status text not null default 'pending',
  embedding_error text,
  embedded_at timestamptz,

  tags_json jsonb not null default '[]'::jsonb,
  entities_json jsonb not null default '[]'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,

  event_date timestamptz,
  source_created_at timestamptz,
  source_updated_at timestamptz,

  status text,
  visibility text,
  importance double precision not null default 0.5,

  content_hash text not null,
  indexed_at timestamptz not null default now(),
  deleted_at timestamptz,

  constraint shenyu_recall_index_source_chunk_uniq
    unique (source_table, source_id, chunk_index)
);

create index if not exists shenyu_recall_index_source_idx
  on public.shenyu_recall_index (source_type, status, event_date desc);

create index if not exists shenyu_recall_index_session_idx
  on public.shenyu_recall_index (session_tag);

create index if not exists shenyu_recall_index_updated_idx
  on public.shenyu_recall_index (source_updated_at desc);

create index if not exists shenyu_recall_index_deleted_idx
  on public.shenyu_recall_index (deleted_at);

create index if not exists shenyu_recall_index_tokens_gin_idx
  on public.shenyu_recall_index using gin (search_tokens);

create index if not exists shenyu_recall_index_tags_gin_idx
  on public.shenyu_recall_index using gin (tags_json);

create index if not exists shenyu_recall_index_entities_gin_idx
  on public.shenyu_recall_index using gin (entities_json);

create index if not exists shenyu_recall_index_search_trgm_idx
  on public.shenyu_recall_index using gin (search_text gin_trgm_ops);

create or replace function public.set_shenyu_recall_index_indexed_at()
returns trigger
language plpgsql
as $$
begin
  new.indexed_at = now();
  return new;
end;
$$;

drop trigger if exists trg_shenyu_recall_index_indexed_at
  on public.shenyu_recall_index;

create trigger trg_shenyu_recall_index_indexed_at
before update on public.shenyu_recall_index
for each row
execute function public.set_shenyu_recall_index_indexed_at();
