-- Shenyu star memory.
--
-- Stars are tiny felt-state notes. Recall is intentionally logged as raw runs,
-- candidates, and feedback so the gateway can learn later without losing the
-- original observations.

create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists shenyu_stars (
  id uuid primary key default gen_random_uuid(),
  session_tag text not null default 'default',
  content text not null,
  chord text not null default '',
  chord_root text not null default '',
  chord_quality text not null default '',
  chord_tension double precision,
  status text not null default 'active',
  is_constant boolean not null default false,
  reviewed_at timestamptz,
  activation_count integer not null default 0,
  last_activated_at timestamptz,
  source_model text not null default '',
  source_session_id text,
  source_excerpt text not null default '',
  search_tokens text[] not null default '{}',
  embedding vector(1024),
  embedding_model text,
  embedding_status text not null default 'skipped',
  embedding_error text,
  embedded_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint shenyu_stars_content_not_blank check (btrim(content) <> ''),
  constraint shenyu_stars_status_check check (status in ('active', 'paused', 'archived')),
  constraint shenyu_stars_embedding_status_check check (embedding_status in ('skipped', 'pending', 'ready', 'failed'))
);

create index if not exists shenyu_stars_active_updated_idx
  on shenyu_stars (status, updated_at desc);

create index if not exists shenyu_stars_review_idx
  on shenyu_stars (status, reviewed_at, created_at asc);

create index if not exists shenyu_stars_chord_idx
  on shenyu_stars (chord_root, chord_quality, updated_at desc);

create index if not exists shenyu_stars_constant_idx
  on shenyu_stars (is_constant, updated_at desc)
  where status = 'active';

create table if not exists shenyu_star_links (
  id uuid primary key default gen_random_uuid(),
  from_node_type text not null default 'star',
  from_node_id text not null,
  to_node_type text not null default 'star',
  to_node_id text not null,
  relation_type text not null default 'harmony',
  source text not null default 'gateway',
  status text not null default 'active',
  confidence double precision not null default 0.5,
  weight double precision not null default 1.0,
  position integer,
  bidirectional boolean not null default true,
  times_suggested integer not null default 0,
  times_confirmed integer not null default 0,
  times_ignored integer not null default 0,
  last_suggested_at timestamptz,
  last_confirmed_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint shenyu_star_links_status_check check (status in ('active', 'paused', 'archived')),
  constraint shenyu_star_links_relation_check check (
    relation_type in ('constellation', 'harmony', 'keyword', 'heartbeat', 'manual')
  ),
  constraint shenyu_star_links_no_self_edge check (
    from_node_type <> to_node_type or from_node_id <> to_node_id
  )
);

create unique index if not exists shenyu_star_links_unique_edge_idx
  on shenyu_star_links (from_node_type, from_node_id, to_node_type, to_node_id, relation_type);

create index if not exists shenyu_star_links_from_idx
  on shenyu_star_links (from_node_type, from_node_id, status, weight desc);

create index if not exists shenyu_star_links_to_idx
  on shenyu_star_links (to_node_type, to_node_id, status, weight desc);

