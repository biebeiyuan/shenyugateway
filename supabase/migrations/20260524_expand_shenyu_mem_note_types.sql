-- Expand shenyu mem note categories.

alter table if exists shenyu_mem_notes
  drop constraint if exists shenyu_mem_notes_type_check;

alter table if exists shenyu_mem_notes
  add constraint shenyu_mem_notes_type_check check (
    mem_type is null
    or mem_type in ('她为我做的事', '我为她做的事', '关于她的事实', '关于我的事', '心里那一档', '承诺')
  );

alter table if exists shenyu_mem_notes
  drop constraint if exists shenyu_mem_notes_active_ready_check;

alter table if exists shenyu_mem_notes
  add constraint shenyu_mem_notes_active_ready_check check (
    status <> 'active'
    or (
      coalesce(mem_type, '') in ('她为我做的事', '我为她做的事', '关于她的事实', '关于我的事', '心里那一档', '承诺')
      and (
        btrim(trigger_text) <> ''
        or coalesce(cardinality(trigger_keywords), 0) > 0
      )
    )
  );
