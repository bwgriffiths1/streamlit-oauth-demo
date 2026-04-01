"""
08_agenda_debug.py — Agenda Parser Debug Tool

Standalone diagnostic page: enter an event ID, scrape docs, parse the agenda,
and display a report showing parsed items and file-to-item assignments.
No DB, no summarization — just pure parsing diagnostics.
"""
import re
import sys
import zipfile
from pathlib import Path

# Ensure project root is on sys.path when running standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import streamlit as st
from pipeline.downloader import check_url, download_file_temp
from pipeline.scraper import fetch_event_docs

from pipeline.agenda_parser import (
    item_id_to_prefix as _item_id_to_prefix,
    parse_agenda_from_docx,
    map_docs_to_agenda_items,
)
from pipeline.llm_agenda_parser import parse_agenda_hybrid


# ── UI ───────────────────────────────────────────────────────────────────────

st.title("Agenda Parser Debug")

col1, col2 = st.columns([3, 1])
with col1:
    raw_input = st.text_input("Event ID or URL", value="160091",
                              help="Paste a bare ID (160113) or a full ISO-NE event URL")
with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    go = st.button("Go", type="primary")

# Extract numeric ID from whatever was pasted
_m = re.search(r"eventId=(\d+)", raw_input)
event_id = _m.group(1) if _m else re.sub(r"\D", "", raw_input)

if not go:
    st.info("Enter an ISO-NE event ID and click **Go** to run the agenda parser diagnostic.")
    st.stop()

if not event_id:
    st.error("Could not extract a numeric event ID — please enter a valid ID or URL.")
    st.stop()

event_url = f"https://www.iso-ne.com/event-details?eventId={event_id}"
st.caption(f"Event ID: **{event_id}** — {event_url}")

# ── Step 1: Fetch document links via JSON API ────────────────────────────────

session = requests.Session()
with st.spinner("Fetching document list from ISO-NE API..."):
    doc_links = fetch_event_docs(event_id, session=session)

if not doc_links:
    st.warning("No document links found. Materials may not be posted yet.")
    st.stop()

st.success(f"Found **{len(doc_links)}** document link(s).")

# ── Step 2: Probe each URL for metadata ─────────────────────────────────────
docs_meta: list[dict] = []
with st.spinner("Probing document URLs..."):
    for link in doc_links:
        meta = check_url(url=link["url"], referer_url=event_url, session=session)
        docs_meta.append(meta)

# ── Step 3: Find and parse the agenda .docx ─────────────────────────────────

agenda_doc = None
for meta in docs_meta:
    if "agenda" in meta["filename"].lower() and meta["file_type"] in ("docx", "pdf") and not meta["ceii_skipped"]:
        agenda_doc = meta
        break

if agenda_doc is None:
    st.error("No agenda .docx found among the documents.")
    st.subheader("Documents Found")
    for m in docs_meta:
        ceii = " [CEII]" if m["ceii_skipped"] else ""
        st.text(f"  {m['filename']}  ({m['file_type']}){ceii}")
    st.stop()

with st.spinner(f"Downloading agenda: {agenda_doc['filename']}..."):
    with download_file_temp(
        url=agenda_doc["source_url"],
        filename=agenda_doc["filename"],
        referer_url=event_url,
        session=session,
    ) as tmp_path:
        if tmp_path is None:
            st.error("Agenda download returned CEII/403.")
            st.stop()
        agenda_bytes = Path(tmp_path).read_bytes()
        if agenda_doc["file_type"] == "pdf":
            # PDF agendas need the LLM parser (regex only handles docx)
            agenda_items, _ = parse_agenda_hybrid(
                agenda_bytes, "ISO-NE", "unknown", mode="llm_only",
            )
        else:
            agenda_items = parse_agenda_from_docx(agenda_bytes)

# ── Step 4: Map documents to agenda items ────────────────────────────────────

fake_rows = [{"filename": m["filename"]} for m in docs_meta]
mapping = map_docs_to_agenda_items(fake_rows, agenda_items)
meta_by_name = {m["filename"]: m for m in docs_meta}

# ── Step 5: Display report ───────────────────────────────────────────────────

# Expanders for raw details
with st.expander(f"All documents ({len(docs_meta)})", expanded=False):
    for m in docs_meta:
        ceii = " **[CEII]**" if m["ceii_skipped"] else ""
        st.markdown(f"- `{m['filename']}`  ({m['file_type']}){ceii}")

