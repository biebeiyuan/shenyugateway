-- Temporal personal memory graph.
-- Original content remains in its owning source table; this schema stores only
-- stable entity anchors, source mentions, typed relationships, and provenance.

create extension if not exists pgcrypto;

create table if not exists public.shenyu_entities (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null,
  canonical_name text not null,
  description text not null default '',
  status text not null default 'active',
  merged_into uuid references public.shenyu_entities(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb,
  created_by text not null default 'resident',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint shenyu_entities_name_not_blank check (btrim(canonical_name) <> ''),
  constraint shenyu_entities_type_check check (
    entity_type in ('person', 'place', 'object', 'topic')
  ),
  constraint shenyu_entities_status_check check (
    status in ('active', 'archived', 'merged')
  ),
  constraint shenyu_entities_merged_target_check check (
    (status = 'merged' and merged_into is not null)
    or (status <> 'merged' and merged_into is null)
  )
);

create table if not exists public.shenyu_entity_aliases (
  id uuid primary key default gen_random_uuid(),
  entity_id uuid not null references public.shenyu_entities(id) on delete cascade,
  alias text not null,
  normalized_alias text not null,
  status text not null default 'confirmed',
  is_primary boolean not null default false,
  confidence double precision not null default 1.0,
  provenance text not null default 'manual',
  evidence text not null default '',
  created_by text not null default 'resident',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint shenyu_entity_aliases_alias_not_blank check (btrim(alias) <> ''),
  constraint shenyu_entity_aliases_normalized_not_blank check (btrim(normalized_alias) <> ''),
  constraint shenyu_entity_aliases_status_check check (
    status in ('confirmed', 'suggested', 'rejected')
  ),
  constraint shenyu_entity_aliases_confidence_check check (
    confidence between 0 and 1
  ),
  constraint shenyu_entity_aliases_entity_value_uniq
    unique (entity_id, normalized_alias)
);

create table if not exists public.shenyu_entity_mentions (
  id uuid primary key default gen_random_uuid(),
  entity_id uuid not null references public.shenyu_entities(id) on delete cascade,
  source_table text not null,
  source_type text not null,
  source_id text not null,
  status text not null default 'confirmed',
  origin text not null default 'exact_alias',
  matched_alias text,
  confidence double precision not null default 1.0,
  evidence text not null default '',
  source_content_hash text,
  created_by text not null default 'gateway',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint shenyu_entity_mentions_source_not_blank check (
    btrim(source_table) <> '' and btrim(source_type) <> '' and btrim(source_id) <> ''
  ),
  constraint shenyu_entity_mentions_status_check check (
    status in ('confirmed', 'suggested', 'rejected')
  ),
  constraint shenyu_entity_mentions_origin_check check (
    origin in ('manual', 'exact_alias', 'structural', 'suggestion')
  ),
  constraint shenyu_entity_mentions_confidence_check check (
    confidence between 0 and 1
  ),
  constraint shenyu_entity_mentions_entity_source_uniq
    unique (entity_id, source_table, source_id)
);

create table if not exists public.shenyu_entity_relations (
  id uuid primary key default gen_random_uuid(),
  source_entity_id uuid not null references public.shenyu_entities(id) on delete cascade,
  target_entity_id uuid not null references public.shenyu_entities(id) on delete cascade,
  relation_type text not null,
  status text not null default 'confirmed',
  confidence double precision not null default 1.0,
  evidence text not null default '',
  provenance text not null default 'manual',
  evidence_source_table text,
  evidence_source_type text,
  evidence_source_id text,
  valid_from timestamptz,
  valid_to timestamptz,
  created_by text not null default 'resident',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint shenyu_entity_relations_distinct_check check (
    source_entity_id <> target_entity_id
  ),
  constraint shenyu_entity_relations_type_not_blank check (
    btrim(relation_type) <> ''
  ),
  constraint shenyu_entity_relations_status_check check (
    status in ('confirmed', 'suggested', 'rejected', 'archived')
  ),
  constraint shenyu_entity_relations_confidence_check check (
    confidence between 0 and 1
  ),
  constraint shenyu_entity_relations_validity_check check (
    valid_from is null or valid_to is null or valid_from <= valid_to
  )
);

create index if not exists shenyu_entities_type_status_idx
  on public.shenyu_entities (entity_type, status, canonical_name);

create index if not exists shenyu_entity_aliases_lookup_idx
  on public.shenyu_entity_aliases (normalized_alias, status);

create index if not exists shenyu_entity_mentions_entity_idx
  on public.shenyu_entity_mentions (entity_id, status, updated_at desc);

create index if not exists shenyu_entity_mentions_source_idx
  on public.shenyu_entity_mentions (source_table, source_id, status);

create index if not exists shenyu_entity_relations_source_idx
  on public.shenyu_entity_relations (source_entity_id, status, updated_at desc);

create index if not exists shenyu_entity_relations_target_idx
  on public.shenyu_entity_relations (target_entity_id, status, updated_at desc);

create or replace function public.shenyu_memory_graph_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_shenyu_entities_updated_at on public.shenyu_entities;
create trigger trg_shenyu_entities_updated_at
before update on public.shenyu_entities
for each row execute function public.shenyu_memory_graph_touch_updated_at();

drop trigger if exists trg_shenyu_entity_aliases_updated_at on public.shenyu_entity_aliases;
create trigger trg_shenyu_entity_aliases_updated_at
before update on public.shenyu_entity_aliases
for each row execute function public.shenyu_memory_graph_touch_updated_at();

drop trigger if exists trg_shenyu_entity_mentions_updated_at on public.shenyu_entity_mentions;
create trigger trg_shenyu_entity_mentions_updated_at
before update on public.shenyu_entity_mentions
for each row execute function public.shenyu_memory_graph_touch_updated_at();

drop trigger if exists trg_shenyu_entity_relations_updated_at on public.shenyu_entity_relations;
create trigger trg_shenyu_entity_relations_updated_at
before update on public.shenyu_entity_relations
for each row execute function public.shenyu_memory_graph_touch_updated_at();
