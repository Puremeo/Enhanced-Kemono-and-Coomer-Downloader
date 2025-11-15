"""
Helper functions for handling failed downloads tracking.
"""
import os
from typing import Set
import logging
import time
from pathlib import Path

from .download_utils import download_with_resume
from .session import headers, cookie_map

logger = logging.getLogger(__name__)

FAILED_DOWNLOAD_LOG_FILENAME = "failed_downloads.txt"


def load_failed_downloads(file_path: str = FAILED_DOWNLOAD_LOG_FILENAME) -> Set[str]:
    """Load failed download links from file."""
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_failed_downloads(
    failed_links: Set[str], file_path: str = FAILED_DOWNLOAD_LOG_FILENAME
) -> None:
    """Save failed download links to file."""
    with open(file_path, "w", encoding="utf-8") as f:
        for link in sorted(failed_links):
            f.write(f"{link}\n")


def add_failed_download(
    link: str, file_path: str = FAILED_DOWNLOAD_LOG_FILENAME
) -> None:
    """Add a failed download link to the file."""
    failed_links = load_failed_downloads(file_path)
    failed_links.add(link)
    save_failed_downloads(failed_links, file_path)


def remove_failed_download(
    link: str, file_path: str = FAILED_DOWNLOAD_LOG_FILENAME
) -> None:
    """Remove a successful download link from the failed downloads file."""
    failed_links = load_failed_downloads(file_path)
    failed_links.discard(link)
    save_failed_downloads(failed_links, file_path)


def retry_failed_downloads(
    download_dir: str = "temp_downloads",
    max_retries: int = None,
    backoff: float = None,
) -> None:
    """
    Retry downloads recorded in the failed downloads file.

    This function will attempt to download each failed URL into `download_dir`.
    On success, the URL will be removed from the failed list.
    """
    failed = load_failed_downloads()
    if not failed:
        logger.info("No failed downloads to retry.")
        return

    Path(download_dir).mkdir(parents=True, exist_ok=True)

    # Use config defaults if None
    from .config import load_config

    cfg = load_config()
    retries = max_retries if max_retries is not None else cfg.download_retries
    backoff_factor = backoff if backoff is not None else cfg.download_backoff

    still_failed = set()

    for url in sorted(failed):
        try:
            # derive a safe filename from URL
            filename = Path(url).name
            save_path = Path(download_dir) / filename
            domain_key = "kemono" if "kemono" in url else "coomer"
            success, err = download_with_resume(
                url,
                str(save_path),
                headers=headers,
                cookies=cookie_map.get(domain_key),
                max_retries=retries,
                backoff_factor=backoff_factor,
            )
            if success:
                logger.info("Retried and downloaded: %s", url)
                remove_failed_download(url)
            else:
                logger.warning("Retry failed for %s: %s", url, err)
                still_failed.add(url)
        except Exception as e:
            logger.error("Unexpected error retrying %s: %s", url, e)
            still_failed.add(url)

    # Save remaining failures
    if still_failed:
        save_failed_downloads(still_failed)
    else:
        # clear file
        save_failed_downloads(set())


def cleanup_old_part_files(directory: str = ".", older_than_days: int = 7) -> dict:
    """
    Delete .part temporary files older than `older_than_days` in `directory` (recursively).

    Returns a dict with counts: {"scanned": n, "deleted": m, "skipped": k}
    """
    now = os.path.getmtime
    scanned = 0
    deleted = 0
    skipped = 0

    base = Path(directory)
    if not base.exists():
        logger.warning("Directory for cleanup does not exist: %s", directory)
        return {"scanned": 0, "deleted": 0, "skipped": 0}

    cutoff_seconds = older_than_days * 24 * 60 * 60
    for p in base.rglob("*.part"):
        try:
            scanned += 1
            mtime = now(p)
            age = (time.time() - mtime)
            if age >= cutoff_seconds:
                p.unlink()
                deleted += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error("Error while handling .part file %s: %s", p, e)
            skipped += 1

    logger.info(
        "Cleanup finished for %s: scanned=%s deleted=%s skipped=%s",
        directory,
        scanned,
        deleted,
        skipped,
    )
    return {"scanned": scanned, "deleted": deleted, "skipped": skipped}