create table if not exists shenyu_star_recall_runs (
  id uuid primary key default gen_random_uuid(),
  surface text not null default 'chat_inject',
  trigger_text text not null default '',
  seed_node_type text,
  seed_node_id text,
  session_tag text,
  session_id text,
  limit_requested integer not null default 3,
  ranker_version text not null default 'star-ranker-v0',
  feature_schema_version text not null default 'star-features-v0',
  weights_version text not null default 'manual-v0',
  query_embedding_status text not null default 'skipped',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists shenyu_star_recall_runs_surface_idx
  on shenyu_star_recall_runs (surface, created_at desc);

create table if not exists shenyu_star_recall_candidates (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references shenyu_star_recall_runs(id) on delete cascade,
  candidate_node_type text not null default 'star',
  candidate_node_id text not null,
  rank integer not null default 0,
  shown boolean not null default false,
  injected boolean not null default false,
  final_score double precision not null default 0,
  content_score double precision not null default 0,
  keyword_score double precision not null default 0,
  chord_score double precision not null default 0,
  harmony_score double precision not null default 0,
  content_gravity_score double precision not null default 0,
  actr_score double precision not null default 0,
  constant_bonus double precision not null default 0,
  novelty_bonus double precision not null default 0,
  ignored_penalty double precision not null default 0,
  action_status text,
  feature_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint shenyu_star_recall_candidates_action_check check (
    action_status is null
    or action_status in ('positive', 'negative', 'missed', 'connected', 'skipped', 'should_surface')
  )
);

create index if not exists shenyu_star_recall_candidates_run_idx
  on shenyu_star_recall_candidates (run_id, rank asc);

create index if not exists shenyu_star_recall_candidates_candidate_idx
  on shenyu_star_recall_candidates (candidate_node_type, candidate_node_id, shown, created_at desc);

create table if not exists shenyu_star_feedback (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references shenyu_star_recall_runs(id) on delete set null,
  candidate_id uuid references shenyu_star_recall_candidates(id) on delete set null,
  candidate_node_type text,
  candidate_node_id text,
  expected_node_type text,
  expected_node_id text,
  feedback text not null,
  scored_by text not null default '沈予',
  note text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint shenyu_star_feedback_feedback_check check (
    feedback in ('positive', 'negative', 'missed', 'connected', 'skipped', 'should_surface')
  )
);

create index if not exists shenyu_star_feedback_run_idx
  on shenyu_star_feedback (run_id, created_at desc);

create index if not exists shenyu_star_feedback_expected_idx
  on shenyu_star_feedback (expected_node_type, expected_node_id, feedback, created_at desc);

create table if not exists shenyu_star_activations (
  id uuid primary key default gen_random_uuid(),
  star_id uuid references shenyu_stars(id) on delete cascade,
  run_id uuid references shenyu_star_recall_runs(id) on delete set null,
  surface text not null default 'chat_inject',
  trigger_text text not null default '',
  score double precision not null default 0,
  injected boolean not null default false,
  session_tag text,
  session_id text,
  activated_at timestamptz not null default now()
);

create index if not exists shenyu_star_activations_star_idx
  on shenyu_star_activations (star_id, activated_at desc);

create or replace function shenyu_star_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists shenyu_stars_touch_updated_at on shenyu_stars;
create trigger shenyu_stars_touch_updated_at
before update on shenyu_stars
for each row
execute function shenyu_star_touch_updated_at();

drop trigger if exists shenyu_star_links_touch_updated_at on shenyu_star_links;
create trigger shenyu_star_links_touch_updated_at
before update on shenyu_star_links
for each row
execute function shenyu_star_touch_updated_at();

create or replace function public.match_shenyu_stars(
  query_embedding vector(1024),
  match_count integer default 80,
  include_status text default 'active'
)
returns table (
  id uuid,
  session_tag text,
  content text,
  chord text,
  chord_root text,
  chord_quality text,
  chord_tension double precision,
  status text,
  is_constant boolean,
  reviewed_at timestamptz,
  activation_count integer,
  last_activated_at timestamptz,
  source_model text,
  source_session_id text,
  source_excerpt text,
  search_tokens text[],
  embedding_model text,
  embedding_status text,
  metadata jsonb,
  created_at timestamptz,
  updated_at timestamptz,
  vector_score double precision
)
language sql
stable
as $$
  select
    s.id,
    s.session_tag,
    s.content,
    s.chord,
    s.chord_root,
    s.chord_quality,
    s.chord_tension,
    s.status,
    s.is_constant,
    s.reviewed_at,
    s.activation_count,
    s.last_activated_at,
    s.source_model,
    s.source_session_id,
    s.source_excerpt,
    s.search_tokens,
    s.embedding_model,
    s.embedding_status,
    s.metadata,
    s.created_at,
    s.updated_at,
    greatest(0, 1 - (s.embedding <=> query_embedding)) as vector_score
  from public.shenyu_stars s
  where s.embedding is not null
    and s.embedding_status = 'ready'
    and (include_status is null or include_status = '' or s.status = include_status)
  order by s.embedding <=> query_embedding
  limit greatest(1, least(coalesce(match_count, 80), 200));
$$;

-- Add after the table grows large enough:
-- create index if not exists shenyu_stars_embedding_hnsw_idx
--   on public.shenyu_stars
--   using hnsw (embedding vector_cosine_ops)
--   where embedding is not null and embedding_status = 'ready' and status = 'active';
