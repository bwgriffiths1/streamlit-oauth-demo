"""
v2_pages/bulk_summarize.py — Bulk-summarize multiple meetings in one run.
"""
import os
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import pipeline.db_new as db
from pipeline.summarizer import make_client, run_meeting_summarization

st.set_page_config(page_title="Bulk Summarize", layout="wide")
st.title("Bulk Summarize")
st.caption(
    "Select meetings to summarize in batch. "
    "Each meeting runs the full 3-level pipeline (doc summaries → rollups → briefing)."
)

# ---------------------------------------------------------------------------
# Check API key early
# ---------------------------------------------------------------------------
api_key_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
if not api_key_ok:
    st.error("ANTHROPIC_API_KEY not set — cannot summarize.", icon="⚠️")
    st.stop()

# ---------------------------------------------------------------------------
# Cascading filters: Venue → Committee → Date range
# ---------------------------------------------------------------------------
venues = db.get_venues()
venue_map = {v["short_name"]: v for v in venues}
venue_shorts = list(venue_map.keys())

ALL = "(All)"

col_v, col_t, col_range = st.columns(3)

with col_v:
    sel_venue = st.selectbox("Venue", options=venue_shorts, key="_bs_venue")

with col_t:
    types = db.get_meeting_types(venue_short_name=sel_venue)
    type_map = {t["short_name"]: t["name"] for t in types}
    type_options = [ALL] + list(type_map.keys())
    sel_type = st.selectbox(
        "Committee",
        options=type_options,
        format_func=lambda k: type_map[k] if k in type_map else ALL,
        key="_bs_type",
    )

with col_range:
    past_days = st.number_input(
        "Show meetings from last N days",
        min_value=7, max_value=730, value=90, step=30,
        key="_bs_days",
    )

st.divider()

# ---------------------------------------------------------------------------
# Load meetings with status info
# ---------------------------------------------------------------------------
all_meetings = db.list_meetings_overview(
    venue_short=sel_venue, past_days=past_days, future_days=90,
)

# Filter by committee if not "(All)"
if sel_type != ALL:
    all_meetings = [m for m in all_meetings if m["type_short"] == sel_type]

if not all_meetings:
    st.info("No meetings found for the selected filters.")
    st.stop()

# Enrich with unassigned doc counts
for m in all_meetings:
    unassigned = db.get_unassigned_documents(m["id"])
    m["unassigned_docs"] = len(unassigned)


# ---------------------------------------------------------------------------
# Build the display table
# ---------------------------------------------------------------------------
def _status_label(m: dict) -> str:
    if m.get("has_manual"):
        return "🟣 Edited"
    if m.get("has_summary"):
        return "🟢 Summarized"
    if m.get("doc_count", 0) > 0:
        return "🟡 Materials"
    return "🔵 Scheduled"


rows = []
for m in all_meetings:
    rows.append({
        "meeting_id": m["id"],
        "Committee": m["type_short"],
        "Date": m["meeting_date"],
        "Status": _status_label(m),
        "Docs": m.get("doc_count", 0),
        "Unassigned": m["unassigned_docs"],
        "Summarized": bool(m.get("has_summary")),
    })

df = pd.DataFrame(rows)

# Add a Select column for the user to check/uncheck
df.insert(0, "Select", False)

# ---------------------------------------------------------------------------
# Editable table
# ---------------------------------------------------------------------------
st.markdown("### Meetings")

edited_df = st.data_editor(
    df,
    column_config={
        "Select": st.column_config.CheckboxColumn("Select", default=False, width="small"),
        "meeting_id": st.column_config.NumberColumn("ID", width="small"),
        "Committee": st.column_config.TextColumn("Committee", width="small"),
        "Date": st.column_config.DateColumn("Date", width="small"),
        "Status": st.column_config.TextColumn("Status", width="medium"),
        "Docs": st.column_config.NumberColumn("Docs", width="small"),
        "Unassigned": st.column_config.NumberColumn("Unassigned", width="small",
                                                     help="Documents not yet assigned to an agenda item"),
        "Summarized": st.column_config.CheckboxColumn("Has Summary", disabled=True, width="small"),
    },
    hide_index=True,
    use_container_width=True,
    key="_bs_table",
)

