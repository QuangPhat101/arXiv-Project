"""Downloader Module: arXiv LaTeX Source Archive Downloader.

Assigned to: Khôi (Member1)
Purpose:
    Fetch raw source archives for specific arXiv paper versions from
    `https://export.arxiv.org/src/{versioned_id}`. Enforces the required 3-second
    rate limit, custom User-Agent, and exponential backoff retry.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    from src.utils import arxiv_rate_limiter, retry_with_backoff
except ImportError:
    from utils import arxiv_rate_limiter, retry_with_backoff  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

ARXIV_SRC_BASE_URL = "https://export.arxiv.org/src"
DEFAULT_USER_AGENT = "ArxivCrawler/1.0 (HCMUS Data Science Project; mailto:contact@hcmus.edu.vn)"


def get_source_url(versioned_id: str) -> str:
    """Construct the direct source download URL for an arXiv paper version.

    Note: Always use `export.arxiv.org`, NEVER use `arxiv.org` directly
    to avoid automated scraping blocks (HTTP 403).

    Args:
        versioned_id: Versioned arXiv identifier (e.g., '2505.10666v1').

    Returns:
        str: Direct download URL string.
    """
    return f"{ARXIV_SRC_BASE_URL}/{versioned_id}"


def download_source(
    versioned_id: str,
    dest_path: Path | str,
    timeout: float = 30.0,
) -> Optional[Path]:
    """Download the source archive for a given versioned arXiv ID.

    Steps:
        1. Enforce rate limit (3s delay) using `arxiv_rate_limiter.wait()`.
        2. Set custom `User-Agent` header.
        3. Make GET request to `https://export.arxiv.org/src/{versioned_id}`.
        4. If HTTP 200, stream content to `dest_path`.
        5. Handle HTTP 404 (source not available), HTTP 403 / 429 / timeouts
           with retry logic or graceful skip.

    Args:
        versioned_id: Versioned arXiv identifier (e.g., '2505.10666v1').
        dest_path: Destination file path where archive will be saved.
        timeout: Network request timeout in seconds.

    Returns:
        Optional[Path]: Path to the downloaded archive if successful,
        or None if download failed or source does not exist.
    """
    # TODO (Khôi):
    # 1. Ensure dest_path parent directory exists.
    # 2. Call arxiv_rate_limiter.wait().
    # 3. Use requests.get(url, headers={'User-Agent': ...}, stream=True, timeout=timeout).
    # 4. Check response status:
    #    - 200: stream write to dest_path, return Path(dest_path).
    #    - 404: log warning that paper version has no source, return None.
    #    - 403/429/5xx: trigger retry_with_backoff or handle accordingly.
    # 5. Return None on persistent failure.
    raise NotImplementedError("download_source() is not yet implemented.")
