"""
v2_pages/nyiso_viewer.py — NYISO meeting browser (filesystem-based, no DB).

Browse meetings, view agendas, inspect file-to-item mappings, and trigger scrapes.
"""
import json
import time
from datetime import date
from pathlib import Path

import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _load_manifests(storage_root: Path) -> list[dict]:
    """Walk the storage root and load all manifest.json files."""
    manifests = []
    if not storage_root.exists():
        return manifests
    for mf in sorted(storage_root.rglob("manifest.json"), reverse=True):
        try:
            with open(mf) as f:
                data = json.load(f)
            data["_manifest_path"] = str(mf)
            data["_folder"] = str(mf.parent)
            manifests.append(data)
        except Exception:
            pass
    manifests.sort(key=lambda m: m.get("meeting_date", ""), reverse=True)
    return manifests


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("NYISO Meetings")

cfg = _load_config()
storage_root = ROOT / cfg.get("nyiso_storage_root", "./nyiso-materials")
committees = cfg.get("nyiso_committees", [])

# ── Sidebar: Committee filter + scrape controls ──────────────────────────

st.sidebar.header("NYISO")

committee_names = ["All"] + [c["short"] for c in committees if c.get("active", True)]
selected_committee = st.sidebar.selectbox("Committee", committee_names)

st.sidebar.divider()

# Calendar preview
with st.sidebar.expander("Fetch Calendar"):
    cal_year = st.number_input("Year", value=date.today().year, min_value=2020, max_value=2030)
    cal_committee = st.selectbox(
        "Committee to check",
        [c["short"] for c in committees if c.get("active", True)],
        key="cal_committee",
    )
    if st.button("List Meetings"):
        from pipeline.nyiso_scraper import fetch_meetings
        target = next((c for c in committees if c["short"] == cal_committee), None)
        if target:
            with st.spinner("Fetching..."):
                meetings = fetch_meetings(target, cal_year, lookahead_days=365)
            if meetings:
                for m in meetings:
                    st.write(f"**{m['date'].isoformat()}** — ID: `{m['meeting_id']}`")
            else:
                st.info("No meetings found.")

# Scrape trigger
with st.sidebar.expander("Scrape Meeting"):
    scrape_committee = st.selectbox(
        "Committee",
        [c["short"] for c in committees if c.get("active", True)],
        key="scrape_committee",
    )
    scrape_id = st.text_input("Meeting ID (folder ID)", placeholder="e.g. 57399123")
    if st.button("Scrape & Download"):
        if scrape_id:
            from pipeline.nyiso_scraper import fetch_meetings, fetch_meeting_files
            from nyiso_main import scrape_meeting
            import requests

            target = next((c for c in committees if c["short"] == scrape_committee), None)
            if target:
                with st.spinner(f"Scraping {scrape_committee} meeting {scrape_id}..."):
                    session = requests.Session()
                    # Find meeting date from API
                    all_mtgs = fetch_meetings(target, cal_year, lookahead_days=365, session=session)
                    meeting_date = date.today()
                    for m in all_mtgs:
                        if m["meeting_id"] == scrape_id:
                            meeting_date = m["date"]
                            break

                    meeting = {
                        "meeting_id": scrape_id,
                        "date": meeting_date,
                        "committee_name": target["name"],
                        "committee_short": target["short"],
                    }
                    result = scrape_meeting(target, meeting, storage_root, session)

                if result:
                    st.success(
                        f"Done! {len(result['documents'])} files, "
                        f"{len(result['agenda_items'])} agenda items"
                    )
                    st.rerun()
                else:
                    st.error("Scrape failed — check logs.")
        else:
            st.warning("Enter a meeting ID.")


# ── Main: Meeting list ───────────────────────────────────────────────────

manifests = _load_manifests(storage_root)

if selected_committee != "All":
    manifests = [m for m in manifests if m.get("committee_short") == selected_committee]

if not manifests:
    st.info(
        "No NYISO meetings scraped yet. Use the sidebar to scrape a meeting, "
        "or run `python nyiso_main.py` from the command line."
    )
    st.stop()

