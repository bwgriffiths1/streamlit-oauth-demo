"""
nyiso_agenda_parser.py — Parse NYISO committee agenda PDFs and map documents.

NYISO agendas are single-page PDFs with a columnar layout:
    Title text (left)          Presenter Name    Time Slot
    1. Introductions...        Alex Novicki      10:00 – 10:05

Uses pdfplumber's layout=True mode to preserve spatial column separation.
"""
import logging
import re
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

# Matches numbered agenda items at start of line
_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")

# Time slot at end of line: "10:15 – 10:20"
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[–—-]\s*\d{1,2}:\d{2})\s*$")

# Presenter name: 2-3 capitalized words, preceded by 2+ spaces (column gap)
# e.g. "...Report    Alex Novicki   10:00..."
_PRESENTER_RE = re.compile(
    r"\s{2,}([A-Z][a-z]+(?:\s+[A-Z][a-zA-Z'.]+){1,3})\s*$"
)

# Discussion/Vote/Action markers (standalone lines or inline)
_ACTION_RE = re.compile(
    r"^\s*Discussion\s*(?:&|/|and)?\s*(?:Vote|Action)\s*$", re.IGNORECASE
)
_ACTION_INLINE_RE = re.compile(
    r"\s*Discussion\s*(?:&|/|and)?\s*(?:Vote|Action)\s*", re.IGNORECASE
)

# Lines to skip
_SKIP_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^\s*•"),                      # bullet points
    re.compile(r"^\s*Act on:", re.IGNORECASE),
    re.compile(r"^\s*Next meeting:", re.IGNORECASE),
    re.compile(r"^\s*Working Group Updates", re.IGNORECASE),
    re.compile(r"^\s*Subcommittee", re.IGNORECASE),
]


def _is_skip_line(line: str) -> bool:
    return any(p.match(line) for p in _SKIP_PATTERNS)


def _is_continuation(line: str) -> bool:
    """Check if a line is a continuation of the previous item's title."""
    stripped = line.strip()
    if not stripped:
        return False
    # Continuation lines are indented but don't start a new item
    if _ITEM_RE.match(line):
        return False
    if _is_skip_line(line):
        return False
    # Must not be a standalone presenter line (just a name with lots of leading space)
    if re.match(r"^\s{20,}[A-Z][a-z]+\s+[A-Z]", line):
        return False
    return True


