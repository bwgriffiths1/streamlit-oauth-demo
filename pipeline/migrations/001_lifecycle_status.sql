-- Migration 001: lifecycle_status, agenda_doc_hash, last_scraped_at, inactive agenda items
-- Idempotent — safe to re-run.

-- ─── meetings ──────────────────────────────────────────────────────────────

ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'discovered';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'meetings_lifecycle_status_check'
    ) THEN
        ALTER TABLE meetings
            ADD CONSTRAINT meetings_lifecycle_status_check
            CHECK (lifecycle_status IN (
                'discovered', 'agenda_posted', 'materials_posted',
                'summarized', 'approved'
            ));
    END IF;
END$$;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS agenda_doc_hash  TEXT;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS last_scraped_at  TIMESTAMPTZ;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS agenda_parsed_at TIMESTAMPTZ;

-- ─── agenda_items ──────────────────────────────────────────────────────────
-- `inactive` lets us soft-delete items that disappear on agenda re-parse
-- without losing their summaries.

ALTER TABLE agenda_items ADD COLUMN IF NOT EXISTS inactive BOOLEAN NOT NULL DEFAULT false;

-- ─── venues ────────────────────────────────────────────────────────────────
-- Track when a venue's calendar was last scraped — surfaces in the Add Meeting
-- screen + lets cron decide which venues to refresh.

ALTER TABLE venues ADD COLUMN IF NOT EXISTS last_scraped_at TIMESTAMPTZ;

-- ─── backfill lifecycle_status from observed data ──────────────────────────

UPDATE meetings m SET lifecycle_status = CASE
    WHEN EXISTS (
        SELECT 1 FROM summary_versions sv
        WHERE sv.entity_type = 'meeting'
          AND sv.entity_id = m.id
          AND sv.is_manual = true
          AND sv.status IN ('approved', 'draft')
    ) THEN 'approved'
    WHEN EXISTS (
        SELECT 1 FROM summary_versions sv
        WHERE sv.entity_type = 'meeting'
          AND sv.entity_id = m.id
          AND sv.status IN ('approved', 'draft')
          AND sv.created_by != 'autosave'
    ) THEN 'summarized'
    WHEN (SELECT COUNT(*) FROM documents d WHERE d.meeting_id = m.id) > 0
        THEN 'materials_posted'
    WHEN (SELECT COUNT(*) FROM agenda_items ai WHERE ai.meeting_id = m.id) > 0
        THEN 'agenda_posted'
    ELSE 'discovered'
END
WHERE lifecycle_status = 'discovered';   -- only backfill rows still at the default

-- ─── helpful indexes ───────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_meetings_lifecycle ON meetings (lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_meetings_date_lifecycle
    ON meetings (meeting_date, lifecycle_status);
