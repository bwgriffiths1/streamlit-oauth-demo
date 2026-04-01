"""
nyiso_scraper.py — NYISO committee meeting discovery and file listing.

Uses the Liferay committeefile REST API (no auth required).
Two endpoints:
  POST /o/committeefile/meetings  → list meetings for a committee+year
  POST /o/committeefile/files     → list files for a single meeting
"""
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import unquote, urlparse

import requests

logger = logging.getLogger(__name__)

MEETINGS_URL = "https://www.nyiso.com/o/committeefile/meetings"
FILES_URL = "https://www.nyiso.com/o/committeefile/files"

# The portletId prefix is constant across all committees; only the 4-char
# INSTANCE suffix varies.
_PORTLET_PREFIX = (
    "portlet_com_liferay_client_extension_web_internal_portlet_"
    "ClientExtensionEntryPortlet_20115_LXC_nyiso_committee_file_browser_INSTANCE_"
)


def _build_portlet_id(instance_suffix: str) -> str:
    return f"{_PORTLET_PREFIX}{instance_suffix}"


def _api_body(committee: dict, folder_id: str) -> dict:
    """Build the JSON body for the committeefile API."""
    return {
        "plid": str(committee["plid"]),
        "portletId": _build_portlet_id(committee["portlet_instance"]),
        "folderId": str(folder_id),
    }


# ---------------------------------------------------------------------------
# Meeting discovery
# ---------------------------------------------------------------------------

