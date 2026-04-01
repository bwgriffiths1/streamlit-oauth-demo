"""
v2_pages/editor.py — Summary Editor

Key design: a SINGLE text area key ("editor_ta") is always rendered.
Streamlit never clears a widget key that is always on screen, so edits
survive item navigation without fighting the engine's state-clearing.

On item change the current text is flushed to `pending_edits` and the
new item's text (from pending_edits or DB) is loaded into the widget.
Autosave to DB happens on every item switch so changes survive a full
browser/session restart.
"""
import os
import streamlit as st

import pipeline.db_new as db
from pipeline.summarizer import make_client, run_meeting_summarization

st.set_page_config(page_title="Summary Editor", layout="wide")
st.title("📝 Summary Editor")

# ── Persistent stores (plain dicts — never widget keys, never cleared) ───────
if "pending_edits" not in st.session_state:
    st.session_state["pending_edits"] = {}
pending_edits: dict[str, str] = st.session_state["pending_edits"]

def _ek(entity_type: str, entity_id: int) -> str:
    return f"{entity_type}:{entity_id}"

def _has_pending(et: str, eid: int, db_text: str) -> bool:
    return pending_edits.get(_ek(et, eid), db_text) != (db_text or "")

# ── Cascading meeting selector: Venue → Committee → Date ────────────────────
all_meetings = db.list_meetings(limit=200)
if not all_meetings:
    st.info("No meetings yet — add one via Add Meeting.")
    st.stop()

c1, c2, c3 = st.columns(3)

with c1:
    venues = db.get_venues(active_only=False)
    venue_shorts = sorted(set(v["short_name"] for v in venues))
    def_venue = max(
        venue_shorts,
        key=lambda vs: sum(1 for m in all_meetings if m.get("venue_short") == vs),
        default=venue_shorts[0],
    )
    sel_venue = st.selectbox("Venue", venue_shorts,
                             index=venue_shorts.index(def_venue),
                             key="editor_venue")

with c2:
    committee_shorts = sorted(set(
        m.get("type_short", "") for m in all_meetings
        if m.get("venue_short") == sel_venue and m.get("type_short")
    ))
    if not committee_shorts:
        st.info("No committees for this venue.")
        st.stop()
    if st.session_state.get("_ev_prev") != sel_venue:
        for k in ("editor_committee", "editor_date_idx", "editor_sel_idx"):
            st.session_state.pop(k, None)
        st.session_state["_ev_prev"] = sel_venue
    sel_committee = st.selectbox("Committee", committee_shorts, key="editor_committee")

with c3:
    mtgs = sorted(
        [m for m in all_meetings
         if m.get("venue_short") == sel_venue and m.get("type_short") == sel_committee],
        key=lambda x: x.get("meeting_date") or "", reverse=True,
    )
    if not mtgs:
        st.info("No meetings for this committee.")
        st.stop()
    if st.session_state.get("_ec_prev") != sel_committee:
        for k in ("editor_date_idx", "editor_sel_idx"):
            st.session_state.pop(k, None)
        st.session_state["_ec_prev"] = sel_committee
    date_labels = [str(m.get("meeting_date", "Unknown")) for m in mtgs]
    if st.session_state.get("editor_date_idx", 0) >= len(mtgs):
        st.session_state["editor_date_idx"] = 0
    sel_date = st.selectbox("Date", range(len(date_labels)),
                            format_func=lambda i: date_labels[i],
                            key="editor_date_idx")
    selected_meeting = mtgs[sel_date]
    selected_id      = selected_meeting["id"]

if st.session_state.get("_em_prev") != selected_id:
    st.session_state.pop("editor_sel_idx", None)
    st.session_state["_em_prev"] = selected_id

# ── Build editable-item list ─────────────────────────────────────────────────
all_agenda = db.get_agenda_items(selected_id)

entries: list[tuple[str, str, int, dict]] = []
for item in all_agenda:
    summ = db.get_current_summary("agenda_item", item["id"])
    if summ and summ.get("detailed"):
        lbl = f"{item.get('item_id','?')}  —  {(item.get('title') or 'Untitled')[:55]}"
        entries.append((lbl, "agenda_item", item["id"], summ))

