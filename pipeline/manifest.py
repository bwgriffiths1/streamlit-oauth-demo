"""
pipeline/manifest.py — Meeting and document registration in Postgres.

Replaces the old JSON manifest file I/O. All data is now stored in the DB.
"""
from __future__ import annotations

import pipeline.db as db


def upsert_meeting(
    primary_event_id: str,
    all_event_ids: list[str],
    committee_name: str,
    meeting_dates: list[str],   # ISO format: ["2026-04-14", ...]
) -> int:
    """
    Create or update the meeting row in Postgres.
    Returns the meeting's integer primary key (meeting_id).
    """
    return db.upsert_meeting(
        event_id=primary_event_id,
        committee=committee_name,
        meeting_dates=meeting_dates,
        all_event_ids=all_event_ids,
    )


def upsert_document(
    meeting_id: int,
    filename: str,
    source_url: str | None,
    file_type: str | None,
    ceii_skipped: bool = False,
) -> int:
    """
    Create or update a document row for a meeting.
    Returns the document's integer primary key (document_id).
    """
    return db.upsert_document(
        meeting_id=meeting_id,
        filename=filename,
        source_url=source_url,
        file_type=file_type,
        ceii_skipped=ceii_skipped,
    )


def get_meeting(event_id: str) -> dict | None:
    """Return the meeting dict for a given event_id, or None."""
    return db.get_meeting_by_event_id(event_id)


def set_document_status(document_id: int, status: str | None):
    """Update a document's summary_status."""
    db.set_document_summary_status(document_id, status)


def set_meeting_complete(meeting_id: int):
    """Mark a meeting's summary pipeline as complete."""
    db.set_meeting_summary_status(meeting_id, "complete")
