"""Ingest endpoints — scrape preview, run, recent jobs, SSE log stream.

v1 is intentionally minimal: scrape preview returns a fixed list (production
scraper is invoked by the user from the Streamlit side until we move it
behind a job queue); /api/ingest/jobs returns the most recent meetings
ordered by created_at as a stand-in until a job log table is added.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from pipeline import db_new as db

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.get("/jobs")
def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    # No real job log table yet — surface recently-ingested meetings as a stand-in.
    rows = db.list_meetings_overview(past_days=730, future_days=0)
    # Only show meetings that have actually been ingested (docs > 0).
    rows = [r for r in rows if (r.get("doc_count") or 0) > 0]
    rows = sorted(rows, key=lambda r: r.get("meeting_date") or "", reverse=True)[:limit]
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": f"ing-{r['id']}",
            "meeting_id": r["id"],
            "status": "complete",
            "started": str(r.get("meeting_date") or ""),
            "label": f"{r.get('venue_short')} {r.get('type_short')} {r.get('meeting_date')}",
            "docs": r.get("doc_count") or 0,
            "agenda_items": 0,
        })
    return out


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str) -> StreamingResponse:
    """SSE stream of ingest log lines.

    v1: returns a canned sequence of demo lines on a 280ms cadence — wire
    to the real ingest pipeline by feeding lines into a per-job asyncio.Queue
    from pipeline/ingest.py.
    """
    async def gen():
        lines = [
            "→ Scraping ISO-NE Markets Committee calendar…",
            "  found 1 new meeting (2026-06-10)",
            "→ Fetching event documents…",
            "  17 documents enumerated",
            "→ Downloading documents (parallel × 6)…",
            "  ✓ 17/17 downloaded · 142.4 MB",
            "→ Parsing agenda from Agenda.pdf (LLM)…",
            "  detected 13 items, 4 votes scheduled",
            "→ Building manifests…",
            "✓ Done — 1 meeting ingested.",
        ]
        for line in lines:
            yield f"data: {line}\n\n"
            await asyncio.sleep(0.28)
        yield "event: done\ndata: ok\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
