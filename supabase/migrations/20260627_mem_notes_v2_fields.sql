-- Mem0 v2: structured life-continuity fields for shenyu_mem_notes.
-- Run AFTER 20260627_add_mem_note_entities.sql.

-- ============================================================
-- 1. Common structured fields
-- ============================================================

ALTER TABLE shenyu_mem_notes
  ADD COLUMN IF NOT EXISTS summary text,
  ADD COLUMN IF NOT EXISTS memory_kind text,
  ADD COLUMN IF NOT EXISTS people text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS places text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS objects text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS keywords text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS event_time text,
  ADD COLUMN IF NOT EXISTS importance integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS confidence numeric NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS mention_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS promotion_score numeric NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS decay_after timestamptz;

-- ============================================================
-- 2. promise-specific fields
-- ============================================================

ALTER TABLE shenyu_mem_notes
  ADD COLUMN IF NOT EXISTS promise_text text,
  ADD COLUMN IF NOT EXISTS trigger_scenarios text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS due_hint text,
  ADD COLUMN IF NOT EXISTS resolved boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS resolved_at timestamptz,
  ADD COLUMN IF NOT EXISTS next_action text,
  ADD COLUMN IF NOT EXISTS privacy_level text;

-- ============================================================
-- 3. running_joke-specific fields
-- ============================================================

ALTER TABLE shenyu_mem_notes
  ADD COLUMN IF NOT EXISTS joke_text text,
  ADD COLUMN IF NOT EXISTS scene_tags text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS last_used_at timestamptz;

-- ============================================================
-- 4. routine-specific fields
-- ============================================================

ALTER TABLE shenyu_mem_notes
  ADD COLUMN IF NOT EXISTS routine_domain text,
  ADD COLUMN IF NOT EXISTS pattern text,
  ADD COLUMN IF NOT EXISTS phase text,
  ADD COLUMN IF NOT EXISTS constraints text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS last_confirmed_at timestamptz;

-- ============================================================
-- 5. thread-specific fields
-- ============================================================

ALTER TABLE shenyu_mem_notes
  ADD COLUMN IF NOT EXISTS topic text,
  ADD COLUMN IF NOT EXISTS last_position text,
  ADD COLUMN IF NOT EXISTS open_questions text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS next_prompt text,
  ADD COLUMN IF NOT EXISTS thread_resolved boolean NOT NULL DEFAULT false;

-- ============================================================
-- 6. Constraints
-- ============================================================

-- importance range 0-5
ALTER TABLE shenyu_mem_notes
  DROP CONSTRAINT IF EXISTS shenyu_mem_notes_importance_range;
ALTER TABLE shenyu_mem_notes
  ADD CONSTRAINT shenyu_mem_notes_importance_range CHECK (importance >= 0 AND importance <= 5);

-- memory_kind allowed values (nullable for legacy rows)
ALTER TABLE shenyu_mem_notes
  DROP CONSTRAINT IF EXISTS shenyu_mem_notes_memory_kind_check;
ALTER TABLE shenyu_mem_notes
  ADD CONSTRAINT shenyu_mem_notes_memory_kind_check CHECK (
    memory_kind IS NULL
    OR memory_kind IN (
      'event', 'person_fact', 'social', 'trip', 'object', 'preference',
      'routine', 'promise', 'running_joke', 'thread'
    )
  );

-- v2 structured anchors are valid active triggers too.
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
      )
    )
  );

-- ============================================================
-- 7. GIN indexes for array fields
-- ============================================================

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_people_idx
  ON shenyu_mem_notes USING gin (people)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_places_idx
  ON shenyu_mem_notes USING gin (places)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_objects_idx
  ON shenyu_mem_notes USING gin (objects)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_keywords_idx
  ON shenyu_mem_notes USING gin (keywords)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_scene_tags_idx
  ON shenyu_mem_notes USING gin (scene_tags)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_trigger_scenarios_idx
  ON shenyu_mem_notes USING gin (trigger_scenarios)
  WHERE status = 'active';

-- ============================================================
-- 8. Partial indexes for common queries
-- ============================================================

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_memory_kind_idx
  ON shenyu_mem_notes (memory_kind)
  WHERE status = 'active' AND memory_kind IS NOT NULL;

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_resolved_idx
  ON shenyu_mem_notes (resolved)
  WHERE status = 'active' AND memory_kind = 'promise' AND resolved = false;

CREATE INDEX IF NOT EXISTS shenyu_mem_notes_promotion_score_idx
  ON shenyu_mem_notes (promotion_score DESC)
  WHERE status = 'active' AND promotion_score > 0;