with st.expander(f"Parsed agenda items ({len(agenda_items)})", expanded=False):
    for item in agenda_items:
        depth = item["item_id"].count(".")
        pad = "&nbsp;" * (depth * 6)
        st.markdown(
            f"{pad}**{item['item_id']}** — {item['title']} &nbsp;"
            f"<span style='color:#888;font-size:0.85em'>`{item.get('prefix')}`</span>",
            unsafe_allow_html=True,
        )

st.divider()
st.subheader("File-to-Item Assignments")

# ── Helpers ──────────────────────────────────────────────────────────────────

def _file_sub_letter(filename: str, base_prefix: str) -> str:
    """Return the sub-letter suffix in the filename beyond base_prefix.
    e.g. base='a07.1', 'a07.1.b_foo.pdf' → '.b'
         base='a07.1', 'a07.1_foo.pdf'   → '.a'   (bare = first position)
    """
    rest = filename.lower()[len(base_prefix):]
    if not rest or rest[0] in ("_", "-"):
        return ".a"
    if rest.startswith(".") and len(rest) > 1 and rest[1].isalpha():
        end = 2
        while end < len(rest) and rest[end] not in ("_", "-"):
            end += 1
        return rest[:end]   # e.g. ".b", ".ii"
    return ""

def _sub_sort_key(filename: str, base_prefix: str) -> str:
    """Sort key: sub-letter character so .a < .b < .c … regardless of filename."""
    lbl = _file_sub_letter(filename, base_prefix)
    return lbl.lstrip(".") or "z"

def _file_row_html(filename: str, file_type: str, ceii: bool,
                   sub_label: str, indent_px: int) -> str:
    ceii_badge = (
        ' <span style="background:#c00;color:#fff;border-radius:3px;'
        'padding:1px 5px;font-size:0.75em">CEII</span>'
        if ceii else ""
    )
    ftype = f'<span style="color:#888"> ({file_type})</span>'
    sub_tag = (
        f'<span style="color:#4a90d9;font-size:0.8em;margin-right:6px">[{sub_label}]</span>'
        if sub_label else ""
    )
    return (
        f'<div style="margin-left:{indent_px}px;line-height:1.8">'
        f'{sub_tag}<code style="font-size:0.85em">{filename}</code>{ftype}{ceii_badge}'
        f'</div>'
    )

# ── Build display: group repeated item_ids, render files once per group ───────

from collections import Counter, defaultdict

id_counts = Counter(item["item_id"] for item in agenda_items)

# Group all items by item_id, preserving agenda order of first appearance
groups_ordered: list[str] = []           # item_ids in first-seen agenda order
groups: dict[str, list[dict]] = defaultdict(list)
for item in agenda_items:
    iid = item["item_id"]
    if iid not in groups:
        groups_ordered.append(iid)
    groups[iid].append(item)

html_lines: list[str] = []

def _parent_has_files(item_id: str) -> bool:
    """Return True if the direct parent item has any matched files."""
    parts = item_id.rsplit(".", 1)
    if len(parts) < 2:
        return True   # top-level — no parent to elide against
    parent_id = parts[0]
    if parent_id not in groups:
        return True
    parent_prefix = groups[parent_id][0].get("prefix") or ""
    return bool(mapping.get(parent_prefix))

