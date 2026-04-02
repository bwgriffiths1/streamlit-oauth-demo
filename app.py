"""
app.py — Meeting Summaries with Google OIDC + Local DB Authentication
"""
import os
import streamlit as st

st.set_page_config(
    page_title="Meeting Summaries",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

from pipeline.auth import (
    is_authenticated, get_current_user,
    authenticate_user, login_local_user, logout_local_user,
)

# --- Landing page (unauthenticated) ---
if not is_authenticated():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("Meeting Summaries")
        st.markdown(
            "ISO-NE and NYISO meeting summaries powered by AI. "
            "Log in to continue."
        )
        st.divider()

        tab_google, tab_local = st.tabs(["Google", "Email & Password"])

        with tab_google:
            st.markdown("Sign in with your Google account.")
            if st.button("Log in with Google", type="primary",
                         use_container_width=True):
                st.login()

        with tab_local:
            with st.form("local_login_form"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Log in", type="primary",
                                                  use_container_width=True)
                if submitted:
                    if email and password:
                        user = authenticate_user(email, password)
                        if user:
                            login_local_user(user)
                            st.rerun()
                        else:
                            st.error("Invalid email or password.")
                    else:
                        st.warning("Please enter both email and password.")
    st.stop()

# --- Authenticated: sidebar user info + logout ---
current_user = get_current_user()

with st.sidebar:
    st.markdown(f"**{current_user['name']}**")
    if current_user["email"]:
        st.caption(current_user["email"])
    st.divider()
    if st.button("Log out", width="stretch"):
        if current_user["provider"] == "google":
            st.logout()
        else:
            logout_local_user()
            st.rerun()

# --- DB bootstrap ---
from dotenv import load_dotenv
load_dotenv()

try:
    import pipeline.db_new as _db
    _db.get_venues()          # lightweight connection check
except Exception as _e:
    st.error(f"Database connection failed: {_e}\n\nCheck DATABASE_URL.")
    st.stop()

# --- Navigation ---
pg = st.navigation(
    [
        st.Page("v2_pages/overview.py",       title="Overview",       icon="🗓️"),
        st.Page("v2_pages/meetings.py",       title="Meetings",       icon="📋"),
        st.Page("v2_pages/editor.py",         title="Editor",         icon="📝"),
        st.Page("v2_pages/bulk_summarize.py", title="Bulk Summarize", icon="⚡"),
        st.Page("v2_pages/ingest_meeting.py", title="Add Meeting",    icon="➕"),
        st.Page("v2_pages/agenda_debug.py",   title="Agenda Debug",   icon="🔍"),
        st.Page("v2_pages/prompt_library.py", title="Prompt Library", icon="✏️"),
        st.Page("v2_pages/parse_compare.py",  title="Parse Compare",  icon="🔀"),
        st.Page("v2_pages/settings.py",       title="Settings",       icon="⚙️"),
        st.Page("v2_pages/nyiso_viewer.py",   title="NYISO",          icon="🏙️"),
        st.Page("v2_pages/pdf_summarizer.py", title="PDF Summarizer", icon="📄"),
    ]
)
pg.run()
