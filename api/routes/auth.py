"""Auth routes — local email/password login + logout."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from pipeline.auth import authenticate_user
from .. import schemas
from ..auth import clear_session_cookie, set_session_cookie

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


def _to_current_user(user: dict) -> schemas.CurrentUser:
    name = (user.get("name") or user.get("email") or "User").strip()
    parts = [p for p in name.split() if p]
    initials = (
        (parts[0][0] + parts[-1][0]).upper()
        if len(parts) >= 2
        else (parts[0][:2].upper() if parts else "U")
    )
    return schemas.CurrentUser(
        name=name,
        email=user.get("email", ""),
        initials=initials,
    )


@router.post("/login", response_model=schemas.CurrentUser)
def login(body: LoginRequest, response: Response) -> schemas.CurrentUser:
    user = authenticate_user(body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    set_session_cookie(response, user["email"])
    return _to_current_user(user)


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    clear_session_cookie(response)
    return {"ok": True}
