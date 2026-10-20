"""References Module: Semantic Scholar Citation & Reference Scraper.

Assigned to: Bảo (Member3)
Purpose:
    Query Semantic Scholar Graph API to fetch citation references for arXiv papers.
    Parses referenced paper metadata including arXiv ID, Semantic Scholar ID,
    title, authors, submission/publication date, and venue.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

try:
    from src.utils import retry_with_backoff, s2_rate_limiter
except ImportError:
    from utils import retry_with_backoff, s2_rate_limiter  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

S2_GRAPH_API_URL = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = "references.title,references.authors,references.year,references.publicationDate,references.venue,references.externalIds"


def fetch_s2_paper_data(
    arxiv_id: str,
    timeout: float = 30.0,
) -> Optional[dict[str, Any]]:
    """Fetch raw paper reference payload from Semantic Scholar Graph API.

    Endpoint:
        GET https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}?fields={S2_FIELDS}

    Enforces 1 req/sec rate limit via `s2_rate_limiter.wait()` and handles
    HTTP 429 with exponential backoff.

    Args:
        arxiv_id: Base arXiv ID without version suffix (e.g., '2505.10666').
        timeout: Network timeout in seconds.

    Returns:
        Optional[dict[str, Any]]: JSON response dictionary, or None if paper
        is unindexed (HTTP 404) or API error occurs.
    """
    # TODO (Bảo):
    # 1. Call s2_rate_limiter.wait().
    # 2. Query requests.get(f"{S2_GRAPH_API_URL}/arXiv:{arxiv_id}", params={"fields": S2_FIELDS}).
    # 3. If 404: log info that paper is not indexed on S2, return None.
    # 4. If 200: return resp.json().
    # 5. Handle 429/5xx with retry_with_backoff.
    raise NotImplementedError("fetch_s2_paper_data() is not yet implemented.")


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
        list[dict[str, Any]]: Parsed list of reference dicts (empty list if no references).
    """
    # TODO (Bảo):
    # 1. If not raw_data or "references" not in raw_data: return [].
    # 2. Iterate over raw_data.get("references", []).
    # 3. Extract ref_arxiv_id (from item.get("externalIds", {}).get("ArXiv")),
    #    ref_s2_id (from item.get("paperId")),
    #    ref_title, ref_authors, ref_submission_date, ref_venue.
    # 4. Return list of cleaned dictionaries.
    raise NotImplementedError("parse_references() is not yet implemented.")


def get_references(
    arxiv_id: str,
    output_dir: Optional[Path | str] = None,
) -> list[dict[str, Any]]:
    """Retrieve and optionally save references for a paper.

    Coordinates fetching and parsing. If `output_dir` is provided, saves
    the resulting list (even if empty) to `{output_dir}/{arxiv_id}/references.json`.

    Args:
        arxiv_id: Base arXiv ID (e.g., '2505.10666').
        output_dir: Optional path to project data directory.

    Returns:
        list[dict[str, Any]]: List of parsed references.
    """
    # TODO (Bảo):
    # 1. raw_data = fetch_s2_paper_data(arxiv_id).
    # 2. refs = parse_references(raw_data).
    # 3. If output_dir: save_references(refs, Path(output_dir) / arxiv_id / "references.json").
    # 4. Return refs.
    raise NotImplementedError("get_references() is not yet implemented.")


def save_references(references: list[dict[str, Any]], output_file: Path | str) -> None:
    """Save reference list to a JSON file.

    Args:
        references: List of reference dicts to serialize.
        output_file: Target file path (e.g., path/to/references.json).
    """
    # TODO (Bảo): Create parent dir, write formatted JSON (indent=2, ensure_ascii=False).
    raise NotImplementedError("save_references() is not yet implemented.")
