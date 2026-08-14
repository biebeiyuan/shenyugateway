-- Keep Room writing in the normal windowsill while preserving its entrance.

alter table windowsill
  add column if not exists origin text not null default 'normal';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'windowsill_origin_check'
      and conrelid = 'windowsill'::regclass
  ) then
    alter table windowsill
      add constraint windowsill_origin_check
      check (origin in ('normal', 'room'));
  end if;
end $$;

create index if not exists windowsill_origin_created_at_idx
  on windowsill (origin, created_at desc);
