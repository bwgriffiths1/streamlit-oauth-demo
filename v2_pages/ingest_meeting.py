"""
v2_pages/ingest_meeting.py — Add a meeting by URL (new schema).
"""
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pandas as pd
import streamlit as st
import yaml
from dotenv import load_dotenv

load_dotenv()

import pipeline.db_new as db
from pipeline.scraper import fetch_event_docs, fetch_event_metadata
from pipeline.ingest import ingest_meeting

st.set_page_config(page_title="Add Meeting", layout="wide")
st.title("Add Meeting")

# ---------------------------------------------------------------------------
# Helpers (shared by both tabs)
# ---------------------------------------------------------------------------

def _parse_event_id(raw: str) -> str | None:
    raw = raw.strip()
    if re.fullmatch(r"\d+", raw):
        return raw
    try:
        qs = parse_qs(urlparse(raw).query)
        for key in ("eventId", "eventid", "EventId"):
            if qs.get(key):
                return qs[key][0]
        m = re.search(r"\beventId[=:](\d+)", raw, re.IGNORECASE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _match_committee(raw_name: str, meeting_types: list[dict]) -> str | None:
    """Match a free-text committee name to a known meeting_type short_name."""
    if not raw_name:
        return None
    raw_lower = raw_name.lower()
    # Exact name match
    for t in meeting_types:
        if t["name"].lower() == raw_lower:
            return t["short_name"]
    # Exact short_name match
    for t in meeting_types:
        if t["short_name"].lower() == raw_lower:
            return t["short_name"]
    # DB name is a substring of the raw name (e.g. "Markets Committee" in "Markets Committee Meeting")
    for t in meeting_types:
        if t["name"].lower() in raw_lower:
            return t["short_name"]
    # Short name appears in raw name
    for t in meeting_types:
        if t["short_name"].lower() in raw_lower.split():
            return t["short_name"]
    return None


def _apply_prefill_to_widgets(metadata: dict) -> None:
    """Write prefill values directly to Streamlit widget session_state keys.

    This ensures the dropdowns, date pickers, and text inputs actually show
    the looked-up values on the next rerun (Streamlit ignores the `value`/
    `index` param once a key already exists in session_state).
    """
    # Venue — ISO-NE meetings always come from ISO-NE
    if "ISO-NE" in venue_map:
        st.session_state["add_venue"] = "ISO-NE"

    # Committee — match the raw title to a known short_name
    if metadata.get("committee"):
        # Need to resolve types for the venue that will be selected
        venue_short = st.session_state.get("add_venue", venue_shorts[0] if venue_shorts else "")
        mtypes = db.get_meeting_types(venue_short_name=venue_short)
        matched = _match_committee(metadata["committee"], mtypes)
        if matched:
            st.session_state["add_type"] = matched

    # Dates
    if metadata.get("start_date"):
        st.session_state["add_date"] = metadata["start_date"]
    st.session_state["add_multiday"] = metadata.get("end_date") is not None
    if metadata.get("end_date"):
        st.session_state["add_end_date"] = metadata["end_date"]

    # Location
    st.session_state["add_location"] = metadata.get("location") or ""


def _already_in_db(event_id: str, meeting_type_id: int) -> dict | None:
    for m in db.list_meetings(limit=500):
        if str(m.get("external_id")) == str(event_id) and m["meeting_type_id"] == meeting_type_id:
            return m
    return None


# Load venues once — used in both tabs
venues = db.get_venues()
venue_map = {v["short_name"]: v for v in venues}
venue_shorts = list(venue_map.keys())

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["ISO-NE Meeting", "Bulk Upload", "NYISO Meeting"])

