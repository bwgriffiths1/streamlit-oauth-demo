"""
pipeline/db.py — Postgres connection, schema bootstrap, and CRUD helpers.

DATABASE_URL is injected automatically by Railway when the Postgres addon
is attached. Set it locally in .env for development.
"""
import os
from pathlib import Path

import psycopg2
import psycopg2.extras

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meetings (
    id             SERIAL PRIMARY KEY,
    event_id       TEXT NOT NULL UNIQUE,
    all_event_ids  TEXT[],
    committee      TEXT NOT NULL,
    meeting_dates  DATE[],
    summary_status TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id             SERIAL PRIMARY KEY,
    meeting_id     INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    source_url     TEXT,
    file_type      TEXT,
    ceii_skipped   BOOLEAN DEFAULT FALSE,
    summary_status TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (meeting_id, filename)
);

CREATE TABLE IF NOT EXISTS document_summaries (
    id             SERIAL PRIMARY KEY,
    document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE UNIQUE,
    summary_text   TEXT NOT NULL,
    model_used     TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agenda_item_summaries (
    id             SERIAL PRIMARY KEY,
    meeting_id     INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    item_number    TEXT NOT NULL,
    item_title     TEXT,
    summary_text   TEXT NOT NULL,
    model_used     TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (meeting_id, item_number)
);

CREATE TABLE IF NOT EXISTS briefings (
    id             SERIAL PRIMARY KEY,
    meeting_id     INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE UNIQUE,
    briefing_text  TEXT NOT NULL,
    model_used     TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS initiatives (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    description    TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS initiative_tags (
    initiative_id  INTEGER NOT NULL REFERENCES initiatives(id) ON DELETE CASCADE,
    meeting_id     INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    tagged_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (initiative_id, meeting_id)
);

CREATE TABLE IF NOT EXISTS prompts (
    id             SERIAL PRIMARY KEY,
    slug           TEXT NOT NULL UNIQUE,
    content        TEXT NOT NULL,
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meeting_keywords (
    id          SERIAL PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    keyword     TEXT NOT NULL,
    source      TEXT DEFAULT 'ai',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (meeting_id, keyword)
);

CREATE INDEX IF NOT EXISTS idx_docs_meeting       ON documents(meeting_id);
CREATE INDEX IF NOT EXISTS idx_doc_sums_doc       ON document_summaries(document_id);
CREATE INDEX IF NOT EXISTS idx_item_sums_meeting  ON agenda_item_summaries(meeting_id);
CREATE INDEX IF NOT EXISTS idx_briefings_meeting  ON briefings(meeting_id);
CREATE INDEX IF NOT EXISTS idx_init_tags_meeting  ON initiative_tags(meeting_id);
CREATE INDEX IF NOT EXISTS idx_init_tags_init     ON initiative_tags(initiative_id);
CREATE INDEX IF NOT EXISTS idx_meetings_committee ON meetings(committee);
CREATE INDEX IF NOT EXISTS idx_keywords_meeting   ON meeting_keywords(meeting_id);
"""

# Migrations for columns added after initial schema deployment.
# ALTER TABLE ... ADD COLUMN IF NOT EXISTS is idempotent.
_MIGRATIONS_SQL = """
ALTER TABLE document_summaries    ADD COLUMN IF NOT EXISTS user_text       TEXT;
ALTER TABLE document_summaries    ADD COLUMN IF NOT EXISTS user_edited_at  TIMESTAMPTZ;
ALTER TABLE agenda_item_summaries ADD COLUMN IF NOT EXISTS user_text       TEXT;
ALTER TABLE agenda_item_summaries ADD COLUMN IF NOT EXISTS user_edited_at  TIMESTAMPTZ;
ALTER TABLE briefings             ADD COLUMN IF NOT EXISTS user_text       TEXT;
ALTER TABLE briefings             ADD COLUMN IF NOT EXISTS user_edited_at  TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS edit_versions (
    id            SERIAL PRIMARY KEY,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_edit_versions_entity
    ON edit_versions(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS agenda_items (
    id          SERIAL PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    item_id     TEXT NOT NULL,
    title       TEXT,
    prefix      TEXT,
    depth       INTEGER DEFAULT 0,
    parent_id   TEXT,
    seq         INTEGER DEFAULT 0,
    auto_sub    BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (meeting_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_agenda_items_meeting ON agenda_items(meeting_id);
"""


def get_conn():
    """Return a new psycopg2 connection with RealDictCursor."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def bootstrap():
    """
    Create all tables (if not exists), run column migrations, and seed any
    prompt files not yet in the DB. Call once at app startup (app.py).

    Uses a PostgreSQL advisory lock to prevent deadlocks when multiple
    Streamlit workers start concurrently.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(42)")
            try:
                cur.execute(_SCHEMA_SQL)
                cur.execute(_MIGRATIONS_SQL)
                _seed_missing_prompts(conn)
                conn.commit()
            finally:
                cur.execute("SELECT pg_advisory_unlock(42)")
    print("DB bootstrap complete.")


def _seed_missing_prompts(conn):
    """Insert any prompt .md file whose slug is not already in the DB."""
    prompts_dir = Path(__file__).parent.parent / "prompts"
    with conn.cursor() as cur:
        for p in sorted(prompts_dir.glob("*.md")):
            slug = p.stem
            content = p.read_text(encoding="utf-8")
            cur.execute(
                "INSERT INTO prompts (slug, content) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (slug, content),
            )


def _seed_prompts_from_disk(conn):
    """Alias kept for backward compatibility — delegates to _seed_missing_prompts."""
    _seed_missing_prompts(conn)


# ── Meetings ──────────────────────────────────────────────────────────────────

def upsert_meeting(event_id: str, committee: str, meeting_dates: list,
                   all_event_ids: list | None = None) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meetings (event_id, committee, meeting_dates, all_event_ids, updated_at)
                VALUES (%s, %s, %s::date[], %s, NOW())
                ON CONFLICT (event_id) DO UPDATE
                  SET committee      = EXCLUDED.committee,
                      meeting_dates  = EXCLUDED.meeting_dates,
                      all_event_ids  = EXCLUDED.all_event_ids,
                      updated_at     = NOW()
                RETURNING id
                """,
                (event_id, committee, meeting_dates, all_event_ids or []),
            )
            meeting_id = cur.fetchone()["id"]
        conn.commit()
    return meeting_id


def get_meeting_by_event_id(event_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM meetings WHERE event_id = %s", (event_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def get_all_meetings() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM meetings ORDER BY meeting_dates[1] DESC NULLS LAST"
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def set_meeting_summary_status(meeting_id: int, status: str | None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE meetings SET summary_status=%s, updated_at=NOW() WHERE id=%s",
                (status, meeting_id),
            )
        conn.commit()


# ── Documents ─────────────────────────────────────────────────────────────────

def upsert_document(meeting_id: int, filename: str, source_url: str | None,
                    file_type: str | None, ceii_skipped: bool = False) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents
                  (meeting_id, filename, source_url, file_type, ceii_skipped, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (meeting_id, filename) DO UPDATE
                  SET source_url   = EXCLUDED.source_url,
                      file_type    = EXCLUDED.file_type,
                      ceii_skipped = EXCLUDED.ceii_skipped,
                      updated_at   = NOW()
                RETURNING id
                """,
                (meeting_id, filename, source_url, file_type, ceii_skipped),
            )
            doc_id = cur.fetchone()["id"]
        conn.commit()
    return doc_id


def get_documents_for_meeting(meeting_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM documents WHERE meeting_id = %s ORDER BY filename",
                (meeting_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def set_document_summary_status(document_id: int, status: str | None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET summary_status=%s, updated_at=NOW() WHERE id=%s",
                (status, document_id),
            )
        conn.commit()


# ── Document Summaries ────────────────────────────────────────────────────────

def upsert_document_summary(document_id: int, summary_text: str,
                            model_used: str | None = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO document_summaries (document_id, summary_text, model_used, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (document_id) DO UPDATE
                  SET summary_text = EXCLUDED.summary_text,
                      model_used   = EXCLUDED.model_used,
                      updated_at   = NOW()
                """,
                (document_id, summary_text, model_used),
            )
        conn.commit()


def get_document_summary(document_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM document_summaries WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_all_document_summaries_for_meeting(meeting_id: int) -> list[dict]:
    """Returns rows with both document_summaries fields and documents.filename."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ds.*, d.filename, d.source_url, d.file_type, d.ceii_skipped
                FROM document_summaries ds
                JOIN documents d ON d.id = ds.document_id
                WHERE d.meeting_id = %s
                ORDER BY d.filename
                """,
                (meeting_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Agenda Items (skeleton) ───────────────────────────────────────────────────

def upsert_agenda_items(meeting_id: int, items: list[dict]) -> None:
    """Replace all agenda items for a meeting (delete + re-insert)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agenda_items WHERE meeting_id = %s", (meeting_id,))
            for seq, item in enumerate(items):
                parts = item["item_id"].split(".")
                depth = len(parts) - 1
                parent_id = ".".join(parts[:-1]) if len(parts) > 1 else None
                cur.execute(
                    """
                    INSERT INTO agenda_items
                      (meeting_id, item_id, title, prefix, depth, parent_id, seq, auto_sub)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        meeting_id,
                        item["item_id"],
                        item.get("title"),
                        item.get("prefix"),
                        depth,
                        parent_id,
                        seq,
                        bool(item.get("auto_sub", False)),
                    ),
                )
        conn.commit()


def get_agenda_items(meeting_id: int) -> list[dict]:
    """Return agenda items for a meeting ordered by seq."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM agenda_items WHERE meeting_id = %s ORDER BY seq",
                (meeting_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Agenda Item Summaries ─────────────────────────────────────────────────────

def upsert_agenda_item_summary(meeting_id: int, item_number: str,
                               summary_text: str, item_title: str | None = None,
                               model_used: str | None = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agenda_item_summaries
                  (meeting_id, item_number, item_title, summary_text, model_used, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (meeting_id, item_number) DO UPDATE
                  SET item_title   = EXCLUDED.item_title,
                      summary_text = EXCLUDED.summary_text,
                      model_used   = EXCLUDED.model_used,
                      updated_at   = NOW()
                """,
                (meeting_id, item_number, item_title, summary_text, model_used),
            )
        conn.commit()


def get_agenda_item_summary(meeting_id: int, item_number: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM agenda_item_summaries WHERE meeting_id=%s AND item_number=%s",
                (meeting_id, item_number),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def clear_agenda_item_summaries(meeting_id: int) -> None:
    """Delete all agenda item summaries for a meeting (called before re-running rollup)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agenda_item_summaries WHERE meeting_id = %s",
                (meeting_id,),
            )
        conn.commit()


def get_all_agenda_item_summaries_for_meeting(meeting_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM agenda_item_summaries WHERE meeting_id=%s ORDER BY item_number",
                (meeting_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Briefings ─────────────────────────────────────────────────────────────────

def upsert_briefing(meeting_id: int, briefing_text: str,
                    model_used: str | None = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO briefings (meeting_id, briefing_text, model_used, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (meeting_id) DO UPDATE
                  SET briefing_text = EXCLUDED.briefing_text,
                      model_used    = EXCLUDED.model_used,
                      updated_at    = NOW()
                """,
                (meeting_id, briefing_text, model_used),
            )
        conn.commit()


def get_briefing_for_meeting(meeting_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM briefings WHERE meeting_id = %s", (meeting_id,)
            )
            row = cur.fetchone()
    return dict(row) if row else None


# ── Initiatives ───────────────────────────────────────────────────────────────

def create_initiative(name: str, description: str | None = None) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO initiatives (name, description) VALUES (%s, %s) RETURNING id",
                (name, description),
            )
            init_id = cur.fetchone()["id"]
        conn.commit()
    return init_id


def get_all_initiatives() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM initiatives ORDER BY name")
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def update_initiative(initiative_id: int, name: str,
                      description: str | None = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE initiatives SET name=%s, description=%s, updated_at=NOW() WHERE id=%s",
                (name, description, initiative_id),
            )
        conn.commit()


def delete_initiative(initiative_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM initiatives WHERE id=%s", (initiative_id,))
        conn.commit()


def tag_meeting(initiative_id: int, meeting_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO initiative_tags (initiative_id, meeting_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (initiative_id, meeting_id),
            )
        conn.commit()


def untag_meeting(initiative_id: int, meeting_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM initiative_tags WHERE initiative_id=%s AND meeting_id=%s",
                (initiative_id, meeting_id),
            )
        conn.commit()


def get_meetings_for_initiative(initiative_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.* FROM meetings m
                JOIN initiative_tags it ON it.meeting_id = m.id
                WHERE it.initiative_id = %s
                ORDER BY m.meeting_dates[1] DESC NULLS LAST
                """,
                (initiative_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_initiatives_for_meeting(meeting_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT i.* FROM initiatives i
                JOIN initiative_tags it ON it.initiative_id = i.id
                WHERE it.meeting_id = %s
                ORDER BY i.name
                """,
                (meeting_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── Summary status reset ──────────────────────────────────────────────────────

def reset_meeting_summary_status(meeting_id: int):
    """Clear summary_status on meeting and all its documents so pipeline re-runs."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE meetings SET summary_status=NULL, updated_at=NOW() WHERE id=%s",
                (meeting_id,),
            )
            cur.execute(
                "UPDATE documents SET summary_status=NULL, updated_at=NOW() WHERE meeting_id=%s",
                (meeting_id,),
            )
        conn.commit()


# ── Prompts ───────────────────────────────────────────────────────────────────

# ── Meeting Keywords ──────────────────────────────────────────────────────────

def get_keywords_for_meeting(meeting_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM meeting_keywords WHERE meeting_id=%s ORDER BY source, keyword",
                (meeting_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def set_ai_keywords(meeting_id: int, keywords: list[str]):
    """Replace all AI-sourced keywords for a meeting with the given list."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meeting_keywords WHERE meeting_id=%s AND source='ai'",
                (meeting_id,),
            )
            for kw in keywords:
                kw = kw.strip()
                if kw:
                    cur.execute(
                        """INSERT INTO meeting_keywords (meeting_id, keyword, source)
                           VALUES (%s, %s, 'ai') ON CONFLICT DO NOTHING""",
                        (meeting_id, kw),
                    )
        conn.commit()


def add_user_keyword(meeting_id: int, keyword: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO meeting_keywords (meeting_id, keyword, source)
                   VALUES (%s, %s, 'user') ON CONFLICT DO NOTHING""",
                (meeting_id, keyword.strip()),
            )
        conn.commit()


def delete_keyword(meeting_id: int, keyword: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meeting_keywords WHERE meeting_id=%s AND keyword=%s",
                (meeting_id, keyword),
            )
        conn.commit()


# ── User edits on summaries ───────────────────────────────────────────────────

def update_doc_summary_user_text(document_id: int, user_text: str | None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE document_summaries
                   SET user_text=%s, user_edited_at=CASE WHEN %s IS NULL THEN NULL ELSE NOW() END,
                       updated_at=NOW()
                   WHERE document_id=%s""",
                (user_text, user_text, document_id),
            )
        conn.commit()


def update_item_summary_user_text(meeting_id: int, item_number: str, user_text: str | None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE agenda_item_summaries
                   SET user_text=%s, user_edited_at=CASE WHEN %s IS NULL THEN NULL ELSE NOW() END,
                       updated_at=NOW()
                   WHERE meeting_id=%s AND item_number=%s""",
                (user_text, user_text, meeting_id, item_number),
            )
        conn.commit()


def update_briefing_user_text(meeting_id: int, user_text: str | None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE briefings
                   SET user_text=%s, user_edited_at=CASE WHEN %s IS NULL THEN NULL ELSE NOW() END,
                       updated_at=NOW()
                   WHERE meeting_id=%s""",
                (user_text, user_text, meeting_id),
            )
        conn.commit()


# ── Prompts ───────────────────────────────────────────────────────────────────

def get_all_prompts() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM prompts ORDER BY slug")
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_prompt_by_slug(slug: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM prompts WHERE slug = %s", (slug,))
            row = cur.fetchone()
    return dict(row) if row else None


def update_prompt(slug: str, content: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE prompts SET content=%s, updated_at=NOW() WHERE slug=%s",
                (content, slug),
            )
        conn.commit()


# ── Edit Versions ────────────────────────────────────────────────────────────

def save_edit_version(entity_type: str, entity_id: str, content: str) -> int:
    """Snapshot content before overwriting. Returns the new version id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO edit_versions (entity_type, entity_id, content)
                   VALUES (%s, %s, %s) RETURNING id""",
                (entity_type, entity_id, content),
            )
            vid = cur.fetchone()["id"]
        conn.commit()
    return vid


def get_edit_versions(entity_type: str, entity_id: str) -> list[dict]:
    """Return all versions for an entity, newest first."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM edit_versions
                   WHERE entity_type=%s AND entity_id=%s
                   ORDER BY created_at DESC""",
                (entity_type, entity_id),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_edit_version_by_id(version_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM edit_versions WHERE id=%s", (version_id,))
            row = cur.fetchone()
    return dict(row) if row else None
