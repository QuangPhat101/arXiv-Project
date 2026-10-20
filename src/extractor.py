"""Extractor Module: LaTeX Source Archive Selective Extractor.

Assigned to: Khánh (Member4)
Purpose:
    Decompress downloaded arXiv source archives and extract ONLY `.tex` and `.bib`
    files into the target version directory (e.g., `v1/`, `v2/`). Discards all
    images, PDFs, compiled binaries, and intermediate files while preserving
    original LaTeX code untouched (do NOT remove `\\includegraphics` or figure
    environments).
"""

from __future__ import annotations

import gzip
import logging
import shutil
import tarfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Valid extensions to retain
LATEX_EXTENSIONS = {".tex", ".bib"}


def is_latex_source_file(filename: str) -> bool:
    """Check whether a filename ends with an accepted LaTeX extension (.tex or .bib).

    Args:
        filename: Path or name of the file to check.

    Returns:
        bool: True if the file is a .tex or .bib file, False otherwise.
    """
    return Path(filename).suffix.lower() in LATEX_EXTENSIONS


def extract_tex_bib(
    archive_path: Path | str,
    target_dir: Path | str,
) -> bool:
    """Extract .tex and .bib files from an archive into target_dir.

    Handles multiple archive formats encountered on arXiv:
        1. `tar.gz` (multi-file submission): Inspect members via `tarfile`,
           and selectively extract only members with `.tex` or `.bib` extension.
        2. `gzip` single-file (single .tex submission): Read decompressed content
           via `gzip.open()`. If content is text/LaTeX, save as `main.tex`.
        3. `PDF-only` / non-LaTeX format: Archive may be a raw PDF. Detect this,
           leave `target_dir` as an empty folder, and log a warning.

    IMPORTANT:
        Do NOT edit, strip, or sanitize the content of `.tex` files.
        Retain all `\\includegraphics`, `figure` environments, and comments.

    Args:
        archive_path: Path to the downloaded source archive file.
        target_dir: Destination directory (e.g., path/to/2505.10666/v1).

    Returns:
        bool: True if extraction succeeded or valid empty folder created,
        False if archive extraction failed due to error.
    """
    # TODO (Khánh):
    # 1. Ensure target_dir exists.
    # 2. Try tarfile.is_tarfile(archive_path) or tarfile.open():
    #    - Loop over members, check is_latex_source_file(member.name).
    #    - Extract valid members to target_dir (prevent path traversal / Zip Slip).
    # 3. Else, try gzip.GzipFile:
    #    - Decompress; if first bytes don't look like PDF (%PDF-), save as main.tex.
    #    - If it's a PDF (%PDF-), log PDF-only submission and keep target_dir empty.
    # 4. Handle exceptions gracefully and return status.
    raise NotImplementedError("extract_tex_bib() is not yet implemented.")
