"""References Module: Semantic Scholar Citation & Reference Scraper.

Assigned to: Bảo 
Purpose:
    Query Semantic Scholar Graph API to fetch citation references for arXiv papers.
    Parses referenced paper metadata including arXiv ID, Semantic Scholar ID,
    title, authors, submission/publication date, and venue.

Completeness & Contract Requirements for Member3:
    1. Distinguish between:
       - HTTP 200: Successfully retrieved data. Parse and return reference list.
       - HTTP 404: Paper is not indexed yet on Semantic Scholar. This is normal for new papers.
         Return empty list [] and save [] to references.json. This is a VALID state.
       - HTTP 429 / 5xx / Network Timeout: Transient or rate-limit errors.
         MUST trigger retry with exponential backoff. If exhausted, raise RuntimeError.
         DO NOT return empty list on network failure, otherwise valid references are permanently lost!
    2. Support optional `api_key: Optional[str]` in headers (`x-api-key`).
       Semantic Scholar unauthenticated pool has a tight rate limit (100 req/5 min).
       An API key guarantees a steady 1 req/sec.
    3. Old-format arXiv ID (e.g. 'hep-th/9901001') MUST be preserved as-is.
    4. Ghi file nguyên tử (atomic write): ghi vào references.json.tmp rồi replace.
    5. QUY ƯỚC QUAN TRỌNG: Lưu 100% references cào được vào `references.json` cục bộ.
       Chỉ lọc điều kiện `ref_arxiv_id is not None` khi gộp dữ liệu thành bảng Parquet/DataFrame cuối cùng (theo Requirement).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

try:
    from src.utils import retry_with_backoff, s2_rate_limiter
except ImportError:
    from utils import retry_with_backoff, s2_rate_limiter  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

S2_GRAPH_API_URL = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = "references.title,references.authors,references.year,references.publicationDate,references.venue,references.externalIds"


_s2_cooldown_until: float = 0.0


def fetch_s2_paper_data(
    arxiv_id: str,
    timeout: float = 30.0,
    api_key: Optional[str] = None,
    session: Optional[Any] = None,
) -> Optional[dict[str, Any]]:
    """Fetch raw paper reference payload from Semantic Scholar Graph API.

    Endpoint:
        GET https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}?fields={S2_FIELDS}

    Enforces 1 req/sec rate limit via `s2_rate_limiter.wait()` and handles
    HTTP 429 with exponential backoff.

    Args:
        arxiv_id: Base arXiv ID without version suffix (e.g., '2505.10666').
        timeout: Network timeout in seconds.
        api_key: Optional Semantic Scholar API key.
        session: Optional reusable `requests.Session`.

    Returns:
        Optional[dict[str, Any]]: JSON response dictionary, or None if paper
        is unindexed (HTTP 404).

    Raises:
        RuntimeError: If request fails due to server/network errors after all retries.
    """
    global _s2_cooldown_until
    if requests is None:
        raise RuntimeError("The 'requests' library is not installed.")

    now = time.monotonic()
    if now < _s2_cooldown_until:
        wait_s = _s2_cooldown_until - now
        logger.warning("[%s] Waiting for S2 cooldown (%.1fs remaining)...", arxiv_id, wait_s)
        time.sleep(wait_s)

    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    url = f"{S2_GRAPH_API_URL}/arXiv:{arxiv_id}"
    params = {"fields": S2_FIELDS}

    max_retries = 3
    delay = 1.5

    for attempt in range(1, max_retries + 1):
        try:
            s2_rate_limiter.wait()
            req_func = session.get if session else requests.get
            response = req_func(url, params=params, headers=headers, timeout=timeout)

            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                logger.debug("[%s] Paper is not indexed yet on Semantic Scholar (HTTP 404).", arxiv_id)
                return None
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                cooldown = float(retry_after) if retry_after and retry_after.isdigit() else 30.0
                _s2_cooldown_until = time.monotonic() + cooldown
                if attempt < max_retries:
                    logger.warning("[%s] S2 429 Rate Limit. Sleeping %.1fs before retry %d/%d.", arxiv_id, cooldown, attempt + 1, max_retries)
                    time.sleep(cooldown)
                    continue
                raise RuntimeError(f"Semantic Scholar 429 Rate Limited after {max_retries} attempts.")
            if response.status_code in (500, 502, 503, 504):
                if attempt < max_retries:
                    logger.warning(
                        "[%s] S2 request failed with HTTP %d (attempt %d/%d). Retrying in %.1fs...",
                        arxiv_id,
                        response.status_code,
                        attempt,
                        max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2.0
                continue

            response.raise_for_status()

        except Exception as exc:
            if attempt == max_retries:
                logger.warning("[%s] S2 request failed after %d retries (%s). Defaulting to empty references list.", arxiv_id, max_retries, exc)
                return None
            logger.warning(
                "[%s] Transient network error (attempt %d/%d): %s. Retrying in %.1fs...",
                arxiv_id,
                attempt,
                max_retries,
                exc,
                delay,
            )
            time.sleep(delay)
            delay *= 2.0

    raise RuntimeError(f"Semantic Scholar request failed for {arxiv_id} after {max_retries} attempts.")


def parse_references(raw_data: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transform raw Semantic Scholar response into standardized reference records.

    Each reference item in the result list must conform to:
        - `ref_arxiv_id`: arXiv ID from externalIds.ArXiv (str or None, preserve old format e.g. 'hep-th/9901001')
        - `ref_s2_id`: Semantic Scholar paperId (str or None)
        - `ref_title`: Reference title (str or None)
        - `ref_authors`: List of author names (list[str])
        - `ref_submission_date`: Publication date or year string (str or None)
        - `ref_venue`: Venue/conference name (str or None)

    Args:
        raw_data: Raw JSON dictionary returned from Semantic Scholar API.

    Returns:
        list[dict[str, Any]]: Parsed list of reference dicts (empty list if no references or unindexed).
    """
    if not raw_data or not isinstance(raw_data, dict):
        return []

    raw_refs = raw_data.get("references")
    if not raw_refs or not isinstance(raw_refs, list):
        return []

    parsed: list[dict[str, Any]] = []
    for item in raw_refs:
        if not item or not isinstance(item, dict):
            continue

        ext_ids = item.get("externalIds") or {}
        ref_arxiv_id = None
        if isinstance(ext_ids, dict):
            for k, v in ext_ids.items():
                if k.lower() == "arxiv":
                    ref_arxiv_id = v
                    break

        authors_raw = item.get("authors") or []
        ref_authors = [
            a.get("name")
            for a in authors_raw
            if isinstance(a, dict) and a.get("name")
        ]

        ref_sub_date = item.get("publicationDate")
        if not ref_sub_date and item.get("year"):
            ref_sub_date = str(item.get("year"))

        parsed.append({
            "ref_arxiv_id": ref_arxiv_id,
            "ref_s2_id": item.get("paperId"),
            "ref_title": item.get("title"),
            "ref_authors": ref_authors,
            "ref_submission_date": ref_sub_date,
            "ref_venue": item.get("venue"),
        })

    return parsed


