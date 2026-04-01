"""
downloader.py — File download helpers.

Files are now downloaded to temporary files for in-pipeline processing only.
Nothing is saved to disk permanently — all data lives in Postgres.
"""
import logging
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _filename_from_url(url: str) -> str:
    return Path(urlparse(url).path).name


def check_url(
    url: str,
    referer_url: str,
    session: requests.Session,
) -> dict:
    """
    Probe a document URL (HEAD request) and return its metadata dict
    without downloading the full file.

    Returns:
        filename, source_url, file_type, ceii_skipped, downloaded_at
    """
    filename = _filename_from_url(url)
    file_type = Path(filename).suffix.lstrip(".").lower() or "unknown"
    downloaded_at = datetime.now(timezone.utc).isoformat()
    headers = {**_HEADERS_BASE, "Referer": referer_url}

    try:
        resp = session.head(url, headers=headers, timeout=15, allow_redirects=True)
    except Exception:
        # Fall back to assuming it's accessible
        return {
            "filename": filename,
            "source_url": url,
            "file_type": file_type,
            "ceii_skipped": False,
            "downloaded_at": downloaded_at,
        }

    if resp.status_code == 403:
        logger.warning("CEII skip (403): %s", url)
        return {
            "filename": filename,
            "source_url": url,
            "file_type": file_type,
            "ceii_skipped": True,
            "downloaded_at": downloaded_at,
        }

    return {
        "filename": filename,
        "source_url": url,
        "file_type": file_type,
        "ceii_skipped": False,
        "downloaded_at": downloaded_at,
    }


@contextmanager
def download_file_temp(
    url: str,
    filename: str,
    referer_url: str,
    session: requests.Session,
):
    """
    Download a file to a NamedTemporaryFile and yield its path.
    The temp file is deleted automatically on context exit.

    Yields None if the file is CEII-protected (403).

    Usage:
        with download_file_temp(url, filename, referer, session) as tmp_path:
            if tmp_path is None:
                continue  # CEII-skipped
            with open(tmp_path, "rb") as f:
                content = f.read()
        # temp file deleted here
    """
    headers = {**_HEADERS_BASE, "Referer": referer_url}
    resp = session.get(url, headers=headers, timeout=60, stream=True)

    if resp.status_code == 403:
        logger.warning("CEII skip (403): %s", url)
        yield None
        return

    resp.raise_for_status()

    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        for chunk in resp.iter_content(chunk_size=65536):
            tmp.write(chunk)
        tmp.flush()
        logger.info("Downloaded to temp: %s", filename)
        yield tmp.name
    # temp file is deleted on NamedTemporaryFile exit


def download_file_to_disk(
    url: str,
    dest_path: Path,
    session: requests.Session | None = None,
) -> bool:
    """
    Stream-download a file and save it permanently to *dest_path*.

    Returns True on success, False if the file was CEII-protected (403).
    Raises on other HTTP errors.
    """
    sess = session or requests.Session()
    headers = {**_HEADERS_BASE}
    resp = sess.get(url, headers=headers, timeout=120, stream=True)

    if resp.status_code == 403:
        logger.warning("Skipped (403): %s", url)
        return False

    resp.raise_for_status()

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)

    logger.info("Downloaded: %s", dest_path.name)
    return True
