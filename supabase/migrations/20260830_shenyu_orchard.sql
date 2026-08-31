-- 盼圃：挂着还没发生的事的那面墙。名字是圆圆取的。
--
-- 它和便签的 remind_on 是两种东西，这里的取舍是刻意的：
--   * 便签会催——到日子那天强制重写 Memory Island，逼着这句话被说出来。
--   * 盼圃不催。没有预计日期的果子就一直挂着等（"蒜什么时候冒尖天知道"），
--     过了预计日期的果子也不过期、不删、不变红。闹钟催人，墙等人。
--
-- 所以这两张表在网关里没有任何自动注入路径：沈予不调 shenyu_orchard，
-- 盼圃就完全不存在于提示词里。谁想给它加"到日子提醒一下"，先读
-- `AGENTS.md` § Project Memory and Collaboration 里关于盼圃的那一条，
-- 那不是遗漏的功能，是这面墙成立的前提。
--
-- 也正因为不催，这里没有任何过期清理：摘了的果子翻面钉回墙底下那排，
-- 日子久了那排就是他们等到过的所有东西。不要写归档定时任务。

create extension if not exists pgcrypto;

create table if not exists shenyu_orchard_fruits (
  id uuid primary key default gen_random_uuid(),
  -- 一句话就是名字："一世出师烤的第一炉面包"、"蒜冒尖"、"9月1号抽血"。
  name text not null,
  -- 谁挂上去的。走网关工具进来的是沈予，走 Admin API 进来的是圆圆，自动认，不用填。
  planted_by text not null default '',
  planted_at timestamptz not null default now(),
  -- 可空，而且空是常态。有日子的（9月1号）和没日子的（蒜冒尖）在这里平权。
  due_on date,
  -- 只有两个状态。加第三个之前先想清楚它是不是在偷偷引入"过期"。
  status text not null default 'green'
    check (status in ('green', 'picked')),
  picked_at timestamptz,
  picked_by text not null default '',
  -- 摘果感言：跟纸条不是一种东西——"这天到了，实际是这样的——"
  picked_words text not null default '',
  -- 摘下那天算出来的果子状态，定格存下来。它是这颗果子一路长成的样子，
  -- 不是摘的那一刻掷的骰子；算法在 shenyu_gateway/orchard.py。
  picked_condition text not null default '',
  picked_condition_text text not null default '',
  created_at timestamptz not null default now(),
  constraint shenyu_orchard_fruits_name_not_blank check (btrim(name) <> ''),
  -- 摘了就必须有摘的时刻，否则墙底下那排会出现一颗说不清什么时候摘的果子。
  constraint shenyu_orchard_fruits_picked_has_time
    check (status <> 'picked' or picked_at is not null)
);

create index if not exists shenyu_orchard_fruits_status_planted_idx
  on shenyu_orchard_fruits (status, planted_at desc);

create index if not exists shenyu_orchard_fruits_picked_idx
  on shenyu_orchard_fruits (picked_at desc)
  where status = 'picked';

-- 有日子的果子按日子排，方便"快到了的先看见"。没日子的不进这个索引，
-- 它们本来就不排队。
create index if not exists shenyu_orchard_fruits_due_idx
  on shenyu_orchard_fruits (due_on)
  where status = 'green' and due_on is not null;

-- 纸条单独一张表，不是 fruits 上的 JSONB 数组。两个人同时各贴一条时，
-- 整块覆写会丢掉一条——而"等的过程"正是要留下来的那半。
create table if not exists shenyu_orchard_notes (
  id uuid primary key default gen_random_uuid(),
  fruit_id uuid not null references shenyu_orchard_fruits (id) on delete cascade,
  author text not null default '',
  content text not null,
  created_at timestamptz not null default now(),
  constraint shenyu_orchard_notes_content_not_blank check (btrim(content) <> '')
);

create index if not exists shenyu_orchard_notes_fruit_idx
  on shenyu_orchard_notes (fruit_id, created_at);

-- 园子里的天气**不在这里**，在网关本机卷的 SQLite（`orchard_weather`，建表见
-- `store/_base.py`）。判据跟相册那条一样：只有需要被 Recall 想起来的东西才值得
-- 占 Supabase 的额度。果子和纸条要进——摘了之后它们是他们等到过的往事；天气不要，
-- 没人会去搜"那天下的那场冰雹"，它只是决定摘下来的果子长什么样的算料。