for item_id in groups_ordered:
    group = groups[item_id]
    first = group[0]
    base_prefix = first.get("prefix") or ""
    depth = item_id.count(".")
    indent_px      = depth * 28
    title_indent   = indent_px + 22
    file_indent_px = indent_px + 22

    rows = mapping.get(base_prefix, [])
    has_files = bool(rows)

    # Elide the group header when this is an auto-sub stub whose parent has
    # no files — the parent title is already the meaningful header.
    elide_header = len(group) > 1 and not _parent_has_files(item_id)

    if len(group) == 1:
        # ── Single agenda item ────────────────────────────────────────────
        color = "#111" if has_files else "#aaa"
        prefix_hint = (
            f' <span style="color:#aaa;font-size:0.78em">[{base_prefix}]</span>'
            if base_prefix else ""
        )
        html_lines.append(
            f'<div style="margin-left:{indent_px}px;margin-top:7px;'
            f'line-height:1.5;color:{color}">'
            f'<strong>{item_id}</strong> — {first["title"]}{prefix_hint}'
            f'</div>'
        )
        # Files sorted by sub-letter
        for row in sorted(rows, key=lambda r: _sub_sort_key(r["filename"], base_prefix)):
            m = meta_by_name.get(row["filename"], {})
            sub_lbl = _file_sub_letter(row["filename"], base_prefix) if base_prefix else ""
            html_lines.append(_file_row_html(
                row["filename"], m.get("file_type", "?"),
                m.get("ceii_skipped", False), sub_lbl, file_indent_px,
            ))

    else:
        # ── Multiple agenda rows share this item_id ───────────────────────
        # Show a group header (unless elided), sub-item titles lettered a-h,
        # then ALL files once sorted by sub-letter.
        if not elide_header:
            color = "#111" if has_files else "#aaa"
            prefix_hint = (
                f' <span style="color:#aaa;font-size:0.78em">[{base_prefix}.*]</span>'
                if base_prefix else ""
            )
            auto_note = ' <span style="color:#f90;font-size:0.75em">▸ auto-sub</span>'
            html_lines.append(
                f'<div style="margin-left:{indent_px}px;margin-top:7px;'
                f'line-height:1.5;color:{color}">'
                f'<strong>{item_id}</strong>{prefix_hint}{auto_note}'
                f'</div>'
            )
        # Sub-item titles in agenda order, lettered a, b, c …
        for n, item in enumerate(group):
            letter = chr(ord("a") + n)
            html_lines.append(
                f'<div style="margin-left:{title_indent}px;line-height:1.6;'
                f'color:#555;font-size:0.9em">'
                f'<em>{letter}.</em>&nbsp;{item["title"]}'
                f'</div>'
            )
        # Files sorted by extracted sub-letter (.a first, .b, .c …)
        if rows:
            html_lines.append(
                f'<div style="margin-left:{title_indent}px;margin-top:4px;'
                f'color:#888;font-size:0.78em">files:</div>'
            )
        for row in sorted(rows, key=lambda r: _sub_sort_key(r["filename"], base_prefix)):
            m = meta_by_name.get(row["filename"], {})
            sub_lbl = _file_sub_letter(row["filename"], base_prefix) if base_prefix else ""
            html_lines.append(_file_row_html(
                row["filename"], m.get("file_type", "?"),
                m.get("ceii_skipped", False), sub_lbl, file_indent_px,
            ))

# Unmatched files
if "other" in mapping:
    html_lines.append(
        '<div style="margin-top:18px;border-top:1px solid #ddd;padding-top:8px;'
        'color:#888;font-weight:600">Unmatched files</div>'
    )
    for row in mapping["other"]:
        m = meta_by_name.get(row["filename"], {})
        html_lines.append(_file_row_html(
            row["filename"], m.get("file_type", "?"),
            m.get("ceii_skipped", False), "", 12,
        ))

st.markdown("\n".join(html_lines), unsafe_allow_html=True)

# ── Step 6: Item Metadata ─────────────────────────────────────────────────────
# Show all structured metadata extracted from description cells:
# presenter, org, vote status, meeting number, WMPP ID, initiative codes,
# free-text notes, and time slots from the third column.

_META_FIELDS = [
    ("presenter",        "Presenter"),
    ("org",              "Org"),
    ("vote_status",      "Vote"),
    ("meeting_number",   "Mtg #"),
    ("wmpp_id",          "WMPP ID"),
    ("initiative_codes", "Initiative"),
    ("other_tags",       "Tags"),
    ("notes",            "Notes"),
    ("time_slot",        "Time"),
]

def _has_any_meta(item: dict) -> bool:
    for key, _ in _META_FIELDS:
        val = item.get(key)
        if val and val != [] and val != "":
            return True
    return False

items_with_meta = [i for i in agenda_items if _has_any_meta(i)]

