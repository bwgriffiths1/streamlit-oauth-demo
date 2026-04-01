"""
v2_pages/settings.py — App configuration and committee scraper settings.
"""
import copy

import streamlit as st
import yaml
from dotenv import load_dotenv

import pipeline.db_new as db

load_dotenv()

CONFIG_PATH = "config.yaml"

st.set_page_config(page_title="Settings", layout="wide")
st.title("Settings")


# ---------------------------------------------------------------------------
# Load / save helpers
# ---------------------------------------------------------------------------

def _load() -> dict:
    with open(CONFIG_PATH) as fh:
        return yaml.safe_load(fh)


def _save(config: dict) -> None:
    with open(CONFIG_PATH, "w") as fh:
        yaml.dump(config, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# Committee scraper configuration
# ---------------------------------------------------------------------------

st.subheader("Committees to Scrape")
st.caption(
    "Each row defines a committee whose ISO-NE calendar page will be scraped "
    "when **Refresh Upcoming Meetings** is run from the Overview page. "
    "**Short** must match the committee short name already in the database (MC, RC, NPC, TC…)."
)

config = _load()
committees = config.get("committees", [])

# Normalise to consistent keys
_rows = [
    {
        "name":   c.get("name", ""),
        "short":  c.get("short", ""),
        "url":    c.get("url", ""),
        "active": bool(c.get("active", True)),
    }
    for c in committees
]

edited = st.data_editor(
    _rows,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "name":   st.column_config.TextColumn("Committee Name", width="medium"),
        "short":  st.column_config.TextColumn("Short", width="small"),
        "url":    st.column_config.TextColumn("Calendar URL", width="large"),
        "active": st.column_config.CheckboxColumn("Active", width="small"),
    },
    key="committees_editor",
)

col_save, col_reset = st.columns([1, 6])
with col_save:
    if st.button("Save committees", type="primary"):
        # Drop completely empty rows that the editor may append
        clean = [r for r in edited if r.get("name") or r.get("url")]
        new_config = copy.deepcopy(config)
        new_config["committees"] = clean
        _save(new_config)
        venue = db.get_venue("ISO-NE")
        if venue:
            for row in clean:
                if row.get("short") and row.get("name"):
                    db.create_meeting_type(venue["id"], row["name"], row["short"])
        st.success("Saved.")
        st.rerun()
with col_reset:
    if st.button("Discard changes"):
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Scraper lookahead window
# ---------------------------------------------------------------------------

st.subheader("Scraper Settings")

lookahead = config.get("lookahead_days", 60)
new_lookahead = st.number_input(
    "Lookahead days",
    min_value=7,
    max_value=365,
    value=lookahead,
    step=7,
    help="How many calendar days ahead to scan for upcoming meetings.",
)

if st.button("Save scraper settings"):
    new_config = copy.deepcopy(config)
    new_config["lookahead_days"] = int(new_lookahead)
    _save(new_config)
    st.success("Saved.")
    st.rerun()
