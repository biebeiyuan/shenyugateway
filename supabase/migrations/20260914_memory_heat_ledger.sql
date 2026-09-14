-- 记忆热度：事件账本 + 读时算出来的活性视图。
--
-- 为什么是事件表而不是一个 activation_score 列：
-- 存分数就必须每晚跑 cron 去乘衰减率。漏跑一晚、换容器、迁移库，地形就被抹平或
-- 算错，而且没人会发现（分数看起来一直是个合理的数）。事件是不可变的，活性在读的
-- 时候由 created_at 推出来，所以：没有 cron、没有夜间任务、漏跑不存在，
-- 顺带白拿一个「上次被想起是哪天」——那个量是后面「自己浮上来」要用的。
--
-- 衰减 0.82/天，半衰期 ≈ ln(0.5)/ln(0.82) ≈ 3.5 天。也就是说这套地形记的是
-- 「最近这几周」，不是一辈子。这是刻意的：一辈子的权重会长成车辙。
--
-- 一次注入记一行，而不是 star_ids uuid[] 数组：按记忆聚合是这张表唯一的读法，
-- 数组会让那个聚合写不出来。

-- ============================================================
-- 1. 事件账本
-- ============================================================

create table if not exists shenyu_heat_events (
  id uuid primary key default gen_random_uuid(),

  -- 幂等键。同一轮的同一条记忆只该记一次，网络重试、流式断连重连、
  -- tool loop 里的多次 mark 都不该重复加热。
  event_id text not null unique,

  event_type text not null default 'island_enter',

  -- 多态外键拆成两列而不是一个 memory_id：这样引用完整性是真的，
  -- 而且记忆被删时它的热度跟着级联走，不留下幽灵热度。
  star_id uuid references shenyu_stars(id) on delete cascade,
  mem_note_id uuid references shenyu_mem_notes(id) on delete cascade,

  session_id text,
  turn_index integer,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),

  -- 恰好一个非空。多态表最容易烂的地方就是两列都填或都不填。
  constraint shenyu_heat_events_exactly_one_target check (
    (star_id is not null and mem_note_id is null)
    or (star_id is null and mem_note_id is not null)
  ),

  constraint shenyu_heat_events_type_check check (
    event_type in ('island_enter', 'manual_search', 'tool_use', 'trigger_hit')
  )
);

-- 聚合视图按目标 + 时间扫，这两条索引是给它用的
create index if not exists shenyu_heat_events_star_idx
  on shenyu_heat_events (star_id, created_at desc)
  where star_id is not null;

create index if not exists shenyu_heat_events_mem_note_idx
  on shenyu_heat_events (mem_note_id, created_at desc)
  where mem_note_id is not null;

create index if not exists shenyu_heat_events_created_idx
  on shenyu_heat_events (created_at desc);

-- ============================================================
-- 2. 活性视图：读时算，不存
-- ============================================================
-- 90 天窗口不是近似，是免费的：0.82^90 ≈ 3e-9，比 double 的噪声还小。
-- 但它把扫描量永久封住了——三年后这个视图和今天一样快。
--
-- 恒星不参与加热。它们本来就一直在岛上，活性会单调涨到封顶然后永远贴着上限，
-- 那是把钉子长成一面墙。恒星已经有自己的 constant_boost（1.3），
-- 这里排除掉是结构上的保证，不靠写入侧记得跳过。

create or replace view shenyu_star_activation as
select
  s.id as star_id,
  coalesce(sum(power(0.82, extract(epoch from (now() - e.created_at)) / 86400.0)), 0.0)
    as activation,
  count(e.id) as heat_count,
  max(e.created_at) as last_heated_at
from shenyu_stars s
left join shenyu_heat_events e
  on e.star_id = s.id
  and e.created_at > now() - interval '90 days'
where s.is_constant is not true
group by s.id
having count(e.id) > 0;

create or replace view shenyu_mem_note_activation as
select
  m.id as mem_note_id,
  coalesce(sum(power(0.82, extract(epoch from (now() - e.created_at)) / 86400.0)), 0.0)
    as activation,
  count(e.id) as heat_count,
  max(e.created_at) as last_heated_at
from shenyu_mem_notes m
left join shenyu_heat_events e
  on e.mem_note_id = m.id
  and e.created_at > now() - interval '90 days'
group by m.id
having count(e.id) > 0;

-- ============================================================
-- 3. 注释：把「为什么」放在 schema 里，别放在某个人的记性里
-- ============================================================

comment on table shenyu_heat_events is
  '记忆被真正想起的不可变事件账本。一条记忆一轮一行，event_id 幂等。
   活性不存在这里也不存在记忆表上，由 shenyu_*_activation 视图按 created_at 读时算出来——
   所以没有夜间衰减任务，漏跑不存在。';

comment on column shenyu_heat_events.event_id is
  '幂等键，形如 <session_id>:<turn_index>:<kind>:<memory_id>。
   turn_index 必须来自 island_state.human_turn_index，不是 session.message_count——
   session 行里没有 turn_count 这个字段，取不到会静默落 0，
   于是一个 session 里只会加热一次。';

comment on column shenyu_heat_events.star_id is
  '只在这条记忆「这一轮新进岛」时写（resolve_memory_island 返回的 entering），
   不是「这一轮在岛上」。岛有 retain，按驻留写会把停留时长当成想起次数记，
   一颗星留十轮就记十次。';

comment on view shenyu_star_activation is
  '衰减 0.82/天（半衰期 ≈ 3.5 天），90 天窗口，恒星排除在外。
   activation 是原始值、无上界，排序修正项必须在代码里压缩再封顶：
   1 + w·ln(1+activation) clamp 到 [1.0, 1.3]，和家里其他 modifier 同一把尺。
   直接乘 1 + 0.15·activation 会把分数顶出 0–1 值域，
   mem_note_min_score 那几条线会静默漂移。';

comment on view shenyu_mem_note_activation is
  '同 shenyu_star_activation。便签表没有 is_constant 列，
   所以这边没有恒星排除——想在便签上钉死什么，得先有那一列。';