mtg_summ = db.get_current_summary("meeting", selected_id)
if mtg_summ and mtg_summ.get("detailed"):
    entries.append(("📋  Meeting Briefing", "meeting", selected_id, mtg_summ))

if not entries:
    st.info("No summaries yet — run summarization from the Meetings page first.")
    st.stop()

# ── Recover DB autosaves once per meeting load (session-loss protection) ─────
rec_key = f"_asl_{selected_id}"
if not st.session_state.get(rec_key):
    recovered = 0
    for _, et, eid, summ in entries:
        ek = _ek(et, eid)
        if ek in pending_edits:
            continue
        saved = db.get_autosave(et, eid)
        if saved and saved.get("detailed"):
            db_txt = summ.get("detailed") or ""
            if saved["detailed"] != db_txt:
                pending_edits[ek] = saved["detailed"]
                recovered += 1
    if recovered:
        st.info(f"↩ Recovered {recovered} autosaved draft(s) from a previous session.")
    st.session_state[rec_key] = True

# ── Item dropdown ─────────────────────────────────────────────────────────────
n_pending = sum(1 for _, et, eid, s in entries
                if _has_pending(et, eid, s.get("detailed") or ""))
dd_labels = [
    ("✏️  " if _has_pending(et, eid, s.get("detailed") or "") else "      ") + lbl
    for lbl, et, eid, s in entries
]
note = f" — **{n_pending} unsaved change(s)**" if n_pending else ""

if st.session_state.get("editor_sel_idx", 0) >= len(entries):
    st.session_state["editor_sel_idx"] = 0

sel_idx = st.selectbox(
    f"Select item to edit{note}",
    range(len(dd_labels)),
    format_func=lambda i: dd_labels[i],
    key="editor_sel_idx",
)

_, entity_type, entity_id, current_summ = entries[sel_idx]
db_text = current_summ.get("detailed") or ""
ek      = _ek(entity_type, entity_id)

# ── Swap text-area content when item changes ──────────────────────────────────
# Using a SINGLE permanent key "editor_ta" avoids Streamlit's widget-key clearing.
curr_item = (entity_type, entity_id)
prev_item = st.session_state.get("_eip")   # _eip = editor item previous

if prev_item is None:
    # Very first render — seed from pending_edits or DB
    st.session_state["editor_ta"] = pending_edits.get(ek, db_text)
    st.session_state["_eip"] = curr_item

elif prev_item != curr_item:
    # Item changed — flush previous item's live text into pending_edits
    prev_text = st.session_state.get("editor_ta", "")
    prev_et, prev_eid = prev_item
    prev_ek   = _ek(prev_et, prev_eid)
    prev_summ = next((s for _, et, eid, s in entries if (et, eid) == prev_item), None)
    prev_db   = (prev_summ.get("detailed") or "") if prev_summ else ""

    pending_edits[prev_ek] = prev_text

    # Autosave previous item to DB (best-effort, non-blocking)
    if prev_text != prev_db:
        try:
            db.autosave_summary(prev_et, prev_eid, prev_text,
                                one_line=(prev_summ or {}).get("one_line"))
        except Exception:
            pass

    # Load new item's text into the widget
    st.session_state["editor_ta"] = pending_edits.get(ek, db_text)
    st.session_state["_eip"] = curr_item

st.divider()

# ── Metadata header ───────────────────────────────────────────────────────────
if entity_type == "agenda_item":
    item = next((it for it in all_agenda if it["id"] == entity_id), {})
    hc = st.columns([4, 2, 1, 1])
    with hc[0]:
        st.markdown(f"**{item.get('item_id','')}  —  {item.get('title','Untitled')}**")
    with hc[1]:
        if item.get("presenter"):
            st.caption(f"👤 {item['presenter']}"
                       + (f" / {item['org']}" if item.get("org") else ""))
    with hc[2]:
        if item.get("vote_status"):
            st.caption(f"🗳️ {item['vote_status']}")
    with hc[3]:
        icon = "✅" if current_summ.get("status") == "approved" else "📄"
        st.caption(f"{icon} v{current_summ.get('version','?')} · {current_summ.get('status','?')}")