selected_rows = edited_df[edited_df["Select"] == True]
n_selected = len(selected_rows)

# ---------------------------------------------------------------------------
# Options + Run button
# ---------------------------------------------------------------------------
st.divider()

col_btn, col_force, col_img, col_info = st.columns([2, 2, 2, 3])

with col_btn:
    run_btn = st.button(
        f"🤖 Summarize {n_selected} meeting{'s' if n_selected != 1 else ''}",
        type="primary",
        disabled=n_selected == 0,
        use_container_width=True,
        key="_bs_run",
    )

with col_force:
    force_rerun = st.checkbox(
        "Force re-run",
        value=False,
        help="Re-summarize even if summaries already exist (creates new versions)",
        key="_bs_force",
    )

with col_img:
    do_images = st.checkbox(
        "Extract images",
        value=False,
        help="Extract charts/diagrams from PDFs and slides (slower, higher cost)",
        key="_bs_images",
    )

with col_info:
    if n_selected > 0:
        has_unassigned = selected_rows["Unassigned"].sum()
        already_done = selected_rows["Summarized"].sum()
        parts = []
        if already_done:
            parts.append(f"**{int(already_done)}** already summarized")
        if has_unassigned:
            parts.append(f"**{int(has_unassigned)}** unassigned doc(s)")
        if parts:
            st.caption(" · ".join(parts))
    else:
        st.caption("Select meetings above to summarize.")

# ---------------------------------------------------------------------------
# Run the pipeline
# ---------------------------------------------------------------------------
if run_btn and n_selected > 0:
    client = make_client()

    meeting_ids = selected_rows["meeting_id"].tolist()

    # Build a lookup for display labels
    id_to_label = {
        r["meeting_id"]: f"{r['Committee']} {r['Date']}"
        for _, r in selected_rows.iterrows()
    }

    results = []  # (label, status_str, detail)

    progress = st.progress(0)
    status_area = st.status(
        f"Summarizing {n_selected} meeting{'s' if n_selected != 1 else ''}…",
        expanded=True,
    )

    for i, mid in enumerate(meeting_ids):
        label = id_to_label.get(mid, str(mid))
        progress.progress(i / n_selected)
        status_area.write(f"**{label}** — starting…")

        # Look up meeting metadata
        meeting = db.get_meeting(mid)
        if not meeting:
            results.append((label, "❌ Error", "Meeting not found in DB"))
            continue

        committee_short = meeting.get("type_short", "MC")
        venue_short = meeting.get("venue_short", sel_venue)

        try:
            res = run_meeting_summarization(
                meeting_id=mid,
                client=client,
                committee_short=committee_short,
                venue_short=venue_short,
                progress_fn=lambda msg, _l=label: status_area.write(f"  {_l}: {msg}"),
                force_rerun=force_rerun,
                extract_images=do_images if do_images else None,
            )
            n1, n2, n3 = res["level1"], res["level2"], res["level3"]
            errs = res.get("errors", [])
            detail = f"L1={n1}, L2={n2}, briefing={'✓' if n3 else '—'}"
            if errs:
                results.append((label, f"⚠️ {len(errs)} error(s)", detail + f" | {errs[0]}"))
            else:
                results.append((label, "✅ Done", detail))
        except Exception as exc:
            results.append((label, "❌ Error", str(exc)[:120]))

    progress.progress(1.0)
    status_area.update(label="Batch complete!", state="complete", expanded=False)

    # Results table
    st.markdown("### Results")
    result_df = pd.DataFrame(results, columns=["Meeting", "Status", "Detail"])
    st.dataframe(result_df, use_container_width=True, hide_index=True)