def parse_agenda_pdf(pdf_path: str) -> list[dict]:
    """
    Extract agenda items from a NYISO agenda PDF.

    Returns list of agenda item dicts:
        {
            "item_id": str,       # "1", "2", "3", etc.
            "title": str,         # cleaned title
            "presenter": str|None,
            "time_slot": str|None,
        }
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join(
                page.extract_text(layout=True) or "" for page in pdf.pages
            )
    except Exception as exc:
        logger.error("Failed to read agenda PDF %s: %s", pdf_path, exc)
        return []

    if not full_text.strip():
        logger.warning("Empty text extracted from %s", pdf_path)
        return []

    lines = full_text.split("\n")
    items = []
    i = 0

    while i < len(lines):
        line = lines[i]
        m = _ITEM_RE.match(line)
        if not m:
            i += 1
            continue

        item_id = m.group(1)
        rest_of_first_line = m.group(2)

        # Parse the first line: extract time slot, then presenter, leaving title
        presenter, time_slot, title_part = _parse_line_columns(rest_of_first_line)

        # Collect continuation lines for multi-line titles
        j = i + 1
        continuation_parts = []
        while j < len(lines):
            next_line = lines[j]
            stripped = next_line.strip()

            # Skip Discussion/Vote lines but don't stop
            if _ACTION_RE.match(next_line):
                j += 1
                continue

            if _is_continuation(next_line):
                # This is a continuation of the title (e.g. multi-line item 5)
                cont_text = stripped
                # Remove any inline Discussion/Vote markers
                cont_text = _ACTION_INLINE_RE.sub("", cont_text).strip()
                if cont_text:
                    continuation_parts.append(cont_text)
                j += 1
            else:
                break

        # Build full title
        full_title = title_part
        if continuation_parts:
            full_title = full_title + " " + " ".join(continuation_parts)
        full_title = full_title.strip().rstrip(" –—-,:")

        if full_title:
            items.append({
                "item_id": item_id,
                "title": full_title,
                "presenter": presenter,
                "time_slot": time_slot,
            })

        i = j

    logger.info("Parsed %d agenda item(s) from %s", len(items), Path(pdf_path).name)
    return items


def _parse_line_columns(text: str) -> tuple[str | None, str | None, str]:
    """
    Parse a line with potential columnar layout into (presenter, time_slot, title).

    Input:  "Market Operations Report                    Shaun Johnson  10:15 – 10:20"
    Output: ("Shaun Johnson", "10:15 – 10:20", "Market Operations Report")
    """
    presenter = None
    time_slot = None
    rest = text

    # 1. Extract time slot from end
    tm = _TIME_RE.search(rest)
    if tm:
        time_slot = tm.group(1).strip()
        rest = rest[:tm.start()].rstrip()

    # 2. Extract presenter: look for a name preceded by 2+ spaces (column gap)
    pm = _PRESENTER_RE.search(rest)
    if pm:
        presenter = pm.group(1).strip()
        rest = rest[:pm.start()].rstrip()

    # 3. If no column-gap presenter found, strip Discussion/Vote markers first
    #    then retry — these markers often sit between title and presenter.
    if not presenter:
        cleaned = _ACTION_INLINE_RE.sub(" ", rest).strip()
        # Try column-gap match on cleaned text
        pm2 = _PRESENTER_RE.search(cleaned)
        if pm2:
            presenter = pm2.group(1).strip()
            rest = cleaned[:pm2.start()].rstrip()
        else:
            # Try glued-name: lowercase char directly adjacent to uppercase name
            glued = re.search(
                r"([a-z])([A-Z][a-z]+\s+[A-Z][a-zA-Z'.]+)\s*$",
                cleaned,
            )
            if glued:
                presenter = glued.group(2).strip()
                rest = cleaned[:glued.end(1)].rstrip()
            else:
                # Try name with single space before it (after marker removal)
                spaced = re.search(
                    r"\s+([A-Z][a-z]+\s+[A-Z][a-zA-Z'.]+)\s*$",
                    cleaned,
                )
                if spaced:
                    candidate = spaced.group(1)
                    words = candidate.split()
                    # Only accept if it looks like a person name (2-3 short words)
                    if 2 <= len(words) <= 3 and all(len(w) <= 15 for w in words):
                        presenter = candidate
                        rest = cleaned[:spaced.start()].rstrip()
                    else:
                        rest = cleaned
                else:
                    rest = cleaned

    # 4. Clean remaining text as the title
    title = _ACTION_INLINE_RE.sub("", rest).strip()
    title = title.rstrip(" –—-,:")

    return presenter, time_slot, title


def map_files_to_agenda_items(
    files: list[dict],
    agenda_items: list[dict],
) -> dict[str, list[dict]]:
    """
    Map downloaded files to agenda items using numeric prefix matching.

    NYISO files have display names like '4a Motion' where '4a' maps to
    agenda item '4'. Sub-items (4a, 4b) are grouped under the parent item
    if no exact match exists.

    Returns dict mapping item_id → list of file dicts.
    Files with no matching item go under the 'unmatched' key.
    """
    item_ids = {item["item_id"] for item in agenda_items}
    mapping: dict[str, list[dict]] = {item["item_id"]: [] for item in agenda_items}
    mapping["unmatched"] = []

    for f in files:
        prefix = f.get("agenda_prefix")
        if not prefix:
            mapping["unmatched"].append(f)
            continue

        # Exact match (e.g. prefix '5' matches item_id '5')
        if prefix in item_ids:
            mapping[prefix].append(f)
            continue

        # Sub-item match: prefix '5a' → parent item '5'
        parent = re.match(r"^(\d+)", prefix)
        if parent and parent.group(1) in item_ids:
            mapping[parent.group(1)].append(f)
            continue

        mapping["unmatched"].append(f)

    return mapping
