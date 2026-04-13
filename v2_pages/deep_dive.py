"""
v2_pages/deep_dive.py — Deep Dive / Special Report page.

Three-phase workflow:
  1. Document Selection (manual pick or tag-based discovery)
  2. Configuration & Generation
  3. Review & Download
"""
import streamlit as st

import pipeline.db_new as db

st.set_page_config(page_title="Deep Dive", layout="wide")
st.title("🔬 Deep Dive — Special Report")

# ── Session state init ───────────────────────────────────────────────────────
if "dd_selected_docs" not in st.session_state:
    st.session_state["dd_selected_docs"] = {}  # {doc_id: doc_dict}
if "dd_active_report" not in st.session_state:
    st.session_state["dd_active_report"] = None

selected_docs: dict[int, dict] = st.session_state["dd_selected_docs"]

# ── Previous Reports ─────────────────────────────────────────────────────────
with st.expander("📂 Previous Reports", expanded=False):
    prev_reports = db.list_deep_dive_reports(limit=20)
    if not prev_reports:
        st.info("No previous reports.")
    else:
        for rpt in prev_reports:
            c1, c2, c3 = st.columns([4, 2, 1])
            with c1:
                st.write(f"**{rpt['title']}**")
            with c2:
                status_icon = {"draft": "📝", "generating": "⏳",
                               "complete": "✅", "error": "❌"}.get(rpt["status"], "?")
                st.write(f"{status_icon} {rpt['status']}  ·  {rpt['created_at']:%Y-%m-%d}")
            with c3:
                if rpt["status"] == "complete" and st.button("Load", key=f"load_{rpt['id']}"):
                    st.session_state["dd_active_report"] = rpt["id"]
                    st.rerun()

