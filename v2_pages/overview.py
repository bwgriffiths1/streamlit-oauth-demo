"""
v2_pages/overview.py — High-level meeting calendar with status pills.
Click any row to jump to that meeting in the Meetings page.
"""
from datetime import date

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import pipeline.db_new as db

st.set_page_config(page_title="Overview", layout="wide")
st.title("Meeting Overview")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_date(row: dict) -> str:
    """Format meeting date range: 'Apr 14, 2026' or 'Apr 14–16, 2026'."""
    start: date = row["meeting_date"]
    end: date | None = row.get("end_date")
    if not end or end == start:
        return start.strftime("%b %-d, %Y")
    if start.month == end.month and start.year == end.year:
        return f"{start.strftime('%b %-d')}–{end.day}, {start.year}"
    return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}"


def _status_pill(row: dict) -> str:
    if row["has_manual"]:
        return "🟣 Updated"
    if row["has_summary"]:
        return "🟢 Summarized"
    if row["doc_count"] > 0:
        return "🟡 Materials Posted"
    return "🔵 Scheduled"


def _meeting_name(row: dict) -> str:
    return row.get("title") or row.get("meeting_number") or "—"


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

meetings = db.list_meetings_overview(past_days=60, future_days=90)

today = date.today()
upcoming = list(reversed([m for m in meetings if m["meeting_date"] >= today]))
past     = list(reversed([m for m in meetings if m["meeting_date"] <  today]))

# ---------------------------------------------------------------------------
# Render a selectable table; returns the meeting ID of the selected row or None
# ---------------------------------------------------------------------------

def _render_table(rows: list[dict], table_key: str) -> int | None:
    if not rows:
        st.write("_(none)_")
        return None

    table_rows = [
        {
            "Date":    _fmt_date(r),
            "Venue":   r["venue_short"],
            "Meeting": _meeting_name(r),
            "Status":  _status_pill(r),
        }
        for r in rows
    ]

    event = st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=table_key,
    )

    selected_indices = event.selection.rows
    if selected_indices:
        return rows[selected_indices[0]]["id"]
    return None


# ---------------------------------------------------------------------------
# Display tables and handle navigation
# ---------------------------------------------------------------------------

st.caption("Click a row to open that meeting in the Meetings page.")

st.subheader("Upcoming")
selected_id = _render_table(upcoming, "tbl_upcoming")

if selected_id is None:
    st.subheader("Recent Past")
    selected_id = _render_table(past, "tbl_past")

if selected_id is not None:
    st.session_state["_jump_to_meeting_id"] = selected_id
    st.switch_page("v2_pages/meetings.py")

# ---------------------------------------------------------------------------
# Refresh upcoming meetings
# ---------------------------------------------------------------------------

st.divider()
with st.expander("🔄 Refresh Upcoming Meetings"):
    st.write(
        "Scrapes ISO-NE and NYISO committee calendars and runs full ingest "
        "(document list + agenda parsing) for any new meetings found. "
        "Existing meetings are not overwritten."
    )
    if st.button("Run Refresh"):
        import yaml
        from datetime import datetime
        from pipeline.scraper import scrape_calendar, fetch_event_docs
        from pipeline.ingest import ingest_meeting
        from pipeline.nyiso_scraper import fetch_meetings as nyiso_fetch_meetings
        from pipeline.nyiso_ingest import ingest_nyiso_meeting

        try:
            with open("config.yaml") as fh:
                config = yaml.safe_load(fh)
        except FileNotFoundError:
            st.error("config.yaml not found — cannot scrape.")
            st.stop()

        status_area = st.empty()
        total_new = 0
        errors = []

        # --- ISO-NE -----------------------------------------------------------
        lookahead = config.get("lookahead_days", 60)
        for committee in config.get("committees", []):
            if not committee.get("active", True):
                continue
            status_area.info(f"Scraping ISO-NE {committee['name']}…")
            try:
                found = scrape_calendar(committee, lookahead)
            except Exception as exc:
                errors.append(f"ISO-NE {committee['name']}: calendar scrape failed — {exc}")
                continue

            for mtg in found:
                try:
                    docs = fetch_event_docs(mtg["primary_event_id"])
                    result = ingest_meeting(
                        mtg, docs, config,
                        venue_short="ISO-NE",
                        overwrite=False,
                    )
                    if result:
                        total_new += 1
                except Exception as exc:
                    errors.append(
                        f"ISO-NE {committee['name']} / event {mtg.get('primary_event_id')}: {exc}"
                    )

        # --- NYISO -------------------------------------------------------------
        nyiso_lookahead = config.get("nyiso_lookahead_days", 90)
        current_year = datetime.now().year
        for committee in config.get("nyiso_committees", []):
            if not committee.get("active", True):
                continue
            status_area.info(f"Scraping NYISO {committee['name']}…")
            try:
                found = nyiso_fetch_meetings(committee, current_year, nyiso_lookahead)
            except Exception as exc:
                errors.append(f"NYISO {committee['name']}: scrape failed — {exc}")
                continue

            for mtg in found:
                try:
                    result = ingest_nyiso_meeting(
                        committee,
                        meeting_id=mtg["meeting_id"],
                        meeting_date=mtg["date"],
                        venue_short="NYISO",
                        overwrite=False,
                    )
                    if result:
                        total_new += 1
                except Exception as exc:
                    errors.append(
                        f"NYISO {committee['name']} / {mtg['date']}: {exc}"
                    )

        if errors:
            for msg in errors:
                st.warning(msg)

        status_area.success(f"Done. {total_new} meeting(s) ingested.")
        st.rerun()
