"""
v2_pages/prompt_library.py — Prompt Library

Structure:
  General Context (shared) | Document Summary (shared) | Venue Prompts | Model Config
    Venue Prompts → venue tabs (from DB) → Briefing | Agenda Item tabs
      → committee sub-tabs (from DB for that venue)
    Model Config → selectbox per summarization level → saved to model_config.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
import pipeline.db_new as db

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Available models (label → model_id)
_MODELS = {
    "Haiku (fast, cheap)":   "claude-haiku-4-5-20251001",
    "Sonnet (balanced)":     "claude-sonnet-4-6",
    "Opus (most capable)":   "claude-opus-4-6",
}
_MODEL_IDS   = list(_MODELS.values())
_MODEL_LABELS = list(_MODELS.keys())

def _model_label(model_id: str) -> str:
    for label, mid in _MODELS.items():
        if mid == model_id:
            return label
    return model_id


# ── Prompt file helpers ────────────────────────────────────────────────────────

def _load_prompt(slug: str) -> str:
    path = PROMPTS_DIR / f"{slug}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _save_prompt(slug: str, content: str) -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPTS_DIR / f"{slug}.md"
    path.write_text(content, encoding="utf-8")


# ── Reusable editor widget ─────────────────────────────────────────────────────

def _prompt_editor(slug: str, key: str) -> None:
    content = _load_prompt(slug)
    new_content = st.text_area(
        slug,
        value=content,
        height=500,
        key=key,
        label_visibility="collapsed",
    )
    if st.button("💾 Save", key=f"save_{key}"):
        _save_prompt(slug, new_content)
        st.success("Saved.")


# ── Main ───────────────────────────────────────────────────────────────────────

def _model_config_tab() -> None:
    """Render the Model Config tab content."""
    st.subheader("Summarization Models")
    st.caption(
        "Choose which model to use at each summarization level. "
        "Haiku is recommended while testing — it's the fastest and cheapest."
    )

    # Load existing config
    cfg_path = PROMPTS_DIR / "model_config.json"
    current: dict = {}
    if cfg_path.exists():
        try:
            current = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    default_doc  = current.get("document_model", "claude-haiku-4-5-20251001")
    default_item = current.get("item_model",     "claude-haiku-4-5-20251001")
    default_mtg  = current.get("meeting_model",  "claude-haiku-4-5-20251001")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Level 1 — Document group**")
        st.caption("Summarises all docs at each agenda item")
        doc_idx = _MODEL_IDS.index(default_doc) if default_doc in _MODEL_IDS else 0
        doc_label = st.selectbox(
            "Document model", _MODEL_LABELS,
            index=doc_idx, key="cfg_doc_model", label_visibility="collapsed",
        )

    with col2:
        st.markdown("**Level 2 — Item rollup**")
        st.caption("Synthesises child items into parent summaries")
        item_idx = _MODEL_IDS.index(default_item) if default_item in _MODEL_IDS else 0
        item_label = st.selectbox(
            "Item model", _MODEL_LABELS,
            index=item_idx, key="cfg_item_model", label_visibility="collapsed",
        )

    with col3:
        st.markdown("**Level 3 — Meeting briefing**")
        st.caption("Generates the full meeting briefing")
        mtg_idx = _MODEL_IDS.index(default_mtg) if default_mtg in _MODEL_IDS else 0
        mtg_label = st.selectbox(
            "Meeting model", _MODEL_LABELS,
            index=mtg_idx, key="cfg_mtg_model", label_visibility="collapsed",
        )

    st.divider()
    if st.button("💾 Save Model Config", type="primary"):
        config = {
            "document_model": _MODELS[doc_label],
            "item_model":     _MODELS[item_label],
            "meeting_model":  _MODELS[mtg_label],
        }
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        st.success(
            f"Saved — Document: **{doc_label}** · "
            f"Item: **{item_label}** · "
            f"Meeting: **{mtg_label}**"
        )


def main() -> None:
    st.title("✏️ Prompt Library")
    st.caption("Edit the prompts used by the summarization pipeline.")

    tab_ctx, tab_doc, tab_venue, tab_models = st.tabs([
        "🌐 General Context",
        "📄 Document Summary",
        "🏛️ Venue Prompts",
        "⚙️ Model Config",
    ])

    # ── Shared: General Context ────────────────────────────────────────────────
    with tab_ctx:
        st.markdown(
            "This text is **prepended to every briefing and agenda-item prompt** before "
            "sending to the model. Use it to describe your portfolio, acronyms, and "
            "standing areas of interest."
        )
        _prompt_editor("general_context_prompt", "general_context_editor")

    # ── Shared: Document Summary ───────────────────────────────────────────────
    with tab_doc:
        st.caption("Applied to every downloaded document across all venues and committees.")
        _prompt_editor("doc_summary_prompt", "doc_prompt_editor")

    # ── Venue Prompts ──────────────────────────────────────────────────────────
    with tab_venue:
        venues = db.get_venues()
        if not venues:
            st.info("No venues found in the database.")
            return

        venue_tabs = st.tabs([v["short_name"] for v in venues])

        for venue_tab, venue in zip(venue_tabs, venues):
            with venue_tab:
                st.caption(venue.get("name") or venue["short_name"])

                committees = db.get_meeting_types(venue["short_name"])
                if not committees:
                    st.info("No committees configured for this venue.")
                    continue

                tab_brief, tab_item = st.tabs([
                    "📋 Briefing Prompts",
                    "📝 Agenda Item Prompts",
                ])

                _VENUE_SLUG_MAP = {"ISO-NE": "isone", "NYISO": "nyiso"}
                venue_slug = _VENUE_SLUG_MAP.get(
                    venue["short_name"],
                    venue["short_name"].lower().replace("-", "").replace(" ", ""),
                )

                with tab_brief:
                    st.caption(
                        "Committee-specific prompts for generating meeting briefings. "
                        "General Context is prepended at runtime."
                    )
                    comm_tabs = st.tabs([c["short_name"] for c in committees])
                    for ct, c in zip(comm_tabs, committees):
                        with ct:
                            comm_slug = c["short_name"].lower()
                            slug = f"{venue_slug}_{comm_slug}_briefing_prompt"
                            key = f"brief_{comm_slug}_{venue_slug}_editor"
                            if not _load_prompt(slug):
                                st.caption(f"No prompt file yet — will be created at `prompts/{slug}.md` on save.")
                            _prompt_editor(slug, key)

                with tab_item:
                    st.caption(
                        "Committee-specific prompts for summarising individual agenda items. "
                        "General Context is prepended at runtime."
                    )
                    comm_tabs2 = st.tabs([c["short_name"] for c in committees])
                    for ct, c in zip(comm_tabs2, committees):
                        with ct:
                            comm_slug = c["short_name"].lower()
                            slug = f"{venue_slug}_{comm_slug}_agenda_item_prompt"
                            key = f"item_{comm_slug}_{venue_slug}_editor"
                            if not _load_prompt(slug):
                                st.caption(f"No prompt file yet — will be created at `prompts/{slug}.md` on save.")
                            _prompt_editor(slug, key)

    # ── Model Config ──────────────────────────────────────────────────────────
    with tab_models:
        _model_config_tab()


main()
