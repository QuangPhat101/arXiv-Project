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
from pathlib import Path
from typing import Any, Optional, Sequence

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
    # TODO (Bảo - Member3):
    # Regex hoặc string split tìm trailing 'v(\\d+)'.
    # Nếu không có 'v', trả về 1.
    raise NotImplementedError("parse_version_count() is not yet implemented.")


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
    # TODO (Bảo - Member3):
    # Trả về [f"{base_id}v{i}" for i in range(1, version_count + 1)]
    raise NotImplementedError("generate_version_list() is not yet implemented.")


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
    # TODO (Bảo - Member3):
    # 1. Khởi tạo arxiv.Client() nếu client is None.
    # 2. Chia arxiv_ids thành các chunk (50-100 IDs).
    # 3. Với mỗi chunk:
    #    - Tạo arxiv.Search(id_list=chunk)
    #    - Duyệt qua client.results(search)
    #    - Trích xuất metadata (arxiv_id, title, authors, submission_date, revised_dates, venue, versions)
    #    - Nếu có output_dir: lưu vào {output_dir}/{arxiv_id}/metadata.json (ghi atomic qua file tạm)
    # 4. Trả về dict kết quả ánh xạ {arxiv_id: metadata_dict}.
    raise NotImplementedError("discover_papers_batch() is not yet implemented.")


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
    # TODO (Bảo - Member3):
    # Có thể gọi discover_papers_batch([arxiv_id], output_dir=output_dir, client=client)[arxiv_id]
    raise NotImplementedError("discover_paper() is not yet implemented.")


def save_metadata(metadata: dict[str, Any], output_file: Path | str) -> None:
    """Save metadata dictionary to a JSON file atomically.

    Args:
        metadata: Metadata dictionary to serialize.
        output_file: Destination file path (e.g., path/to/metadata.json).
    """
    # TODO (Bảo - Member3):
    # Tạo thư mục cha nếu chưa có.
    # Ghi ra file tạm .tmp trước, sau đó replace vào output_file để đảm bảo tính nguyên tử (atomic).
    raise NotImplementedError("save_metadata() is not yet implemented.")