# ===========================================================================
# TAB 1 — Single meeting (original behaviour)
# ===========================================================================
with tab1:
    st.caption(
        "Register a meeting from an ISO-NE event page URL. "
        "The agenda will be parsed and all documents catalogued."
    )

    # URL input
    url_input = st.text_input(
        "Event page URL or event ID",
        placeholder="https://www.iso-ne.com/event-details?eventId=160091  or  160091",
        key="add_url",
    )

    event_id = _parse_event_id(url_input) if url_input.strip() else None

    if url_input.strip() and not event_id:
        st.error("Could not find an eventId in that input.")
    if event_id:
        col_id, col_lookup = st.columns([3, 1])
        with col_id:
            st.caption(f"Event ID: `{event_id}`")
        with col_lookup:
            if st.button("Lookup event details", key="add_lookup"):
                with st.spinner("Fetching event metadata from ISO-NE…"):
                    metadata = fetch_event_metadata(event_id)
                if metadata:
                    st.session_state["_prefill_metadata"] = metadata
                    st.session_state["_prefill_event_id"] = event_id
                    # Write directly to widget keys so they update on rerun
                    _apply_prefill_to_widgets(metadata)
                    st.rerun()
                else:
                    st.warning("Could not fetch metadata. Fill in fields manually.")

    # Clear prefill if event ID changed
    if event_id != st.session_state.get("_prefill_event_id"):
        st.session_state.pop("_prefill_metadata", None)
        st.session_state.pop("_prefill_event_id", None)

    prefill = st.session_state.get("_prefill_metadata", {})
    if prefill:
        st.success(
            f"Auto-filled from event: **{prefill.get('committee', '—')}** · "
            f"{prefill.get('start_date', '—')}"
            + (f" – {prefill['end_date']}" if prefill.get('end_date') else "")
            + (f" · {prefill['location']}" if prefill.get('location') else "")
        )

    st.divider()

    # Venue / Committee
    col_venue, col_type = st.columns([1, 2])

    with col_venue:
        selected_venue = st.selectbox("Venue", options=venue_shorts, key="add_venue")

    with col_type:
        types = db.get_meeting_types(venue_short_name=selected_venue)
        type_map = {t["short_name"]: t for t in types}

        NEW_KEY = "(+ New committee…)"
        type_display = {k: v["name"] for k, v in type_map.items()}
        type_display[NEW_KEY] = NEW_KEY

        type_options = list(type_display.keys())

        selected_type_short = st.selectbox(
            "Committee",
            options=type_options,
            format_func=lambda k: type_display[k],
            key="add_type",
        )

    # New committee form
    new_type_row = None
    if selected_type_short == NEW_KEY:
        st.markdown("**New committee**")
        nc1, nc2, nc3 = st.columns([2, 1, 2])
        new_type_name  = nc1.text_input("Full name",   placeholder="Power Supply Planning Committee", key="new_type_name")
        new_type_short = nc2.text_input("Short name",  placeholder="PSPC", key="new_type_short")
        new_type_desc  = nc3.text_input("Description (optional)", key="new_type_desc")
        if new_type_name and new_type_short:
            st.caption(f"Will create: **{new_type_name}** ({new_type_short.upper()}) under {selected_venue}")
        else:
            st.warning("Enter both a full name and short name to continue.")

    st.divider()

    # Dates — set defaults in session_state once; lookup overwrites them.
    # (Streamlit warns if you pass both `value=` and set session_state.)
    if "add_multiday" not in st.session_state:
        st.session_state["add_multiday"] = False
    if "add_date" not in st.session_state:
        st.session_state["add_date"] = date.today()
    if "add_end_date" not in st.session_state:
        st.session_state["add_end_date"] = date.today() + timedelta(days=1)

    col_multi, col_start, col_end = st.columns([1, 1, 1])

    with col_multi:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        multi_day = st.checkbox("Multi-day meeting", key="add_multiday")

    with col_start:
        meeting_date = st.date_input("Start date", key="add_date")

    with col_end:
        # Ensure end_date is never before start date (avoids Streamlit min_value error)
        if st.session_state.get("add_end_date") and meeting_date and st.session_state["add_end_date"] < meeting_date:
            st.session_state["add_end_date"] = meeting_date
        end_date = st.date_input(
            "End date",
            min_value=meeting_date,
            key="add_end_date",
            disabled=not multi_day,
        )
        if not multi_day:
            end_date = None
        elif end_date == meeting_date:
            end_date = None

    # Location — editable; lookup writes to session_state["add_location"]
    location_input = st.text_input(
        "Location",
        placeholder="e.g. DoubleTree Hotel, Westborough, MA",
        key="add_location",
    )

    meeting_number = None

    # Already-in-DB notice
    existing = None
    if event_id and selected_type_short != NEW_KEY:
        existing = _already_in_db(event_id, type_map[selected_type_short]["id"])
        if existing:
            st.info(
                f"Already in database (id={existing['id']}, status={existing['status']}). "
                "Running again will update documents and re-insert agenda items."
            )

    overwrite = st.checkbox(
        "Overwrite existing agenda if already ingested",
        value=True,
        help="Clears and re-inserts agenda items, assignments, and summary stubs.",
        key="add_overwrite",
    )

    st.divider()

    # Preview
    if st.button("Preview documents", disabled=not event_id, key="add_preview"):
        with st.spinner("Fetching document list from ISO-NE API…"):
            docs = fetch_event_docs(event_id)
        if docs:
            st.success(f"Found {len(docs)} document(s):")
            for d in docs:
                st.markdown(f"- `{d['filename']}`")
        else:
            st.warning("No documents returned. Materials may not be posted yet.")

    st.divider()

    # Ingest
    new_type_ready = (selected_type_short != NEW_KEY) or (
        selected_type_short == NEW_KEY
        and st.session_state.get("new_type_name", "").strip()
        and st.session_state.get("new_type_short", "").strip()
    )
    run_disabled = not event_id or not new_type_ready

    if st.button("Ingest meeting", type="primary", disabled=run_disabled, key="add_run"):
        import yaml, logging
        logging.basicConfig(level=logging.INFO)
        config = yaml.safe_load(open("config.yaml"))

        with st.status("Ingesting…", expanded=True) as status:

            if selected_type_short == NEW_KEY:
                venue_id = venue_map[selected_venue]["id"]
                new_name  = st.session_state["new_type_name"].strip()
                new_short = st.session_state["new_type_short"].strip().upper()
                new_desc  = st.session_state.get("new_type_desc", "").strip() or None
                st.write(f"Creating committee: {new_name} ({new_short})…")
                new_type_row = db.create_meeting_type(venue_id, new_name, new_short, new_desc)
                effective_short = new_short
                effective_name  = new_name
            else:
                effective_short = selected_type_short
                effective_name  = type_map[selected_type_short]["name"]

            if end_date and end_date > meeting_date:
                dates = []
                cur = meeting_date
                while cur <= end_date:
                    dates.append(cur)
                    cur += timedelta(days=1)
            else:
                dates = [meeting_date]

            st.write("Fetching document list from ISO-NE API…")
            doc_list = fetch_event_docs(event_id)
            if not doc_list:
                st.warning("No documents returned. Continuing with empty doc list.")
            else:
                st.write(f"Found {len(doc_list)} document(s).")

            meeting_dict = {
                "primary_event_id": event_id,
                "committee_short":  effective_short,
                "dates":            dates,
                "location":         location_input.strip() or None,
                "title":            effective_name,
                "meeting_number":   None,
            }

            st.write("Parsing agenda and writing to database…")
            try:
                meeting_id = ingest_meeting(
                    meeting_dict=meeting_dict,
                    doc_list=doc_list,
                    config=config,
                    venue_short=selected_venue,
                    overwrite=overwrite,
                )
            except Exception as exc:
                status.update(label="Failed.", state="error")
                st.error(f"Ingest error: {exc}")
                st.stop()

            if meeting_id is None:
                status.update(label="Failed.", state="error")
                st.error("Ingest returned no meeting_id — check logs for details.")
                st.stop()

            status.update(label="Done!", state="complete", expanded=False)

        st.success(f"Meeting ingested (id={meeting_id}).")
        st.markdown("Go to **Meetings** to browse the agenda and documents.")
        col_a, col_b = st.columns(2)
        col_a.metric("Agenda items", len(db.get_agenda_items(meeting_id)))
        col_b.metric("Documents",    len(db.get_documents_for_meeting(meeting_id)))


