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

GZIP_MAGIC = b"\x1f\x8b"
# PDF and PostScript submissions carry no LaTeX source.
NON_LATEX_MAGICS = (b"%PDF-", b"%!PS")


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
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    if archive_path is None:
        return ExtractionResult.PDF_ONLY
    archive = Path(archive_path)

    try:
        # Checked first: is_tarfile also recognises gzip-compressed tarballs.
        if tarfile.is_tarfile(archive):
            return _extract_tar(archive, target)

        with archive.open("rb") as fh:
            magic = fh.read(5)
        if magic.startswith(GZIP_MAGIC):
            with gzip.open(archive, "rb") as gz:
                content = gz.read()
            if content.startswith(NON_LATEX_MAGICS):
                return ExtractionResult.PDF_ONLY
            # Written as raw bytes so the LaTeX source is preserved byte-for-byte.
            (target / "main.tex").write_bytes(content)
            return ExtractionResult.SUCCESS
        if magic.startswith(NON_LATEX_MAGICS):
            return ExtractionResult.PDF_ONLY

        logger.error("Unrecognised archive format: %s (magic=%r)", archive, magic)
        return ExtractionResult.FAILED
    except (tarfile.TarError, OSError, EOFError) as exc:
        logger.error("Failed to extract %s: %s", archive, exc)
        return ExtractionResult.FAILED


def _extract_tar(archive: Path, target: Path) -> ExtractionResult:
    """Copy only regular .tex/.bib members of a tarball into target, keeping subfolders."""
    root = target.resolve()
    extracted = 0
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            # Regular files only: symlinks, hardlinks and devices are never written.
            if not member.isfile() or not is_latex_source_file(member.name):
                continue
            dest = (target / member.name).resolve()
            if not dest.is_relative_to(root):
                logger.warning("Skipping unsafe path in %s: %s", archive, member.name)
                continue
            src = tar.extractfile(member)
            if src is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
            extracted += 1
    # A tarball without any .tex/.bib (e.g. only figures + PDF) has no LaTeX source.
    return ExtractionResult.SUCCESS if extracted else ExtractionResult.PDF_ONLY