def save_references(references: list[dict[str, Any]], output_file: Path | str) -> None:
    """Save reference list to a JSON file atomically.

    Args:
        references: List of reference dicts to serialize.
        output_file: Target file path (e.g., path/to/references.json).
    """
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(f"{out_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(references, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, out_path)


def get_references(
    arxiv_id: str,
    output_dir: Optional[Path | str] = None,
    api_key: Optional[str] = None,
    session: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Retrieve and optionally save references for a paper.

    Coordinates fetching and parsing. If `output_dir` is provided, saves
    the resulting list (even if empty) to `{output_dir}/{arxiv_id}/references.json`.

    Args:
        arxiv_id: Base arXiv ID (e.g., '2505.10666').
        output_dir: Optional path to project data directory.
        api_key: Optional Semantic Scholar API key.
        session: Optional reusable `requests.Session`.

    Returns:
        list[dict[str, Any]]: List of parsed references.
    """
    clean_id = arxiv_id.strip()
    if "v" in clean_id:
        clean_id = clean_id.split("v")[0]

    raw_data = fetch_s2_paper_data(clean_id, api_key=api_key, session=session)
    refs = parse_references(raw_data)

    if output_dir:
        dest_file = Path(output_dir) / clean_id / "references.json"
        save_references(refs, dest_file)

    return refs
