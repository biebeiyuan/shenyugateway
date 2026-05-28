create extension if not exists pg_trgm;

create or replace function public.search_shenyu_recall_index(
  query_tokens text[] default '{}',
  query_text text default '',
  match_count integer default 160,
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
  importance double precision
)
language sql
stable
as $$
  with args as (
    select
      coalesce(query_tokens, '{}'::text[]) as tokens,
      nullif(btrim(coalesce(query_text, '')), '') as q,
      greatest(1, least(coalesce(match_count, 160), 1000)) as wanted
  ),
  matched as (
    select
      sri.source_table,
      sri.source_id,
      sri.chunk_index,
      (
        select count(*)::integer
        from unnest(args.tokens) token
        where token = any(sri.search_tokens)
      ) as token_hits,
      case when args.q is null then 0.0 else similarity(sri.search_text, args.q) end as trigram_score,
      case when args.q is not null and sri.search_text ilike '%' || args.q || '%' then 1 else 0 end as phrase_hit,
      sri.importance,
      coalesce(sri.event_date, sri.source_updated_at, sri.indexed_at) as sort_date
    from public.shenyu_recall_index sri
    cross join args
    where sri.deleted_at is null
      and (source_types is null or cardinality(source_types) = 0 or sri.source_type = any(source_types))
      and (
        cardinality(args.tokens) = 0
        or sri.search_tokens && args.tokens
        or (args.q is not null and similarity(sri.search_text, args.q) >= 0.08)
        or (args.q is not null and sri.search_text ilike '%' || args.q || '%')
      )
    order by token_hits desc, phrase_hit desc, trigram_score desc, sri.importance desc, sort_date desc
    limit (select wanted from args)
  ),
  source_keys as (
    select
      source_table,
      source_id,
      max(token_hits) as source_token_hits,
      max(phrase_hit) as source_phrase_hit,
      max(trigram_score) as source_trigram_score,
      max(importance) as source_importance,
      max(sort_date) as source_sort_date
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
    sri.importance
  from public.shenyu_recall_index sri
  join source_keys sk
    on sk.source_table = sri.source_table
   and sk.source_id = sri.source_id
  where sri.deleted_at is null
  order by
    sk.source_token_hits desc,
    sk.source_phrase_hit desc,
    sk.source_trigram_score desc,
    sk.source_importance desc,
    sk.source_sort_date desc,
    sri.chunk_index asc;
$$;