def fetch_meetings(
    committee: dict,
    year: int,
    lookahead_days: int = 90,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """
    Fetch the meeting list for a committee and year.

    Returns meetings within the lookahead window (today → today + lookahead_days),
    sorted by date descending (newest first).

    Each returned dict:
        {
            "meeting_id": str,
            "date": date,
            "committee_name": str,
            "committee_short": str,
        }
    """
    year_folders = committee.get("year_folders", {})
    folder_id = year_folders.get(year) or year_folders.get(str(year))
    if not folder_id:
        logger.error(
            "No year folder ID for %s / %d — run --discover-folders or add to config",
            committee["short"], year,
        )
        return []

    sess = session or requests.Session()
    body = _api_body(committee, folder_id)

    try:
        resp = sess.post(MEETINGS_URL, json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch meetings for %s/%d: %s", committee["short"], year, exc)
        return []

    if not data.get("status"):
        logger.warning("API returned status=false for %s/%d", committee["short"], year)
        return []

    today = date.today()
    cutoff = today + timedelta(days=lookahead_days)

    meetings = []
    for m in data.get("meetings", []):
        try:
            meeting_date = date.fromisoformat(m["date"])
        except (ValueError, KeyError):
            continue

        if meeting_date < (today - timedelta(days=lookahead_days)) or meeting_date > cutoff:
            continue

        meetings.append({
            "meeting_id": str(m["id"]),
            "date": meeting_date,
            "committee_name": committee["name"],
            "committee_short": committee["short"],
        })

    meetings.sort(key=lambda x: x["date"], reverse=True)
    logger.info(
        "Found %d meeting(s) for %s in %d within window",
        len(meetings), committee["short"], year,
    )
    return meetings


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------

def extract_agenda_prefix(display_name: str) -> str | None:
    """
    Parse the numeric prefix from a NYISO file display name.

    '1 Agenda' → '1'
    '4a Motion' → '4a'
    '06a Deliverability...' → '6a'
    'Final Motions' → None
    'BRM Report' → None
    """
    m = re.match(r"^0*(\d+[a-zA-Z]?)\s+", display_name)
    return m.group(1) if m else None


def fetch_meeting_files(
    committee: dict,
    meeting_folder_id: str,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """
    Fetch the file list for a single meeting.

    Each returned dict:
        {
            "name": str,            # display name from API, e.g. '1 Agenda'
            "filename": str,        # decoded filename from URL path
            "url": str,             # full download URL
            "file_id": str,         # NYISO file ID
            "file_type": str,       # extension (pdf, xlsx, zip, ...)
            "date_posted": str,     # e.g. '2026/03/11'
            "agenda_prefix": str|None,  # parsed prefix, e.g. '4a'
        }
    """
    sess = session or requests.Session()
    body = _api_body(committee, meeting_folder_id)

    try:
        resp = sess.post(FILES_URL, json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch files for meeting %s: %s", meeting_folder_id, exc)
        return []

    files = []
    for f in data.get("files", []):
        url = f.get("fileUrl", "")
        if not url:
            continue

        # Decode the filename from the URL path
        path = urlparse(url).path
        # URL pattern: /documents/20142/{folderId}/{filename}/{uuid}
        parts = path.split("/")
        # filename is the second-to-last segment (before the UUID)
        raw_filename = unquote(parts[-2]) if len(parts) >= 2 else unquote(parts[-1])
        display_name = f.get("name", raw_filename)

        files.append({
            "name": display_name,
            "filename": raw_filename,
            "url": url,
            "file_id": str(f.get("id", "")),
            "file_type": f.get("fileType", "").lower(),
            "date_posted": f.get("date", ""),
            "agenda_prefix": extract_agenda_prefix(display_name),
        })

    logger.info("Found %d file(s) for meeting %s", len(files), meeting_folder_id)
    return files


# ---------------------------------------------------------------------------
# Folder naming
# ---------------------------------------------------------------------------

def folder_name_for_meeting(meeting: dict) -> str:
    """
    Build the folder name for a meeting.
    NYISO meetings are single-day, e.g. 'BIC March 18 2026'.
    """
    d = meeting["date"]
    short = meeting["committee_short"]
    return f"{short} {d.strftime('%B')} {d.day} {d.year}"


# ---------------------------------------------------------------------------
# Year-folder discovery (Playwright)
# ---------------------------------------------------------------------------

async def discover_year_folders(page_url: str, page) -> dict[int, str]:
    """
    Navigate to a NYISO committee page, wait for the React widget to render,
    and extract year → folderId mappings from the dropdown.

    Args:
        page_url: committee page URL (e.g. https://www.nyiso.com/business-issues-committee-bic)
        page: Playwright Page object (caller manages browser lifecycle)

    Returns: {2026: '56302830', 2025: '49138793', ...}
    """
    logger.info("Discovering year folders from %s", page_url)
    await page.goto(page_url, wait_until="networkidle", timeout=30000)

    # Wait for the file browser component to render
    await page.wait_for_selector(
        ".file-browser-dropdown .fakeinput",
        timeout=15000,
    )

    # Click the dropdown to expand it
    await page.click(".file-browser-dropdown .fakeinput")
    await page.wait_for_selector(
        ".file-browser-dropdown li[data-name]",
        timeout=5000,
    )

    # "Show more" may be present — click it to load all years
    show_more = await page.query_selector('.file-browser-dropdown li[value="addYears"]')
    while show_more:
        await show_more.click()
        time.sleep(0.5)
        show_more = await page.query_selector('.file-browser-dropdown li[value="addYears"]')

    # Extract year → folderId from <li value="folderId" data-name="year">
    items = await page.eval_on_selector_all(
        ".file-browser-dropdown li[data-name]",
        """els => els.map(el => ({
            year: parseInt(el.getAttribute('data-name')),
            folderId: el.getAttribute('value')
        }))""",
    )

    result = {item["year"]: item["folderId"] for item in items if item["year"] and item["folderId"]}
    logger.info("Discovered %d year folder(s): %s", len(result), result)
    return result


# ---------------------------------------------------------------------------
# Portlet ID scraping (fallback)
# ---------------------------------------------------------------------------

def scrape_portlet_ids(page_url: str, session: Optional[requests.Session] = None) -> dict:
    """
    Fetch the committee page HTML and extract plid and portlet_instance.

    Returns: {"plid": "40263", "portlet_instance": "khij"}
    """
    sess = session or requests.Session()
    resp = sess.get(page_url, timeout=20)
    resp.raise_for_status()
    html = resp.text

    plid_match = re.search(r"plid=(\d+)", html)
    instance_match = re.search(
        r"nyiso_committee_file_browser_INSTANCE_([a-z]+)", html
    )

    result = {}
    if plid_match:
        result["plid"] = plid_match.group(1)
    if instance_match:
        result["portlet_instance"] = instance_match.group(1)

    return result
