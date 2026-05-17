"""Background-summarization job endpoints.

The job rows are written by the daemon thread in api/routes/meetings.py.
These routes are read-only: poll a job by id, or look up the active job
(if any) for a meeting.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from pipeline import db_new as db
from ..auth import current_user

router = APIRouter(prefix="/api", tags=["jobs"])


def _serialize_job(row: dict) -> dict[str, Any]:
    """Convert a summarize_jobs row to a JSON-safe dict."""
    if not row:
        return {}
    out = dict(row)
    # Postgres NUMERIC / TIMESTAMPTZ → strings the JSON encoder handles natively
    for k in ("cost_usd", "estimated_cost_usd"):
        if out.get(k) is not None:
            out[k] = float(out[k])
    for k in ("started_at", "finished_at"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat() if hasattr(out[k], "isoformat") else str(out[k])
    return out


@router.get("/jobs/{job_id}")
def get_job(job_id: int, _: dict = Depends(current_user)) -> dict[str, Any]:
    with db._conn() as conn:
        with db._cursor(conn) as cur:
            cur.execute("SELECT * FROM summarize_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(dict(row))


@router.get("/meetings/{meeting_id}/active-job")
def get_active_job(
    meeting_id: int,
    _: dict = Depends(current_user),
) -> dict[str, Any] | None:
    """Return the most recent queued/running job for this meeting, or null."""
    with db._conn() as conn:
        with db._cursor(conn) as cur:
            cur.execute(
                """SELECT * FROM summarize_jobs
                    WHERE meeting_id = %s
                      AND status IN ('queued', 'running')
                 ORDER BY started_at DESC
                    LIMIT 1""",
                (meeting_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return _serialize_job(dict(row))
