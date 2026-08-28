-- 便签的倒计时/日期提醒：到了那天，这张便签自己挂上动态岛一次。
-- Run AFTER 20260627_mem_notes_v2_fields.sql.
--
-- remind_on   day precision (Asia/Shanghai 的"那天"由网关判断，这里只存日期)
-- reminded_at 挂过一次之后打的"已提醒"戳；只打戳，不改 status，不删便签。

ALTER TABLE shenyu_mem_notes
  ADD COLUMN IF NOT EXISTS remind_on date,
  ADD COLUMN IF NOT EXISTS reminded_at timestamptz;

-- ============================================================
-- 日期本身就是触发锚点：只写了一个日子的便签也能是 active。
-- ============================================================

ALTER TABLE shenyu_mem_notes
  DROP CONSTRAINT IF EXISTS shenyu_mem_notes_active_ready_check;

ALTER TABLE shenyu_mem_notes
  ADD CONSTRAINT shenyu_mem_notes_active_ready_check CHECK (
    status <> 'active'
    OR (
      coalesce(mem_type, '') IN ('她为我做的事', '我为她做的事', '关于她的事实', '关于我的事', '心里那一档', '承诺')
      AND (
        btrim(trigger_text) <> ''
        OR coalesce(cardinality(trigger_keywords), 0) > 0
        OR coalesce(cardinality(entities), 0) > 0
        OR coalesce(cardinality(people), 0) > 0
        OR coalesce(cardinality(places), 0) > 0
        OR coalesce(cardinality(objects), 0) > 0
        OR coalesce(cardinality(keywords), 0) > 0
        OR coalesce(cardinality(scene_tags), 0) > 0
        OR coalesce(cardinality(trigger_scenarios), 0) > 0
        OR remind_on IS NOT NULL
      )
    )
  );

-- ============================================================
-- 到日子且还没挂过的便签：每轮对话都要查一次，走独立窄索引。
-- ============================================================

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_due_reminder_idx
  ON shenyu_mem_notes (remind_on)
  WHERE status = 'active' AND remind_on IS NOT NULL AND reminded_at IS NULL;

-- 写入时按 (content, remind_on) 去重，要查同一天里所有没收起来的便签，
-- 所以这个索引不限 status，只排掉没有日期的行。
CREATE INDEX IF NOT EXISTS shenyu_mem_notes_remind_on_idx
  ON shenyu_mem_notes (remind_on)
  WHERE remind_on IS NOT NULL;