# Meeting selector
meeting_options = {
    f"{m['committee_short']} — {m['meeting_date']} ({len(m.get('documents', []))} files)": i
    for i, m in enumerate(manifests)
}

selected_label = st.selectbox("Select meeting", list(meeting_options.keys()))
meeting = manifests[meeting_options[selected_label]]

# ── Meeting detail ───────────────────────────────────────────────────────

st.divider()

col1, col2, col3 = st.columns(3)
col1.metric("Committee", meeting["committee_short"])
col2.metric("Date", meeting["meeting_date"])
col3.metric("Documents", len(meeting.get("documents", [])))

# Tabs: Agenda | Documents | File Mapping | Raw Manifest
tab_agenda, tab_docs, tab_mapping, tab_raw = st.tabs(
    ["Agenda", "Documents", "File Mapping", "Manifest"]
)

# ── Agenda tab ───────────────────────────────────────────────────────────

with tab_agenda:
    items = meeting.get("agenda_items", [])
    if not items:
        st.info("No agenda items parsed for this meeting.")
    else:
        for item in items:
            presenter = item.get("presenter") or ""
            time_slot = item.get("time_slot") or ""
            badge = f"  `{time_slot}`" if time_slot else ""
            presenter_text = f"  — _{presenter}_" if presenter else ""
            st.markdown(
                f"**{item['item_id']}.** {item['title']}{presenter_text}{badge}"
            )

# ── Documents tab ────────────────────────────────────────────────────────

with tab_docs:
    docs = meeting.get("documents", [])
    if not docs:
        st.info("No documents.")
    else:
        # Sort by agenda prefix (numeric) then display name
        def _sort_key(d):
            prefix = d.get("agenda_prefix") or "zzz"
            try:
                num = int("".join(c for c in prefix if c.isdigit()))
                letter = "".join(c for c in prefix if c.isalpha())
            except ValueError:
                num, letter = 999, prefix
            return (num, letter)

        sorted_docs = sorted(docs, key=_sort_key)

        for d in sorted_docs:
            prefix_badge = f"`{d['agenda_prefix']}`" if d.get("agenda_prefix") else "`—`"
            dl_icon = "✅" if d.get("downloaded") else "⬜"
            ftype = d.get("file_type", "?").upper()

            with st.container():
                c1, c2 = st.columns([0.07, 0.93])
                c1.markdown(prefix_badge)
                c2.markdown(
                    f"{dl_icon} **{d.get('display_name', d['filename'])}** "
                    f"<small style='color:gray'>({ftype} · {d.get('date_posted', '?')})</small>",
                    unsafe_allow_html=True,
                )

                # Show download link to local file if it exists
                local_path = Path(meeting["_folder"]) / "_files" / d["filename"]
                if local_path.exists():
                    with open(local_path, "rb") as fh:
                        c2.download_button(
                            f"Download {d['filename']}",
                            data=fh.read(),
                            file_name=d["filename"],
                            mime="application/octet-stream",
                            key=f"dl_{d.get('file_id', d['filename'])}",
                        )

# ── File Mapping tab ─────────────────────────────────────────────────────

with tab_mapping:
    file_mapping = meeting.get("file_mapping", {})
    if not file_mapping:
        st.info("No file-to-agenda mapping available.")
    else:
        agenda_lookup = {
            item["item_id"]: item for item in meeting.get("agenda_items", [])
        }
        for item_id, filenames in file_mapping.items():
            if item_id == "unmatched":
                continue
            item = agenda_lookup.get(item_id, {})
            title = item.get("title", f"Item {item_id}")
            st.markdown(f"**{item_id}. {title}**")
            if filenames:
                for fn in filenames:
                    st.markdown(f"  - `{fn}`")
            else:
                st.caption("  _(no files)_")

        unmatched = file_mapping.get("unmatched", [])
        if unmatched:
            st.divider()
            st.markdown("**Unmatched files**")
            for fn in unmatched:
                st.markdown(f"  - `{fn}`")

# ── Raw manifest tab ─────────────────────────────────────────────────────

with tab_raw:
    st.json(meeting)