# ===========================================================================
# TAB 2 — Bulk Upload
# ===========================================================================
with tab2:
    st.caption(
        "Add multiple meetings at once. Each row needs a Venue, Committee (short name), "
        "Start Date, and Event URL or ID. End Date defaults to Start Date if left blank."
    )

    # Build committee options per venue for the help text
    all_types = db.get_meeting_types()
    committee_help = ", ".join(sorted({t["short_name"] for t in all_types}))
    st.caption(f"Known committee short names: {committee_help}")

    empty_df = pd.DataFrame({
        "Venue":           pd.Series(dtype=str),
        "Committee":       pd.Series(dtype=str),
        "Start Date":      pd.Series(dtype="datetime64[ns]"),
        "End Date":        pd.Series(dtype="datetime64[ns]"),
        "Event URL or ID": pd.Series(dtype=str),
    })

    bulk_df = st.data_editor(
        empty_df,
        num_rows="dynamic",
        column_config={
            "Venue": st.column_config.SelectboxColumn(
                "Venue",
                options=venue_shorts,
                required=True,
                default=venue_shorts[0] if venue_shorts else None,
                width="small",
            ),
            "Committee": st.column_config.TextColumn(
                "Committee",
                help="Short name, e.g. MC, NPC, RC",
                required=True,
                width="small",
            ),
            "Start Date": st.column_config.DateColumn(
                "Start Date",
                required=True,
                width="small",
            ),
            "End Date": st.column_config.DateColumn(
                "End Date",
                help="Leave blank for single-day meetings",
                required=False,
                width="small",
            ),
            "Event URL or ID": st.column_config.TextColumn(
                "Event URL or ID",
                help="Paste the full URL or just the numeric event ID",
                required=True,
                width="large",
            ),
        },
        use_container_width=True,
        key="bulk_table",
    )

    valid_rows = bulk_df.dropna(subset=["Venue", "Committee", "Start Date", "Event URL or ID"])

    col_run, col_info = st.columns([1, 4])
    with col_run:
        run_bulk = st.button(
            "Ingest All",
            type="primary",
            disabled=valid_rows.empty,
            use_container_width=True,
            key="bulk_run",
        )
    with col_info:
        if not valid_rows.empty:
            st.caption(f"{len(valid_rows)} row(s) ready to ingest.")

    if run_bulk:
        import yaml, logging
        logging.basicConfig(level=logging.INFO)
        config = yaml.safe_load(open("config.yaml"))

        results = []   # list of (row_label, status, detail)

        progress = st.progress(0)
        status_area = st.empty()

        for i, (_, row) in enumerate(valid_rows.iterrows()):
            venue_short  = str(row["Venue"]).strip()
            comm_short   = str(row["Committee"]).strip().upper()
            start        = row["Start Date"]
            end          = row["End Date"] if pd.notna(row.get("End Date")) else None
            raw_event    = str(row["Event URL or ID"]).strip()

            label = f"{venue_short} / {comm_short} / {start}"
            status_area.info(f"Processing {label}…")
            progress.progress((i) / len(valid_rows))

            # Parse event ID
            eid = _parse_event_id(raw_event)
            if not eid:
                results.append((label, "❌ Error", "Could not parse event ID"))
                continue

            # Resolve venue
            if venue_short not in venue_map:
                results.append((label, "❌ Error", f"Unknown venue '{venue_short}'"))
                continue

            # Resolve committee
            comm_types = db.get_meeting_types(venue_short_name=venue_short)
            comm_map   = {t["short_name"].upper(): t for t in comm_types}
            if comm_short not in comm_map:
                results.append((label, "❌ Error", f"Unknown committee '{comm_short}' for {venue_short}"))
                continue

            type_row = comm_map[comm_short]

            # Build date list
            if end and pd.notna(end) and end > start:
                dates = []
                cur = start.date() if hasattr(start, "date") else start
                end_d = end.date() if hasattr(end, "date") else end
                while cur <= end_d:
                    dates.append(cur)
                    cur += timedelta(days=1)
            else:
                d = start.date() if hasattr(start, "date") else start
                dates = [d]

            meeting_dict = {
                "primary_event_id": eid,
                "committee_short":  comm_short,
                "dates":            dates,
                "location":         None,
                "title":            type_row["name"],
                "meeting_number":   None,
            }

            try:
                doc_list = fetch_event_docs(eid)
                meeting_id = ingest_meeting(
                    meeting_dict=meeting_dict,
                    doc_list=doc_list,
                    config=config,
                    venue_short=venue_short,
                    overwrite=False,
                )
                if meeting_id:
                    n_docs = len(db.get_documents_for_meeting(meeting_id))
                    results.append((label, "✅ Done", f"id={meeting_id}, {n_docs} doc(s)"))
                else:
                    results.append((label, "⚠️ Skipped", "ingest returned no id"))
            except Exception as exc:
                results.append((label, "❌ Error", str(exc)))

        progress.progress(1.0)
        status_area.empty()

        st.markdown("### Results")
        result_df = pd.DataFrame(results, columns=["Meeting", "Status", "Detail"])
        st.dataframe(result_df, use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 3 — NYISO Meeting
# ===========================================================================
with tab3:
    st.caption(
        "Ingest NYISO committee meetings into the database. "
        "Fetches file lists from the NYISO API and parses PDF agendas."
    )

    from pipeline.nyiso_scraper import fetch_meetings as nyiso_fetch_meetings
    from pipeline.nyiso_ingest import ingest_nyiso_meeting

    # Load NYISO committees from config
    try:
        _cfg = yaml.safe_load(open("config.yaml"))
        _nyiso_committees = [
            c for c in _cfg.get("nyiso_committees", []) if c.get("active", True)
        ]
    except Exception:
        _nyiso_committees = []

    if not _nyiso_committees:
        st.warning("No NYISO committees found in config.yaml.")
        st.stop()

    # Committee selector
    _comm_names = [c["short"] for c in _nyiso_committees]
    _comm_map = {c["short"]: c for c in _nyiso_committees}

    col_comm, col_year = st.columns([1, 1])
    with col_comm:
        nyiso_committee = st.selectbox("Committee", _comm_names, key="nyiso_comm")
    with col_year:
        nyiso_year = st.number_input(
            "Year", value=date.today().year,
            min_value=2020, max_value=2030, key="nyiso_year",
        )

    # Session state for fetched meetings
    if "nyiso_meetings" not in st.session_state:
        st.session_state.nyiso_meetings = []

    if st.button("Fetch Meetings", key="nyiso_fetch"):
        committee_cfg = _comm_map[nyiso_committee]
        with st.spinner("Fetching meetings from NYISO API..."):
            meetings = nyiso_fetch_meetings(
                committee_cfg, nyiso_year, lookahead_days=365,
            )
        st.session_state.nyiso_meetings = meetings
        if meetings:
            st.success(f"Found {len(meetings)} meeting(s).")
        else:
            st.warning("No meetings found for that committee/year.")

    meetings_list = st.session_state.nyiso_meetings
    if meetings_list:
        st.divider()

        # Build display options
        meeting_options = {
            f"{m['committee_short']} — {m['date'].isoformat()} (ID: {m['meeting_id']})": i
            for i, m in enumerate(meetings_list)
        }

        selected_meetings = st.multiselect(
            "Select meeting(s) to ingest",
            options=list(meeting_options.keys()),
            key="nyiso_select",
        )

        nyiso_overwrite = st.checkbox(
            "Overwrite existing agenda if already ingested",
            value=True, key="nyiso_overwrite",
        )

        st.divider()

        if st.button(
            "Ingest Selected",
            type="primary",
            disabled=not selected_meetings,
            key="nyiso_ingest",
        ):
            import logging
            logging.basicConfig(level=logging.INFO)

            committee_cfg = _comm_map[nyiso_committee]
            results = []

            with st.status("Ingesting NYISO meetings...", expanded=True) as status:
                for label in selected_meetings:
                    idx = meeting_options[label]
                    m = meetings_list[idx]
                    st.write(f"Ingesting {m['committee_short']} {m['date'].isoformat()}...")

                    try:
                        mid = ingest_nyiso_meeting(
                            committee=committee_cfg,
                            meeting_id=m["meeting_id"],
                            meeting_date=m["date"],
                            overwrite=nyiso_overwrite,
                        )
                        if mid:
                            n_items = len(db.get_agenda_items(mid))
                            n_docs = len(db.get_documents_for_meeting(mid))
                            results.append((label, "Done", f"id={mid}, {n_items} items, {n_docs} docs"))
                            st.write(f"  Done: {n_items} agenda items, {n_docs} documents")
                        else:
                            results.append((label, "Failed", "ingest returned no id"))
                    except Exception as exc:
                        results.append((label, "Error", str(exc)))
                        st.write(f"  Error: {exc}")

                status.update(label="Done!", state="complete", expanded=False)

            st.markdown("### Results")
            result_df = pd.DataFrame(results, columns=["Meeting", "Status", "Detail"])
            st.dataframe(result_df, use_container_width=True, hide_index=True)
