"""Meetings endpoints — wire pipeline/db_new.py to the frontend contract."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from pipeline import db_new as db
from .. import adapters, schemas

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.get("", response_model=list[schemas.MeetingListItem])
def list_meetings(
    past_days: int = Query(730, ge=0, le=3650),
    future_days: int = Query(365, ge=0, le=3650),
    venue: str | None = Query(None),
) -> list[schemas.MeetingListItem]:
    rows = db.list_meetings_overview(
        venue_short=venue, past_days=past_days, future_days=future_days
    )
    out: list[schemas.MeetingListItem] = []
    for row in rows:
        # tags: pull from tag_links via meeting
        try:
            tag_rows = db.get_tags_for_entity("meeting", row["id"])
            tags = [t["name"] for t in tag_rows]
        except Exception:
            tags = []
        # item_count: rough count of agenda rows
        try:
            agenda_rows = db.get_agenda_items(row["id"])
            item_count = len(agenda_rows)
        except Exception:
            item_count = 0
        out.append(adapters.meeting_list_row(row, tags=tags, item_count=item_count))
    return out


@router.get("/{meeting_id}", response_model=schemas.MeetingDetail)
def get_meeting(meeting_id: int) -> schemas.MeetingDetail:
    row = db.get_meeting(meeting_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Idempotently materialize any missing parent items (e.g. "7" when only
    # 7.a–7.l exist) into real DB rows so they can be edited.
    adapters.materialize_missing_parents(meeting_id)

    # Backfill fields list_meetings_overview gives us but get_meeting may not.
    docs = db.get_documents_for_meeting(meeting_id)
    has_summary = bool(db.get_current_summary("meeting", meeting_id))
    enriched = {
        **row,
        "venue_short": row.get("venue_short") or row.get("venue"),
        "type_short": row.get("type_short"),
        "type_name": row.get("type_name"),
        "doc_count": len(docs),
        "has_summary": has_summary,
        "has_manual": False,  # TODO: derive from summary_versions.is_manual
    }
    try:
        tags = [t["name"] for t in db.get_tags_for_entity("meeting", meeting_id)]
    except Exception:
        tags = []
    agenda_rows = db.get_agenda_items(meeting_id)
    item_count = len(agenda_rows)
    base = adapters.meeting_list_row(enriched, tags=tags, item_count=item_count)

    summary = db.get_current_summary("meeting", meeting_id) or {}

    agenda_items: list[schemas.AgendaItem] = []
    for ar in agenda_rows:
        doc_rows = db.get_documents_for_item(ar["id"])
        item_docs = [adapters.document_row(d) for d in doc_rows]
        item_summary = db.get_current_summary("agenda_item", ar["id"])
        agenda_items.append(adapters.agenda_item_row(ar, item_docs, item_summary))

    return schemas.MeetingDetail(
        **base.model_dump(),
        one_line=summary.get("one_line", "") or "",
        agenda=adapters.synthesize_missing_parents(agenda_items),
    )


@router.get("/{meeting_id}/agenda", response_model=list[schemas.AgendaItem])
def get_meeting_agenda(meeting_id: int) -> list[schemas.AgendaItem]:
    items: list[schemas.AgendaItem] = []
    for ar in db.get_agenda_items(meeting_id):
        doc_rows = db.get_documents_for_item(ar["id"])
        docs = [adapters.document_row(d) for d in doc_rows]
        summary = db.get_current_summary("agenda_item", ar["id"])
        items.append(adapters.agenda_item_row(ar, docs, summary))
    return adapters.synthesize_missing_parents(items)
