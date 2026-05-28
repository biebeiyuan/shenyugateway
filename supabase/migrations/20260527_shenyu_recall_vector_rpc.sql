create extension if not exists vector;

create or replace function public.match_shenyu_recall_index(
  query_embedding vector(1024),
  match_count integer default 40,
  source_types text[] default null
)
returns table (
  id uuid,
  source_table text,
  source_id text,
  source_type text,
  chunk_index integer,
  session_tag text,
  title text,
  body text,
  excerpt text,
  search_text text,
  search_tokens text[],
  tags_json jsonb,
  entities_json jsonb,
  metadata_json jsonb,
  event_date timestamptz,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  status text,
  visibility text,
  importance double precision,
  vector_score double precision
)
language sql
stable
as $$
  with args as (
    select greatest(1, least(coalesce(match_count, 40), 100)) as wanted
  ),
  matched as (
    select
      sri.source_table,
      sri.source_id,
      sri.chunk_index,
      greatest(0, 1 - (sri.embedding <=> query_embedding)) as vector_score
    from public.shenyu_recall_index sri
    cross join args
    where sri.deleted_at is null
      and sri.embedding is not null
      and sri.embedding_status = 'ready'
      and (source_types is null or cardinality(source_types) = 0 or sri.source_type = any(source_types))
    order by sri.embedding <=> query_embedding
    limit (select wanted from args)
  ),
  source_keys as (
    select source_table, source_id, max(vector_score) as source_vector_score
    from matched
    group by source_table, source_id
  )
  select
    sri.id,
    sri.source_table,
    sri.source_id,
    sri.source_type,
    sri.chunk_index,
    sri.session_tag,
    sri.title,
    sri.body,
    sri.excerpt,
    sri.search_text,
    sri.search_tokens,
    sri.tags_json,
    sri.entities_json,
    sri.metadata_json,
    sri.event_date,
    sri.source_created_at,
    sri.source_updated_at,
    sri.status,
    sri.visibility,
    sri.importance,
    coalesce(m.vector_score, 0.0) as vector_score
  from public.shenyu_recall_index sri
  join source_keys sk
    on sk.source_table = sri.source_table
   and sk.source_id = sri.source_id
  left join matched m
    on m.source_table = sri.source_table
   and m.source_id = sri.source_id
   and m.chunk_index = sri.chunk_index
  where sri.deleted_at is null
  order by sk.source_vector_score desc, coalesce(m.vector_score, 0.0) desc, sri.chunk_index asc;
$$;

-- Add this later if the recall index grows large enough to need approximate vector search:
-- create index if not exists shenyu_recall_index_embedding_hnsw_idx
--   on public.shenyu_recall_index
--   using hnsw (embedding vector_cosine_ops)
--   where embedding is not null and deleted_at is null and embedding_status = 'ready';
