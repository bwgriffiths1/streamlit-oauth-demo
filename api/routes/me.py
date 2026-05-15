"""Current user — for the sidebar user chip.

v1: returns a stubbed user. Wire to pipeline.auth.get_current_user once we move
to a shared cookie session.
"""
from __future__ import annotations

from fastapi import APIRouter
from .. import schemas

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=schemas.CurrentUser)
def me() -> schemas.CurrentUser:
    return schemas.CurrentUser(
        name="Ben Griffiths",
        email="ben@poolside.io",
        initials="BG",
    )