# ── If an active report is loaded, jump to Review phase ──────────────────────
if st.session_state["dd_active_report"]:
    report = db.get_deep_dive_report(st.session_state["dd_active_report"])
    if report and report["status"] == "complete" and report.get("report_md"):
        st.divider()
        st.subheader(f"📄 {report['title']}")

        report_docs = db.get_deep_dive_documents(report["id"])
        doc_names = [d["filename"] for d in report_docs]

        # Editable report text
        edited_md = st.text_area(
            "Report (markdown — edit freely)",
            value=report["report_md"],
            height=500,
            key=f"dd_edit_{report['id']}",
        )

        # Save edits
        if edited_md != report["report_md"]:
            if st.button("💾 Save Edits"):
                db.update_deep_dive_report(report["id"], report_md=edited_md)
                st.success("Saved.")
                st.rerun()

        # Preview
        with st.expander("Preview", expanded=False):
            from pipeline.summarizer import _clean_output
            st.markdown(_clean_output(edited_md))

        # Download
        col_dl, col_back = st.columns([1, 1])
        with col_dl:
            from pipeline.briefing import generate_deep_dive_docx_bytes
            dates = sorted(set(str(d.get("meeting_date", "")) for d in report_docs))
            date_range = ", ".join(dates)
            docx_bytes = generate_deep_dive_docx_bytes(
                edited_md,
                title=report["title"],
                document_names=doc_names,
                date_range=date_range,
            )
            st.download_button(
                "⬇️ Download .docx",
                data=docx_bytes,
                file_name=f"{report['title'][:50]} Special Report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col_back:
            if st.button("← New Report"):
                st.session_state["dd_active_report"] = None
                st.rerun()
        st.stop()
    elif report and report["status"] == "error":
        st.error(f"Report failed: {report.get('error_message', 'Unknown error')}")
        if st.button("← Back"):
            st.session_state["dd_active_report"] = None
            st.rerun()
        st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: Document Selection
# ═══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("1. Select Documents")

tab_manual, tab_tags, tab_search = st.tabs(["📋 By Meeting", "🏷️ By Tag", "🔍 Search"])

# ── Manual selection ─────────────────────────────────────────────────────────
with tab_manual:
    all_meetings = db.list_meetings(limit=200)
    if not all_meetings:
        st.info("No meetings ingested yet.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            venues = sorted(set(m.get("venue_short", "") for m in all_meetings if m.get("venue_short")))
            sel_venue = st.selectbox("Venue", venues, key="dd_venue")
        with c2:
            committees = sorted(set(
                m.get("type_short", "") for m in all_meetings
                if m.get("venue_short") == sel_venue and m.get("type_short")
            ))
            sel_committee = st.selectbox("Committee", committees, key="dd_committee") if committees else None
        with c3:
            if sel_committee:
                mtgs = sorted(
                    [m for m in all_meetings
                     if m.get("venue_short") == sel_venue and m.get("type_short") == sel_committee],
                    key=lambda x: x.get("meeting_date", ""), reverse=True,
                )
                date_labels = [str(m.get("meeting_date", "")) for m in mtgs]
                sel_idx = st.selectbox("Meeting Date", range(len(date_labels)),
                                       format_func=lambda i: date_labels[i],
                                       key="dd_meeting_idx")
                sel_meeting = mtgs[sel_idx] if mtgs else None
            else:
                sel_meeting = None

        if sel_meeting:
            docs = db.get_documents_for_meeting(sel_meeting["id"])
            if not docs:
                st.info("No documents for this meeting.")
            else:
                st.write(f"**{len(docs)} documents** from {sel_venue} {sel_committee} {sel_meeting.get('meeting_date', '')}")
                for doc in docs:
                    already = doc["id"] in selected_docs
                    col_chk, col_name = st.columns([1, 8])
                    with col_chk:
                        checked = st.checkbox(
                            "sel", value=already, label_visibility="collapsed",
                            key=f"dd_doc_{doc['id']}",
                        )
                    with col_name:
                        ft = doc.get("file_type", "")
                        st.write(f"`{doc['filename']}` {ft}")
                    if checked and not already:
                        # Attach meeting context
                        doc["meeting_date"] = sel_meeting.get("meeting_date")
                        doc["type_short"] = sel_meeting.get("type_short")
                        doc["type_name"] = sel_meeting.get("type_name", "")
                        doc["venue_short"] = sel_meeting.get("venue_short")
                        selected_docs[doc["id"]] = doc
                    elif not checked and already:
                        selected_docs.pop(doc["id"], None)

# ── Tag-based discovery ──────────────────────────────────────────────────────
with tab_tags:
    all_tags = db.list_all_tags()
    if not all_tags:
        st.info("No tags defined yet. Tag documents on the Meetings page first.")
    else:
        tag_names = [t["name"] for t in all_tags]
        sel_tags = st.multiselect("Select tags", tag_names, key="dd_tags")
        if sel_tags:
            for tag_name in sel_tags:
                tag_docs = db.search_documents_by_tag(tag_name)
                if tag_docs:
                    st.write(f"**{tag_name}** — {len(tag_docs)} document(s)")
                    for doc in tag_docs:
                        already = doc["id"] in selected_docs
                        col_chk, col_name = st.columns([1, 8])
                        with col_chk:
                            checked = st.checkbox(
                                "sel", value=already, label_visibility="collapsed",
                                key=f"dd_tag_doc_{doc['id']}",
                            )
                        with col_name:
                            meeting_label = f"{doc.get('venue_short','')} {doc.get('type_short','')} {doc.get('meeting_date','')}"
                            st.write(f"`{doc['filename']}` — {meeting_label}")
                        if checked and not already:
                            selected_docs[doc["id"]] = doc
                        elif not checked and already:
                            selected_docs.pop(doc["id"], None)

# ── Filename search ──────────────────────────────────────────────────────────
with tab_search:
    query = st.text_input("Search by filename", key="dd_search_query")
    if query and len(query) >= 2:
        results = db.search_documents_by_text(query, limit=30)
        if not results:
            st.info("No documents match.")
        else:
            st.write(f"**{len(results)} result(s)**")
            for doc in results:
                already = doc["id"] in selected_docs
                col_chk, col_name = st.columns([1, 8])
                with col_chk:
                    checked = st.checkbox(
                        "sel", value=already, label_visibility="collapsed",
                        key=f"dd_srch_doc_{doc['id']}",
                    )
                with col_name:
                    meeting_label = f"{doc.get('venue_short','')} {doc.get('type_short','')} {doc.get('meeting_date','')}"
                    st.write(f"`{doc['filename']}` — {meeting_label}")
                if checked and not already:
                    selected_docs[doc["id"]] = doc
                elif not checked and already:
                    selected_docs.pop(doc["id"], None)

# ── Selected documents summary ───────────────────────────────────────────────
st.divider()
if selected_docs:
    st.write(f"**{len(selected_docs)} document(s) selected:**")
    for doc_id, doc in list(selected_docs.items()):
        col_name, col_rm = st.columns([8, 1])
        with col_name:
            meeting_label = f"{doc.get('venue_short','')} {doc.get('type_short','')} {doc.get('meeting_date','')}"
            st.write(f"- `{doc['filename']}` — {meeting_label}")
        with col_rm:
            if st.button("✕", key=f"dd_rm_{doc_id}"):
                selected_docs.pop(doc_id, None)
                st.rerun()
else:
    st.info("Select at least one document above to begin.")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: Configuration & Generation
# ═══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("2. Configure & Generate")

c1, c2, c3 = st.columns(3)
with c1:
    # Auto-generate title from document names
    auto_title = " + ".join(
        d["filename"].rsplit(".", 1)[0][:30] for d in list(selected_docs.values())[:3]
    )
    if len(selected_docs) > 3:
        auto_title += f" (+{len(selected_docs)-3} more)"
    report_title = st.text_input("Report title", value=auto_title, key="dd_title")

with c2:
    max_images = st.number_input("Max images", min_value=0, max_value=50,
                                  value=20, key="dd_max_images")

with c3:
    from pipeline.summarizer import HAIKU, SONNET, OPUS, load_model_config
    model_cfg = load_model_config()
    model_options = {"Haiku (fast/cheap)": HAIKU, "Sonnet": SONNET, "Opus (best)": OPUS}
    default_model = model_cfg.get("meeting_model", HAIKU)
    default_label = next(
        (k for k, v in model_options.items() if v == default_model),
        list(model_options.keys())[0],
    )
    model_label = st.selectbox("Model", list(model_options.keys()),
                                index=list(model_options.keys()).index(default_label),
                                key="dd_model")
    model_id = model_options[model_label]

comparison_mode = st.checkbox("Compare across meetings (evolution over time)",
                               value=len(set(d.get("meeting_date") for d in selected_docs.values())) > 1,
                               key="dd_comparison")

if st.button("🚀 Generate Report", type="primary"):
    from pipeline.deep_dive import run_deep_dive
    from pipeline.summarizer import make_client

    config = {
        "max_images": max_images,
        "comparison_mode": comparison_mode,
    }

    # Create report record
    report = db.create_deep_dive_report(
        title=report_title,
        config=config,
        prompt_slug="deep_dive_prompt",
        model_id=model_id,
    )

    # Link documents
    for seq, (doc_id, doc) in enumerate(selected_docs.items()):
        db.add_deep_dive_document(report["id"], doc_id, seq=seq)

    with st.status("Generating deep dive report…", expanded=True) as status_box:
        def _progress(msg: str) -> None:
            st.write(msg)
        try:
            client = make_client()
            success = run_deep_dive(
                report["id"],
                client=client,
                progress_fn=_progress,
            )
            if success:
                status_box.update(label="Report generated successfully!",
                                  state="complete", expanded=False)
                st.session_state["dd_active_report"] = report["id"]
                st.session_state["dd_selected_docs"] = {}
                st.rerun()
            else:
                updated = db.get_deep_dive_report(report["id"])
                err = updated.get("error_message", "Unknown error") if updated else "Unknown error"
                status_box.update(label=f"Generation failed: {err}", state="error")
        except Exception as exc:
            db.update_deep_dive_report(report["id"], status="error",
                                       error_message=str(exc))
            status_box.update(label=f"Generation failed: {exc}", state="error")
            st.error(str(exc))
