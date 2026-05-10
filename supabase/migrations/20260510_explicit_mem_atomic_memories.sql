-- Explicit [mem] atomic memories.
-- New gateway behavior:
--   required: content_surface, subject
--   defaults: status=active, tier=2, importance=3, memory_type=fact
--   legacy scoring/extractor fields are dropped after backfill.

alter table if exists atomic_memories
  alter column quote drop not null,
  alter column time_hint drop not null,
  alter column source_excerpt drop not null,
  alter column heat set default 0.68,
  alter column activation_count set default 0,
  alter column status set default 'active',
  alter column subject set default '沈予',
  alter column tier set default 2,
  alter column importance set default 3,
  alter column memory_type set default 'fact';

do $$
declare
  constraint_row record;
begin
  for constraint_row in
    select n.nspname, c.conname
    from pg_constraint c
    join pg_class t on t.oid = c.conrelid
    join pg_namespace n on n.oid = t.relnamespace
    where t.relname = 'atomic_memories'
      and c.contype = 'c'
      and pg_get_constraintdef(c.oid) ilike '%memory_type%'
  loop
    execute format(
      'alter table %I.%I drop constraint %I',
      constraint_row.nspname,
      'atomic_memories',
      constraint_row.conname
    );
  end loop;
end $$;

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_name = 'atomic_memories'
      and column_name = 'content_canonical'
  ) then
    execute $q$
      update atomic_memories
      set content_surface = coalesce(
        nullif(content_surface, ''),
        nullif(content_canonical, ''),
        nullif(quote, ''),
        nullif(source_excerpt, '')
      )
      where content_surface is null or content_surface = ''
    $q$;
  else
    execute $q$
      update atomic_memories
      set content_surface = coalesce(
        nullif(content_surface, ''),
        nullif(quote, ''),
        nullif(source_excerpt, '')
      )
      where content_surface is null or content_surface = ''
    $q$;
  end if;
end $$;

delete from atomic_memories
where content_surface is null
   or btrim(content_surface) = ''
   or btrim(content_surface) in ('…', '...', '。。', '。。。');

update atomic_memories
set subject = '沈予'
where subject is null or subject = '';

update atomic_memories
set memory_type = case
  when memory_type in ('emotion', 'commitment', 'fact', 'relation', 'preference', 'boundary') then memory_type
  when memory_type = 'state' then 'emotion'
  else 'fact'
end
where memory_type is null
   or memory_type not in ('emotion', 'commitment', 'fact', 'relation', 'preference', 'boundary');

alter table if exists atomic_memories
  alter column content_surface set not null,
  alter column subject set not null,
  add constraint atomic_memories_memory_type_simple
    check (memory_type in ('emotion', 'commitment', 'fact', 'relation', 'preference', 'boundary'));

alter table if exists atomic_memories
  drop column if exists content_canonical,
  drop column if exists confidence,
  drop column if exists valence,
  drop column if exists arousal;

create index if not exists atomic_memories_active_lookup_idx
  on atomic_memories (status, session_tag, heat desc, importance desc, updated_at desc);
