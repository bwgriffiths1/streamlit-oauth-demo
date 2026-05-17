"""FastAPI-native session auth.

Issues an HTTP-only signed cookie after a successful local password check.
Mirrors the cookie shape used by pipeline/auth.py so the same DB users work
in both apps. OAuth providers can hydrate the same cookie later.

TODO: only `/api/me`, `/api/admin/config`, and `/api/admin/ingest-by-url`
currently require auth via `current_user`. Existing meeting/briefing/admin
routes still respond unauthenticated. Before exposing this beyond localhost,
add `Depends(current_user)` to every protected router (or wire a global
middleware) and set `POOLSIDE_COOKIE_SECURE=1` so the cookie is HTTPS-only.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import Cookie, HTTPException, Response, status

from pipeline.auth import get_user_by_email

SESSION_COOKIE = "poolside_session"
_MAX_AGE = 7 * 24 * 3600  # 1 week


def _secret() -> bytes:
    return os.environ.get("POOLSIDE_SESSION_SECRET", "dev-secret-change-me").encode()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_session_cookie(email: str) -> str:
    expiry = int(time.time()) + _MAX_AGE
    payload = f"{email}|{expiry}"
    return f"{payload}|{_sign(payload)}"


def verify_session_cookie(raw: str) -> str | None:
    """Return email if the cookie is valid and unexpired, else None."""
    if not raw:
        return None
    parts = raw.split("|")
    if len(parts) != 3:
        return None
    email, expiry_str, sig = parts
    payload = f"{email}|{expiry_str}"
    if not hmac.compare_digest(_sign(payload), sig):
        return None
    try:
        if int(expiry_str) < int(time.time()):
            return None
    except ValueError:
        return None
    return email


def set_session_cookie(response: Response, email: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=make_session_cookie(email),
        max_age=_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("POOLSIDE_COOKIE_SECURE", "0") == "1",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def current_user(poolside_session: str | None = Cookie(default=None)) -> dict:
    """FastAPI dependency: returns the authenticated user dict or 401s."""
    email = verify_session_cookie(poolside_session or "")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = get_user_by_email(email)
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user
