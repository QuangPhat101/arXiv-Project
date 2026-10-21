"""Extractor Module: LaTeX Source Archive Selective Extractor.

Assigned to: Khánh 
Purpose:
    Decompress downloaded arXiv source archives and extract ONLY `.tex` and `.bib`
    files into the target version directory (e.g., `v1/`, `v2/`). Discards all
    images, PDFs, compiled binaries, and intermediate files while preserving
    original LaTeX code untouched (do NOT remove `\\includegraphics` or figure
    environments).

Completeness & Contract Requirements for Member4:
    1. Distinguish extraction states:
       - Multi-file tar.gz or gzip containing .tex/.bib: Extract to target_dir, return ExtractionResult.SUCCESS ("SUCCESS").
       - PDF-only or source missing (no LaTeX): Create empty target_dir, return ExtractionResult.PDF_ONLY ("PDF_ONLY").
       - Corrupted archive or extraction crash: Raise RuntimeError or return ExtractionResult.FAILED ("FAILED").
    2. IMPORTANT SECURITY: Check member paths before extraction to prevent Zip Slip / path traversal attacks.
       Ensure member.name does not resolve outside target_dir.
    3. IMPORTANT: DO NOT modify the content of .tex files. Keep all \\includegraphics and figure environments intact.
"""

from __future__ import annotations

import enum
import gzip
import logging
import shutil
import tarfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Valid extensions to retain
LATEX_EXTENSIONS = {".tex", ".bib"}


class ExtractionResult(str, enum.Enum):
    SUCCESS = "SUCCESS"        # Found and extracted .tex and/or .bib files
    PDF_ONLY = "PDF_ONLY"      # No LaTeX source exists (PDF submission), valid empty folder created
    FAILED = "FAILED"          # Corrupted archive, I/O error, or extraction error


def is_latex_source_file(filename: str) -> bool:
    """Check whether a filename ends with an accepted LaTeX extension (.tex or .bib).

    Args:
        filename: Path or name of the file to check.

    Returns:
        bool: True if the file is a .tex or .bib file, False otherwise.
    """
    return Path(filename).suffix.lower() in LATEX_EXTENSIONS


def extract_tex_bib(
    archive_path: Optional[Path | str],
    target_dir: Path | str,
) -> ExtractionResult:
    """Extract .tex and .bib files from an archive into target_dir.

    Handles multiple archive formats encountered on arXiv:
        1. If archive_path is None: source is not available on arXiv (PDF-only).
           Create an empty target_dir and return ExtractionResult.PDF_ONLY.
        2. `tar.gz` (multi-file submission): Inspect members via `tarfile`,
           and selectively extract only members with `.tex` or `.bib` extension.
           Return ExtractionResult.SUCCESS.
        3. `gzip` single-file (single .tex submission): Read decompressed content
           via `gzip.open()`. If content is text/LaTeX, save as `main.tex`.
           Return ExtractionResult.SUCCESS.
        4. Raw PDF file (%PDF- magic bytes): Leave target_dir empty, return ExtractionResult.PDF_ONLY.

    IMPORTANT:
        Do NOT edit, strip, or sanitize the content of `.tex` files.
        Retain all `\\includegraphics`, `figure` environments, and comments.

    Args:
        archive_path: Path to the downloaded source archive file, or None if unavailable.
        target_dir: Destination directory (e.g., path/to/2505.10666/v1).

    Returns:
        ExtractionResult: SUCCESS, PDF_ONLY, or FAILED.
    """
    # TODO (Khánh - Member4):
    # 1. target = Path(target_dir); target.mkdir(parents=True, exist_ok=True)
    # 2. if archive_path is None: return ExtractionResult.PDF_ONLY
    # 3. archive = Path(archive_path)
    # 4. Kiểm tra magic bytes / định dạng:
    #    - Thử tarfile: lọc member is_latex_source_file(m.name), extract vào target
    #    - Thử gzip: đọc text, ghi vào target / "main.tex"
    #    - Nếu là PDF (%PDF-): return ExtractionResult.PDF_ONLY
    # 5. Nếu gặp lỗi file hỏng: log error và return ExtractionResult.FAILED
    raise NotImplementedError("extract_tex_bib() is not yet implemented.")
