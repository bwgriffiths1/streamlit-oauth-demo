"""
pipeline/auth.py — Local DB authentication + unified auth helpers.

Provides password hashing, user CRUD, and a session abstraction that works
for both Google OIDC (via st.login) and local email/password login.
"""

import bcrypt
import streamlit as st

from pipeline.db_new import _conn, _cursor

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

# Pre-computed dummy hash so authenticate_user takes constant time
# even when the email does not exist (prevents timing-based enumeration).
_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode("utf-8")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def get_user_by_email(email: str) -> dict | None:
    with _conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT * FROM app_users WHERE email = %s",
                (email,),
            )
            return cur.fetchone()


def create_user(email: str, name: str, password: str,
                auth_provider: str = "local") -> dict:
    pw_hash = hash_password(password)
    with _conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                """INSERT INTO app_users (email, name, password_hash, auth_provider)
                   VALUES (%s, %s, %s, %s)
                   RETURNING *""",
                (email, name, pw_hash, auth_provider),
            )
            return cur.fetchone()


def update_last_login(email: str) -> None:
    with _conn() as conn:
        with _cursor(conn) as cur:
            cur.execute(
                "UPDATE app_users SET last_login = NOW() WHERE email = %s",
                (email,),
            )


def authenticate_user(email: str, password: str) -> dict | None:
    """Verify credentials. Returns user dict on success, None on failure."""
    user = get_user_by_email(email)
    if user is None:
        # Constant-time: still run a bcrypt check so timing doesn't leak
        # whether the email exists.
        verify_password(password, _DUMMY_HASH)
        return None
    if not user.get("is_active", True):
        return None
    if not user.get("password_hash"):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    update_last_login(email)
    return user


# ---------------------------------------------------------------------------
# Unified session helpers
# ---------------------------------------------------------------------------

def is_authenticated() -> bool:
    """True if logged in via Google OIDC or local DB."""
    if st.user.is_logged_in:
        return True
    return st.session_state.get("local_authenticated", False)


def get_current_user() -> dict:
    """Return {name, email, provider} for the authenticated user."""
    if st.user.is_logged_in:
        return {
            "name": st.user.get("name", "User"),
            "email": st.user.get("email", ""),
            "provider": "google",
        }
    return {
        "name": st.session_state.get("user_name", "User"),
        "email": st.session_state.get("user_email", ""),
        "provider": "local",
    }


def login_local_user(user: dict) -> None:
    """Set session state after successful local authentication."""
    st.session_state["local_authenticated"] = True
    st.session_state["user_name"] = user["name"]
    st.session_state["user_email"] = user["email"]


def logout_local_user() -> None:
    """Clear local auth session state."""
    for key in ("local_authenticated", "user_name", "user_email"):
        st.session_state.pop(key, None)
