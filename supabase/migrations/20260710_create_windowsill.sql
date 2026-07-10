-- Windowsill: short essays and passing moods that do not need to become
-- structured memories.

create extension if not exists pgcrypto;

create table if not exists windowsill (
  id uuid primary key default gen_random_uuid(),
  content text not null,
  created_at timestamptz not null default now(),
  title text not null default '',
  mood text not null default '',
  constraint windowsill_content_not_blank check (btrim(content) <> '')
);

create index if not exists windowsill_created_at_idx
  on windowsill (created_at desc);

create index if not exists windowsill_mood_created_at_idx
  on windowsill (mood, created_at desc)
  where btrim(mood) <> '';
