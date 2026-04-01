"""
v2_pages/parse_compare.py — Regex vs LLM Agenda Parse Comparison

Side-by-side diagnostic page: pick a meeting (by event ID or from DB),
run both regex and LLM parsers, and display a colour-coded diff of the
results including agenda items and document assignments.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import pipeline.db_new as db
from pipeline.scraper import fetch_event_docs
from pipeline.downloader import check_url, download_file_temp
from pipeline.agenda_parser import (
    parse_agenda_from_docx,
    map_docs_to_agenda_items,
)
from pipeline.llm_agenda_parser import (
    extract_agenda_text_docx,
    llm_parse_agenda,
    llm_match_docs,
    reconcile_results,
)

st.set_page_config(page_title="Parse Compare", layout="wide")
st.title("Regex vs LLM Parse Comparison")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

import yaml as _yaml

_CFG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

@st.cache_data(ttl=300)
def _load_config() -> dict:
    return _yaml.safe_load(_CFG_PATH.read_text()) if _CFG_PATH.exists() else {}

config = _load_config()
ap_cfg = config.get("agenda_parsing", {})
default_model = ap_cfg.get("parse_model", "claude-haiku-4-5-20251001")

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

col_input, col_model = st.columns([3, 1])
with col_input:
    raw_input = st.text_input(
        "Event ID or URL",
        value="160091",
        help="Paste a bare ISO-NE event ID or a full event URL",
    )
with col_model:
    model = st.selectbox(
        "LLM Model",
        ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
        index=0,
    )

go = st.button("Compare", type="primary")

_m = re.search(r"eventId=(\d+)", raw_input)
event_id = _m.group(1) if _m else re.sub(r"\D", "", raw_input)

if not go:
    st.info("Enter an event ID and click **Compare** to run both parsers side-by-side.")
    st.stop()

if not event_id:
    st.error("Could not extract a numeric event ID.")
    st.stop()

event_url = f"https://www.iso-ne.com/event-details?eventId={event_id}"
st.caption(f"Event ID: **{event_id}** — {event_url}")

# ---------------------------------------------------------------------------
# Step 1: Fetch docs and download agenda
# ---------------------------------------------------------------------------

session = requests.Session()

with st.spinner("Fetching document list..."):
    doc_links = fetch_event_docs(event_id, session=session)

if not doc_links:
    st.warning("No documents found for this event.")
    st.stop()

# Find agenda docx
agenda_link = None
docs_meta: list[dict] = []
with st.spinner("Probing document URLs..."):
    for link in doc_links:
        meta = check_url(url=link["url"], referer_url=event_url, session=session)
        docs_meta.append(meta)
        if (
            "agenda" in meta["filename"].lower()
            and meta["file_type"] in ("docx", "pdf")
            and not meta["ceii_skipped"]
        ):
            # Prefer docx over pdf
            if agenda_link is None or (meta["file_type"] == "docx" and agenda_link["file_type"] == "pdf"):
                agenda_link = meta

if agenda_link is None:
    st.error("No agenda .docx found among the documents.")
    st.stop()

st.success(f"Found {len(docs_meta)} documents. Agenda: `{agenda_link['filename']}`")

# Download agenda bytes
with st.spinner(f"Downloading {agenda_link['filename']}..."):
    with download_file_temp(
        url=agenda_link["source_url"],
        filename=agenda_link["filename"],
        referer_url=event_url,
        session=session,
    ) as tmp_path:
        if tmp_path is None:
            st.error("Could not download agenda (CEII/403).")
            st.stop()
        agenda_bytes = Path(tmp_path).read_bytes()

# ---------------------------------------------------------------------------
# Step 2: Run both parsers
# ---------------------------------------------------------------------------

is_pdf = agenda_link["file_type"] == "pdf"

col_regex, col_llm = st.columns(2)

# Regex parse
with col_regex:
    st.subheader("Regex Parser")
    if is_pdf:
        st.info("Regex parser does not support PDF agendas.")
        regex_items = []
    else:
        with st.spinner("Running regex parser..."):
            try:
                regex_items = parse_agenda_from_docx(agenda_bytes)
                st.metric("Items parsed", len(regex_items))
            except Exception as exc:
                st.error(f"Regex parse failed: {exc}")
                regex_items = []

# LLM parse
with col_llm:
    st.subheader("LLM Parser")
    with st.spinner(f"Running LLM parser ({model})..."):
        try:
            if is_pdf:
                from pipeline.llm_agenda_parser import extract_agenda_text_pdf
                agenda_text = extract_agenda_text_pdf(agenda_bytes)
            else:
                agenda_text = extract_agenda_text_docx(agenda_bytes)
            llm_items = llm_parse_agenda(agenda_text, "ISO-NE", "MC", model=model)
            st.metric("Items parsed", len(llm_items))
        except Exception as exc:
            st.error(f"LLM parse failed: {exc}")
            llm_items = []

if not regex_items and not llm_items:
    st.error("Both parsers failed.")
    st.stop()

# ---------------------------------------------------------------------------
# Step 3: Reconciliation
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Reconciliation")

audit = reconcile_results(regex_items, llm_items)

# Summary metrics
m1, m2, m3, m4 = st.columns(4)
m1.metric("Regex items", audit["regex_count"])
m2.metric("LLM items", audit["llm_count"])
m3.metric("Agreement", f"{audit['agreement_pct']}%")
m4.metric("Only in regex", len(audit["regex_only"]))

# ---------------------------------------------------------------------------
# Step 4: Side-by-side item comparison
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Item-by-Item Comparison")

def _norm_id(iid: str) -> str:
    """Normalise item IDs for comparison: lowercase, strip trailing .0."""
    n = iid.lower().rstrip("*").strip()
    parts = n.split(".")
    if len(parts) == 2 and parts[1] == "0":
        n = parts[0]
    return n

regex_by_id = {_norm_id(it["item_id"]): it for it in regex_items}
llm_by_id = {_norm_id(it["item_id"]): it for it in llm_items}
all_ids = sorted(set(regex_by_id) | set(llm_by_id), key=lambda x: [
    (0, int(p)) if p.isdigit() else (1, p) for p in x.replace(".", " ").split()
])

COMPARE_FIELDS = ["title", "presenter", "org", "vote_status", "wmpp_id", "time_slot", "notes"]
# Title and notes compared case-insensitively (regex preserves source ALL CAPS, LLM title-cases)
CASE_INSENSITIVE = {"title", "notes"}

for item_id in all_ids:
    r = regex_by_id.get(item_id)
    l = llm_by_id.get(item_id)

    # Determine status colour
    if r and l:
        # Check for field differences
        has_diff = False
        for f in COMPARE_FIELDS:
            rv = str(r.get(f) or "").strip()
            lv = str(l.get(f) or "").strip()
            if f in CASE_INSENSITIVE:
                differs = rv.lower() != lv.lower()
            else:
                differs = rv != lv
            if differs:
                has_diff = True
                break
        if has_diff:
            indicator = ":orange_circle:"
            status = "Fields differ"
        else:
            indicator = ":green_circle:"
            status = "Agree"
    elif r and not l:
        indicator = ":red_circle:"
        status = "Regex only"
    else:
        indicator = ":blue_circle:"
        status = "LLM only"

    title = (r or l or {}).get("title", "")
    with st.expander(f"{indicator} **{item_id}** — {title}  _({status})_", expanded=(status != "Agree")):
        if r and l:
            c1, c2 = st.columns(2)
            for field in COMPARE_FIELDS:
                rv = str(r.get(field) or "—")
                lv = str(l.get(field) or "—")
                if field in CASE_INSENSITIVE:
                    match = rv.strip().lower() == lv.strip().lower()
                else:
                    match = rv.strip() == lv.strip()
                colour = "" if match else "background-color: #fff3cd;"
                with c1:
                    st.markdown(
                        f"<div style='font-size:0.85em;{colour}padding:2px 4px'>"
                        f"<strong>{field}</strong>: {rv}</div>",
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.markdown(
                        f"<div style='font-size:0.85em;{colour}padding:2px 4px'>"
                        f"<strong>{field}</strong>: {lv}</div>",
                        unsafe_allow_html=True,
                    )
        elif r:
            for field in COMPARE_FIELDS:
                val = str(r.get(field) or "—")
                st.markdown(f"**{field}**: {val}")
            st.caption("Not found by LLM parser")
        else:
            for field in COMPARE_FIELDS:
                val = str(l.get(field) or "—")
                st.markdown(f"**{field}**: {val}")
            st.caption("Not found by regex parser")

# ---------------------------------------------------------------------------
# Step 5: Document assignment comparison
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Document Assignment Comparison")

filenames = [m["filename"] for m in docs_meta]
simple_rows = [{"filename": f} for f in filenames]

# Regex matching
regex_buckets = map_docs_to_agenda_items(simple_rows, regex_items)

# LLM matching
with st.spinner("Running LLM document matching..."):
    try:
        match_model = ap_cfg.get("match_model", model)
        llm_buckets = llm_match_docs(llm_items or regex_items, filenames, "ISO-NE", model=match_model)
    except Exception as exc:
        st.error(f"LLM matching failed: {exc}")
        llm_buckets = {"other": simple_rows}

# Build reverse lookups: filename → item_id
def _buckets_to_map(buckets: dict, items: list[dict]) -> dict[str, str]:
    prefix_to_id = {it.get("prefix"): _norm_id(it["item_id"]) for it in items if it.get("prefix")}
    result = {}
    for prefix, docs in buckets.items():
        iid = prefix_to_id.get(prefix, prefix)
        for d in docs:
            result[d["filename"]] = iid
    return result

regex_map = _buckets_to_map(regex_buckets, regex_items)
llm_map = _buckets_to_map(llm_buckets, llm_items or regex_items)

# Display table
header = "| Filename | Regex → | LLM → | Match? |\n|---|---|---|---|\n"
rows_md: list[str] = []
for fn in sorted(filenames):
    r_assign = regex_map.get(fn, "other")
    l_assign = llm_map.get(fn, "other")
    match = "✅" if _norm_id(r_assign) == _norm_id(l_assign) else "⚠️"
    rows_md.append(f"| `{fn}` | {r_assign} | {l_assign} | {match} |")

st.markdown(header + "\n".join(rows_md))

# Summary
agree_count = sum(1 for fn in filenames if _norm_id(regex_map.get(fn, "")) == _norm_id(llm_map.get(fn, "")))
st.metric("Document assignment agreement", f"{agree_count}/{len(filenames)}")

# ---------------------------------------------------------------------------
# Step 6: Raw extracted text (for debugging prompts)
# ---------------------------------------------------------------------------

with st.expander("Raw agenda text sent to LLM", expanded=False):
    st.code(agenda_text[:5000] + ("..." if len(agenda_text) > 5000 else ""), language="markdown")
