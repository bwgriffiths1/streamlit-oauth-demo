-- Background summarization jobs.
-- One row per /api/meetings/{id}/summarize invocation. Updated in place by
-- the daemon thread that runs the pipeline; polled from the frontend.

CREATE TABLE IF NOT EXISTS summarize_jobs (
    id                       SERIAL PRIMARY KEY,
    meeting_id               INT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    status                   TEXT NOT NULL DEFAULT 'queued',     -- queued | running | complete | failed
    progress_text            TEXT NOT NULL DEFAULT '',           -- latest line from progress_fn
    level1_done              INT NOT NULL DEFAULT 0,
    level2_done              INT NOT NULL DEFAULT 0,
    level3_done              BOOLEAN NOT NULL DEFAULT false,
    input_tokens             BIGINT NOT NULL DEFAULT 0,
    output_tokens            BIGINT NOT NULL DEFAULT 0,
    cost_usd                 NUMERIC(10, 4) NOT NULL DEFAULT 0,
    estimated_cost_usd       NUMERIC(10, 4),
    estimated_input_tokens   BIGINT,
    estimated_output_tokens  BIGINT,
    error                    TEXT,
    started_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at              TIMESTAMPTZ,
    created_by               TEXT
);

-- Fast "is there an active job for this meeting?" lookup.
CREATE INDEX IF NOT EXISTS idx_summarize_jobs_meeting_status
    ON summarize_jobs (meeting_id, status);