if items_with_meta:
    with st.expander(f"📋 Item Metadata ({len(items_with_meta)} items with metadata)", expanded=False):
        meta_lines: list[str] = []
        for item in items_with_meta:
            iid   = item["item_id"]
            title = item.get("title", "")
            pfx   = item.get("prefix") or ""
            auto  = item.get("auto_sub", False)
            auto_badge = (
                " <span style='font-size:0.72em;color:#aaa'>(auto-sub)</span>"
                if auto else ""
            )
            pfx_badge = (
                f" <span style='font-size:0.78em;color:#888;background:#f0f0f0;"
                f"border-radius:4px;padding:1px 5px;font-family:monospace'>{pfx}</span>"
                if pfx else ""
            )
            meta_lines.append(
                f"<div style='margin-top:14px;font-weight:600;font-size:0.92em'>"
                f"{iid} — {title}{pfx_badge}{auto_badge}</div>"
            )
            for key, label in _META_FIELDS:
                val = item.get(key)
                if not val or val == []:
                    continue
                if isinstance(val, list):
                    display = ", ".join(val)
                else:
                    display = str(val)
                meta_lines.append(
                    f"<div style='margin-left:18px;font-size:0.85em;line-height:1.7'>"
                    f"<span style='color:#888;display:inline-block;width:90px'>{label}</span>"
                    f"<span style='color:#222'>{display}</span></div>"
                )
        st.markdown("\n".join(meta_lines), unsafe_allow_html=True)

# ── Step 7: ZIP contents peek ─────────────────────────────────────────────────
# For every non-CEII ZIP, download it, list its contents, and try to match
# the inner filenames against agenda prefixes.  This tells us whether files
# inside ZIPs carry the aNN.M_ naming convention needed for auto-assignment.

zip_docs = [m for m in docs_meta if m.get("file_type") == "zip" and not m.get("ceii_skipped")]

if zip_docs:
    st.divider()
    st.subheader(f"ZIP Contents ({len(zip_docs)} zip file(s))")
    st.caption("Downloading each ZIP to check whether inner filenames match agenda prefixes.")

    for zip_meta in zip_docs:
        zname = zip_meta["filename"]
        with st.spinner(f"Downloading {zname} …"):
            with download_file_temp(
                url=zip_meta["source_url"],
                filename=zname,
                referer_url=event_url,
                session=session,
            ) as tmp_path:
                if tmp_path is None:
                    st.warning(f"Could not download {zname} (CEII / 403)")
                    continue
                try:
                    with zipfile.ZipFile(tmp_path, "r") as zf:
                        inner_names = [
                            Path(n).name for n in zf.namelist()
                            if not n.endswith("/") and Path(n).name
                        ]
                except Exception as exc:
                    st.error(f"{zname}: could not read ZIP — {exc}")
                    continue

        if not inner_names:
            st.markdown(f"**`{zname}`** — empty or unreadable")
            continue

        # Match inner filenames against agenda prefixes
        inner_rows = [{"filename": n} for n in inner_names]
        inner_mapping = map_docs_to_agenda_items(inner_rows, agenda_items)

        # Build reverse lookup: filename → matched prefix bucket
        fname_to_bucket: dict[str, str] = {}
        for bucket, rows in inner_mapping.items():
            for row in rows:
                fname_to_bucket[row["filename"]] = bucket

        # Build display HTML
        z_lines: list[str] = []
        z_lines.append(
            f'<div style="margin-bottom:4px"><code>{zname}</code>'
            f' <span style="color:#888;font-size:0.85em">({len(inner_names)} file(s) inside)</span></div>'
        )
        for fname in sorted(inner_names):
            bucket = fname_to_bucket.get(fname, "other")
            if bucket == "other":
                match_label = '<span style="color:#c00">✗ unmatched</span>'
            else:
                # Find the item title for this bucket (bucket == prefix)
                matched_item = next(
                    (i for i in agenda_items if i.get("prefix") == bucket), None
                )
                label = matched_item["item_id"] if matched_item else bucket
                match_label = f'<span style="color:#2a2">✓ {label}</span>'

            sub_lbl = _file_sub_letter(fname, bucket) if bucket != "other" else ""
            sub_tag = (
                f'<span style="color:#4a90d9;font-size:0.8em;margin-right:4px">[{sub_lbl}]</span>'
                if sub_lbl else ""
            )
            z_lines.append(
                f'<div style="margin-left:22px;line-height:1.8">'
                f'{sub_tag}<code style="font-size:0.85em">{fname}</code>'
                f' &nbsp; {match_label}</div>'
            )

        st.markdown("\n".join(z_lines), unsafe_allow_html=True)
