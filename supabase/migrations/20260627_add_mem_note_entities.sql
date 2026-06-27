-- Add entities column for precise entity-based matching in mem notes.

ALTER TABLE shenyu_mem_notes
  ADD COLUMN IF NOT EXISTS entities text[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_entities_idx
  ON shenyu_mem_notes USING gin (entities)
  WHERE status = 'active';

-- Relax the active_ready_check to also accept notes with entities as valid triggers.
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
      )
    )
  );
