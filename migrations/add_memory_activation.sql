-- 记忆激活系统：activation_score（加热分数）、replaces_id（更新边）、heat_events（幂等事件表）

-- Stars: 加 activation_score 和 replaces_id
ALTER TABLE shenyu_stars ADD COLUMN IF NOT EXISTS activation_score REAL DEFAULT 0.0;
ALTER TABLE shenyu_stars ADD COLUMN IF NOT EXISTS replaces_id TEXT REFERENCES shenyu_stars(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_stars_replaces ON shenyu_stars(replaces_id) WHERE replaces_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stars_activation ON shenyu_stars(activation_score) WHERE activation_score > 0;

-- Mem Notes: 加 activation_score 和 replaces_id
ALTER TABLE shenyu_mem_notes ADD COLUMN IF NOT EXISTS activation_score REAL DEFAULT 0.0;
ALTER TABLE shenyu_mem_notes ADD COLUMN IF NOT EXISTS replaces_id TEXT REFERENCES shenyu_mem_notes(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_mem_notes_replaces ON shenyu_mem_notes(replaces_id) WHERE replaces_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mem_notes_activation ON shenyu_mem_notes(activation_score) WHERE activation_score > 0;

-- 幂等事件表：防止重复加热
CREATE TABLE IF NOT EXISTS shenyu_heat_events (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  event_id TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL,
  turn_index INTEGER NOT NULL,
  memory_kind TEXT NOT NULL,
  memory_id TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_heat_events_lookup ON shenyu_heat_events(session_id, turn_index, memory_kind, memory_id);
CREATE INDEX IF NOT EXISTS idx_heat_events_memory ON shenyu_heat_events(memory_kind, memory_id);
