"""Briefing reader endpoint — fetch stored markdown, parse to typed AST."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pipeline import db_new as db
from .. import briefing_parser, schemas

router = APIRouter(prefix="/api/meetings", tags=["briefings"])


@router.get("/{meeting_id}/briefing", response_model=schemas.Briefing)
def get_briefing(meeting_id: int) -> schemas.Briefing:
    meeting = db.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    summary = db.get_current_summary("meeting", meeting_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="No briefing for this meeting")

    md = summary.get("detailed") or summary.get("one_line") or ""

    venue_short = meeting.get("venue_short") or meeting.get("venue") or ""
    venue_name = meeting.get("venue_name") or venue_short
    location = meeting.get("location") or ""
    type_name = meeting.get("type_name") or ""

    meta = {
        "title": f"{type_name} — {meeting.get('meeting_date', '')}",
        "subtitle": f"{venue_name} · {location}",
        "headline": summary.get("one_line") or "",
        "generated_at": str(summary.get("created_at", "")),
        "model": summary.get("model") or summary.get("created_by") or "",
        "word_count": 0,
        "reading_time": 0,
    }

    return briefing_parser.parse_briefing_markdown(md, meta)