else:
    hc = st.columns([5, 1])
    with hc[0]:
        st.markdown("**Meeting Briefing**")
    with hc[1]:
        icon = "✅" if current_summ.get("status") == "approved" else "📄"
        st.caption(f"{icon} v{current_summ.get('version','?')} · {current_summ.get('status','?')}")

# ── Text area — single permanent key, always rendered ─────────────────────────
st.text_area("Summary text", key="editor_ta", height=520, label_visibility="collapsed")

# Sync live widget value → pending_edits on every render
pending_edits[ek] = st.session_state.get("editor_ta", db_text)

if _has_pending(entity_type, entity_id, db_text):
    st.caption("✏️ Unsaved — autosaved as draft on next navigation; click Save All to lock in")

# ── Version history / Revert ─────────────────────────────────────────────────
with st.expander("Version history / Revert", expanded=False):
    versions = db.list_summary_versions(entity_type, entity_id)
    if versions:
        ver_labels = [
            f"v{v['version']} · {v.get('status','?')} · "
            f"{str(v.get('created_at') or '')[:16]}"
            + (" · autosave" if v.get("created_by") == "autosave" else
               " · manual"  if v.get("is_manual")               else "")
            for v in versions
        ]
        rev_idx = st.selectbox("Revert to", range(len(ver_labels)),
                               format_func=lambda i: ver_labels[i],
                               key="revert_sel")
        if st.button("↩ Revert to selected version"):
            reverted = versions[rev_idx].get("detailed") or ""
            pending_edits[ek]            = reverted
            st.session_state["editor_ta"] = reverted
            st.rerun()
    else:
        st.caption("No version history yet.")

# ── Action buttons ────────────────────────────────────────────────────────────
st.divider()
bc1, bc2, bc3, _ = st.columns([2, 2, 2, 2])

with bc1:
    if st.button("💾 Save All Changes", type="primary",
                 use_container_width=True, disabled=(n_pending == 0)):
        saved = 0
        for _, et, eid, summ in entries:
            new_txt = pending_edits.get(_ek(et, eid), summ.get("detailed") or "")
            if new_txt != (summ.get("detailed") or ""):
                db.save_manual_summary(
                    entity_type=et, entity_id=eid,
                    one_line=summ.get("one_line"), detailed=new_txt,
                )
                db.clear_autosave(et, eid)
                saved += 1
        st.session_state["pending_edits"] = {}
        st.session_state.pop("editor_ta", None)
        st.session_state.pop("_eip", None)
        st.session_state.pop(rec_key, None)
        st.success(f"Saved {saved} change(s).")
        st.rerun()

with bc2:
    api_key_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not api_key_ok:
        st.warning("API key not set", icon="⚠️")
    elif st.button("🔄 Re-run Rollups (L2 + L3)", use_container_width=True):
        with st.status("Re-running rollups…", expanded=True) as sb:
            def _prog(msg: str) -> None:
                st.write(msg)
            try:
                client  = make_client()
                results = run_meeting_summarization(
                    meeting_id=selected_id,
                    client=client,
                    committee_short=selected_meeting.get("type_short", "MC"),
                    venue_short=selected_meeting.get("venue_short", "ISO-NE"),
                    progress_fn=_prog,
                    force_rerun=True,
                    start_level=2,
                )
                n2, n3 = results["level2"], results["level3"]
                errs   = results.get("errors", [])
                if errs:
                    sb.update(label=f"Completed with {len(errs)} error(s).",
                              state="error", expanded=True)
                    for e in errs:
                        st.error(e)
                else:
                    sb.update(
                        label=f"Done — {n2} rollup(s), briefing {'✓' if n3 else '—'}.",
                        state="complete", expanded=False,
                    )
                    st.session_state["pending_edits"] = {}
                    st.session_state.pop("editor_ta", None)
                    st.session_state.pop("_eip", None)
                    st.rerun()
            except Exception as exc:
                sb.update(label=f"Failed: {exc}", state="error")
                st.error(str(exc))

with bc3:
    if st.button("✖ Discard All Edits", use_container_width=True, disabled=(n_pending == 0)):
        for _, et, eid, _ in entries:
            db.clear_autosave(et, eid)
        st.session_state["pending_edits"] = {}
        st.session_state.pop("editor_ta", None)
        st.session_state.pop("_eip", None)
        st.rerun()
