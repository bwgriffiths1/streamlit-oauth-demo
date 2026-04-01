"""
app.py — Meeting Summaries with Google OIDC Authentication
"""
import os
import streamlit as st

st.set_page_config(
    page_title="Meeting Summaries",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Landing page (unauthenticated) ---
if not st.user.is_logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("Meeting Summaries")
        st.markdown(
            "ISO-NE and NYISO meeting summaries powered by AI. "
            "Log in with your Google account to continue."
        )
        st.divider()
        if st.button("Log in with Google", type="primary", width="stretch"):
            st.login()
    st.stop()

# --- Authenticated: sidebar user info + logout ---
user_name = st.user.get("name", "User")
user_email = st.user.get("email", "")

with st.sidebar:
    st.markdown(f"**{user_name}**")
    if user_email:
        st.caption(user_email)
    st.divider()
    if st.button("Log out", width="stretch"):
        st.logout()

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
