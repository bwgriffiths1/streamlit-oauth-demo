"""Current user — for the sidebar user chip."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import schemas
from ..auth import current_user

router = APIRouter(prefix="/api", tags=["me"])


def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return "U"


@router.get("/me", response_model=schemas.CurrentUser)
def me(user: dict = Depends(current_user)) -> schemas.CurrentUser:
    name = (user.get("name") or user.get("email") or "User").strip()
    return schemas.CurrentUser(
        name=name,
        email=user.get("email", ""),
        initials=_initials(name),
    )
