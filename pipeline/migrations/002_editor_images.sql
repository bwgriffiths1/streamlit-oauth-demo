-- Migration 002: editor_images
-- Stores screenshots / images pasted into the rich-text editor for an
-- agenda item or meeting briefing. Referenced from the markdown via
-- a URL like /api/editor-images/{id}.

CREATE TABLE IF NOT EXISTS editor_images (
    id          SERIAL PRIMARY KEY,
    meeting_id  INT REFERENCES meetings(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('meeting', 'agenda_item')),
    entity_id   INT NOT NULL,
    filename    TEXT,
    mime_type   TEXT NOT NULL DEFAULT 'image/png',
    data        BYTEA NOT NULL,
    width       INT,
    height      INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_editor_images_entity ON editor_images (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_editor_images_meeting ON editor_images (meeting_id);
