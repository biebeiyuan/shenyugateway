-- Shenyu mem notes.
-- Replaces the old inline atomic-memory runtime path.
--
-- Capture is intentionally plain:
--   [mem]...[/mem] writes one raw paragraph to content with status=captured.
-- YuanYuan/Shenyu can later fill mem_type, trigger_text, trigger_keywords,
-- cooldown, and status from the admin UI.

create extension if not exists pgcrypto;

create table if not exists shenyu_mem_notes (
  id uuid primary key default gen_random_uuid(),
  session_tag text not null default 'default',
  content text not null,
  mem_type text,
  trigger_text text not null default '',
  trigger_keywords text[] not null default '{}',
  status text not null default 'captured',
  cooldown_hours integer not null default 72,
  last_triggered_at timestamptz,
  trigger_count integer not null default 0,
  source_model text not null default '',
  source_session_id text,
  source_excerpt text not null default '',
  review_note text not null default '',
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint shenyu_mem_notes_content_not_blank check (btrim(content) <> ''),
  constraint shenyu_mem_notes_type_check check (
    mem_type is null
    or mem_type in ('她为我做的事', '关于她的事实', '心里那一档', '承诺')
  ),
  constraint shenyu_mem_notes_status_check check (
    status in ('captured', 'active', 'paused', 'archived')
  ),
  constraint shenyu_mem_notes_active_ready_check check (
    status <> 'active'
    or (
      coalesce(mem_type, '') in ('她为我做的事', '关于她的事实', '心里那一档', '承诺')
      and (
        btrim(trigger_text) <> ''
        or coalesce(cardinality(trigger_keywords), 0) > 0
      )
    )
  ),
  constraint shenyu_mem_notes_cooldown_check check (
    cooldown_hours between 0 and 8760
  )
);

create index if not exists shenyu_mem_notes_status_updated_idx
  on shenyu_mem_notes (status, updated_at desc);

create index if not exists shenyu_mem_notes_session_status_idx
  on shenyu_mem_notes (session_tag, status, updated_at desc);

create index if not exists shenyu_mem_notes_triggered_idx
  on shenyu_mem_notes (status, last_triggered_at, trigger_count);

create or replace function shenyu_mem_notes_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists shenyu_mem_notes_touch_updated_at on shenyu_mem_notes;
create trigger shenyu_mem_notes_touch_updated_at
before update on shenyu_mem_notes
for each row
execute function shenyu_mem_notes_touch_updated_at();
