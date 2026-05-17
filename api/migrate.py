"""Run pipeline/migrations/*.sql at startup. Idempotent — every migration
uses IF NOT EXISTS / DO $$ guards so re-running is safe.
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg2


_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "pipeline" / "migrations"


def run_migrations() -> list[str]:
    """Execute every .sql in pipeline/migrations/, sorted by filename.
    Returns the list of files run.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set — cannot run migrations")
    if not _MIGRATIONS_DIR.exists():
        return []

    files = sorted(f for f in _MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        return []

    conn = psycopg2.connect(url)
    try:
        with conn:
            with conn.cursor() as cur:
                for f in files:
                    cur.execute(f.read_text())
    finally:
        conn.close()
    return [f.name for f in files]
