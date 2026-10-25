"""Discovery Module: Paper Metadata Extraction and Version Detection.

Assigned to: Bảo 
Purpose:
    Query arXiv API using the official `arxiv` Python library to extract paper
    metadata (title, authors, submission date, revised dates, venue/journal_ref)
    and detect all available version numbers from the latest versioned entry ID.

Performance & Completeness Requirements for Member3:
    1. Implement batch discovery (`discover_papers_batch`):
       arXiv API supports querying a list of IDs in `id_list=[...]`.
       Instead of querying 1 paper per 3 seconds (5000 papers = 4.2 hours),
       batch query in chunks of 50-100 IDs. This reduces discovery time to ~2-3 minutes.
    2. Maintain `discover_paper` as a wrapper for backward compatibility and single paper queries.
    3. Trích xuất đúng cấu trúc metadata theo bảng 'papers' trong Requirement:
       - `arxiv_id`: base ID (str, non-null)
       - `title`: paper title (str)
       - `authors`: list of author names (list[str])
       - `submission_date`: ISO string of initial submission (from paper.published.isoformat())
       - `revised_dates`: list of ISO strings of revisions (from paper.updated.isoformat())
       - `venue`: journal_ref if available, else None
       - `versions`: list of all version IDs (e.g. ["2505.10666v1", "2505.10666v2"])
    4. Xử lý bài không tồn tại: trả về None nếu paper không tìm thấy trên arXiv API.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional, Sequence

try:
    import arxiv
except ImportError:
    arxiv = None  # type: ignore[assignment]

try:
    from src.utils import arxiv_rate_limiter
except ImportError:
    try:
        from utils import arxiv_rate_limiter
    except ImportError:
        arxiv_rate_limiter = None

logger = logging.getLogger(__name__)


def parse_version_count(entry_id: str) -> int:
    """Extract the total number of versions from an arXiv entry ID.

    For example, given 'http://arxiv.org/abs/2505.10666v3' or '2505.10666v3',
    this function parses the trailing version suffix 'v3' and returns 3.
    If no version suffix is present, defaults to 1.

    Args:
        entry_id: arXiv entry URL or versioned ID string.

    Returns:
        int: The highest version number (total versions available, minimum 1).
    """
    if not entry_id:
        return 1
    match = re.search(r"v(\d+)$", str(entry_id).strip())
    if match:
        try:
            return max(1, int(match.group(1)))
        except ValueError:
            return 1
    return 1


def generate_version_list(base_id: str, version_count: int) -> list[str]:
    """Generate a list of versioned arXiv IDs from 1 to `version_count`.

    For example:
        generate_version_list("2505.10666", 3)
        -> ["2505.10666v1", "2505.10666v2", "2505.10666v3"]

    Args:
        base_id: Canonical base arXiv ID (without version suffix).
        version_count: Total number of versions.

    Returns:
        list[str]: Ordered list of versioned ID strings.
    """
    clean_base = re.sub(r"v\d+$", "", str(base_id).strip())
    return [f"{clean_base}v{i}" for i in range(1, max(1, version_count) + 1)]


def save_metadata(metadata: dict[str, Any], output_file: Path | str) -> None:
    """Save metadata dictionary to a JSON file atomically.

    Args:
        metadata: Metadata dictionary to serialize.
        output_file: Destination file path (e.g., path/to/metadata.json).
    """
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(f"{out_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, out_path)


def discover_papers_batch(
    arxiv_ids: Sequence[str],
    output_dir: Optional[Path | str] = None,
    client: Optional[Any] = None,
) -> dict[str, Optional[dict[str, Any]]]:
    """Query arXiv API for metadata in batch to optimize network roundtrips.

    HIGH PERFORMANCE:
    Instead of sending individual requests per ID, send a list of IDs to `arxiv.Search(id_list=chunk)`.
    Recommended batch chunk size: 50 to 100 IDs.

    Args:
        arxiv_ids: Sequence of base arXiv identifiers (e.g. ['2505.10666', '2505.10667']).
        output_dir: Optional base data directory to persist `metadata.json` for each paper.
        client: Optional reusable `arxiv.Client` instance to keep connection pool alive.

    Returns:
        dict[str, Optional[dict[str, Any]]]: Mapping from arxiv_id to its metadata dict (or None if not found).
    """
    if arxiv is None:
        raise RuntimeError("The 'arxiv' library is not installed. Please run `pip install arxiv>=4.0.0`.")

    cleaned_ids = [re.sub(r"v\d+$", "", str(aid).strip()) for aid in arxiv_ids if aid]
    results: dict[str, Optional[dict[str, Any]]] = {aid: None for aid in cleaned_ids}
    if not cleaned_ids:
        return results

    if client is None:
        client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)

    chunk_size = 100
    for i in range(0, len(cleaned_ids), chunk_size):
        chunk = cleaned_ids[i : i + chunk_size]
        try:
            # arxiv.Client enforces delay_seconds=3.0
            search = arxiv.Search(id_list=chunk)
            for paper in client.results(search):
                entry_id = paper.entry_id
                raw_id = (
                    paper.get_short_id()
                    if hasattr(paper, "get_short_id")
                    else entry_id.split("/")[-1]
                )
                base_id = re.sub(r"v\d+$", "", raw_id)

                matched_id = base_id
                if matched_id not in results and entry_id.split("/")[-1] in results:
                    matched_id = entry_id.split("/")[-1]

                v_count = parse_version_count(raw_id)
                versions = generate_version_list(matched_id, v_count)

                title = paper.title.strip().replace("\n", " ") if paper.title else ""
                authors = [author.name for author in paper.authors] if paper.authors else []
                sub_date = paper.published.isoformat() if paper.published else None
                rev_dates = (
                    [paper.updated.isoformat()]
                    if paper.updated and paper.updated != paper.published
                    else []
                )
                venue = paper.journal_ref if paper.journal_ref else None

                metadata = {
                    "arxiv_id": matched_id,
                    "title": title,
                    "authors": authors,
                    "submission_date": sub_date,
                    "revised_dates": rev_dates,
                    "venue": venue,
                    "versions": versions,
                }
                results[matched_id] = metadata

                if output_dir:
                    paper_dir = Path(output_dir) / matched_id
                    save_metadata(metadata, paper_dir / "metadata.json")

        except Exception as exc:
            logger.error("Error during batch discovery for chunk [%s...%s]: %s", chunk[0], chunk[-1], exc)

    return results


def discover_paper(
    arxiv_id: str,
    output_dir: Optional[Path | str] = None,
    client: Optional[Any] = None,
) -> Optional[dict[str, Any]]:
    """Query arXiv API for metadata and detect all versions of a single paper.

    Args:
        arxiv_id: Base arXiv identifier (e.g., '2505.10666').
        output_dir: Optional base data directory to persist `metadata.json`.
        client: Optional reusable `arxiv.Client` instance.

    Returns:
        Optional[dict[str, Any]]: Dictionary containing the extracted metadata,
        or None if the paper was not found or query failed.
    """
    clean_id = re.sub(r"v\d+$", "", str(arxiv_id).strip())
    batch_res = discover_papers_batch([clean_id], output_dir=output_dir, client=client)
    return batch_res.get(clean_id)
