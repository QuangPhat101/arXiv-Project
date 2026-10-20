"""Discovery Module: Paper Metadata Extraction and Version Detection.

Assigned to: Bảo (Member3)
Purpose:
    Query arXiv API using the official `arxiv` Python library to extract paper
    metadata (title, authors, submission date, revised dates, venue/journal_ref)
    and detect all available version numbers from the latest versioned entry ID.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def parse_version_count(entry_id: str) -> int:
    """Extract the total number of versions from an arXiv entry ID.

    For example, given 'http://arxiv.org/abs/2505.10666v3' or '2505.10666v3',
    this function parses the trailing version suffix 'v3' and returns 3.
    If no version suffix is present, defaults to 1.

    Args:
        entry_id: arXiv entry URL or versioned ID string.

    Returns:
        int: The highest version number (total versions available).
    """
    # TODO (Bảo): Parse trailing 'v{n}' using regex or string splitting.
    # Return integer n (minimum 1).
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
    # TODO (Bảo): Return [f"{base_id}v{i}" for i in range(1, version_count + 1)].
    raise NotImplementedError("generate_version_list() is not yet implemented.")


def discover_paper(
    arxiv_id: str,
    output_dir: Optional[Path | str] = None,
) -> Optional[dict[str, Any]]:
    """Query arXiv API for metadata and detect all versions of a given paper.

    Uses `arxiv.Client` and `arxiv.Search(id_list=[arxiv_id])` to query metadata.
    Extracts:
        - `arxiv_id`: base ID (str)
        - `title`: title (str)
        - `authors`: list of author names (list[str])
        - `submission_date`: ISO string of initial submission (from `published`)
        - `revised_dates`: list of ISO strings of revisions (from `updated`)
        - `venue`: journal reference if available, else None
        - `versions`: list of version strings (e.g., ["2505.10666v1", "2505.10666v2"])

    If `output_dir` is provided, automatically saves metadata to:
        `{output_dir}/{arxiv_id}/metadata.json`

    Args:
        arxiv_id: Base arXiv identifier (e.g., '2505.10666').
        output_dir: Optional base data directory to persist `metadata.json`.

    Returns:
        Optional[dict[str, Any]]: Dictionary containing the extracted metadata,
        or None if the paper was not found or query failed.
    """
    # TODO (Bảo):
    # 1. Initialize arxiv.Client().
    # 2. Search arxiv.Search(id_list=[arxiv_id]).
    # 3. Retrieve first result; if none, return None.
    # 4. Extract entry_id, parse version_count, generate versions list.
    # 5. Extract title, authors, published, updated, journal_ref.
    # 6. Format according to schema.
    # 7. If output_dir: save to {output_dir}/{arxiv_id}/metadata.json using save_metadata().
    # 8. Return the metadata dictionary.
    raise NotImplementedError("discover_paper() is not yet implemented.")


def save_metadata(metadata: dict[str, Any], output_file: Path | str) -> None:
    """Save metadata dictionary to a JSON file.

    Creates parent directories if they do not exist, and writes formatted JSON
    with indent=2 and UTF-8 encoding.

    Args:
        metadata: Metadata dictionary to serialize.
        output_file: Destination file path (e.g., path/to/metadata.json).
    """
    # TODO (Bảo): Create parent dir, write json with indent=2, ensure_ascii=False.
    raise NotImplementedError("save_metadata() is not yet implemented.")
