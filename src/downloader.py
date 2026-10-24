"""Downloader Module: arXiv LaTeX Source Archive Downloader.

Assigned to: Khôi
Purpose:
    Fetch raw source archives for specific arXiv paper versions from
    `https://export.arxiv.org/src/{versioned_id}`. Enforces the required 3-second
    rate limit, custom User-Agent, and exponential backoff retry.

Completeness & Contract Requirements for Member1:
    1. Distinguish between:
       - HTTP 200: Successfully downloaded source archive. Return Path to destination.
       - HTTP 404: Source is genuinely NOT available on arXiv (e.g. author only provided PDF).
         Return None so the pipeline passes archive_path=None to extractor.py without treating it as an error.
       - HTTP 403 / 429 / 5xx / Network Timeout: Transient or rate-limit errors.
         MUST trigger retry with exponential backoff. If all retries fail, raise RuntimeError/RequestException.
         DO NOT quietly return None on transient errors, otherwise incomplete papers will be falsely marked complete!
    2. Support reusable `requests.Session` parameter to reuse TCP connection pool.
    3. Stream response chunks directly to file (`stream=True`) to minimize memory footprint.
    4. Enforce arXiv 3.0s rate limit via `arxiv_rate_limiter.wait()`.
       CRITICAL: Always reuse the singleton `arxiv_rate_limiter` imported from `utils.py`.
       NEVER instantiate a new RateLimiter inside download_source(), otherwise timestamps will reset
       across multiple versions (v1, v2, ...) leading to HTTP 403 blocks!
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

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
    session: Optional[Any] = None,
) -> Optional[Path]:
    """Download the source archive for a given versioned arXiv ID.

    Steps:
        1. Ensure dest_path parent directory exists.
        2. Enforce arXiv rate limit (3s minimum gap) using `arxiv_rate_limiter.wait()`.
        3. Make GET request to `https://export.arxiv.org/src/{versioned_id}` using session or requests.
        4. Check status code:
           - 200: Stream content to dest_path (chunk size 64KB), return Path(dest_path).
           - 404: Source package does not exist on arXiv (PDF-only submission). Return None.
           - 403 / 429 / 5xx: Must retry with backoff. If exhausted, raise RuntimeError.

    Args:
        versioned_id: Versioned arXiv identifier (e.g., '2505.10666v1').
        dest_path: Destination file path where archive will be saved.
        timeout: Network request timeout in seconds.
        session: Optional reusable `requests.Session`.

    Returns:
        Optional[Path]: Path to downloaded archive if 200, None if 404 (not available).

    Raises:
        RuntimeError: If download fails due to network or server errors after all retries.
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    url = get_source_url(versioned_id)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    req_func = session.get if session is not None else requests.get

    @retry_with_backoff(
        max_retries=5,
        initial_delay=3.0,
        backoff_factor=2.0,
        retryable_statuses=(403, 429, 500, 502, 503, 504),
        logger=logger,
    )
    def _fetch_stream() -> Any:
        arxiv_rate_limiter.wait()
        resp = req_func(url, headers=headers, stream=True, timeout=timeout)
        if resp.status_code == 404:
            return resp
        resp.raise_for_status()
        return resp

    try:
        response = _fetch_stream()
    except Exception as exc:
        logger.error("[%s] Failed to download source archive after all retries: %s", versioned_id, exc)
        raise RuntimeError(f"Download failed for {versioned_id}: {exc}") from exc

    if response.status_code == 404:
        logger.info("[%s] No LaTeX source archive available on arXiv (HTTP 404, PDF-only).", versioned_id)
        return None

    try:
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    except OSError as err:
        logger.error("[%s] Failed to write downloaded archive to %s: %s", versioned_id, dest, err)
        raise RuntimeError(f"File write failed for {versioned_id}: {err}") from err
    finally:
        response.close()

    return dest
