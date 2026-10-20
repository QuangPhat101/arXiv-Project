"""Crawler Orchestrator: Main Pipeline Coordinator.

Assigned to: Phát (Member2)
Purpose:
    Coordinate the end-to-end data acquisition workflow for arXiv papers:
        1. Resolve base IDs from command line range arguments.
        2. Query metadata and discover available versions (discovery.py).
        3. Download source archives for all versions (downloader.py).
        4. Extract selective .tex and .bib files into version folders (extractor.py).
        5. Fetch citations and references from Semantic Scholar (references.py).
        6. Manage checkpointing/resumption to support interrupted runs.
        7. Provide graceful error isolation, logging, and summary reporting.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Sequence

# Fallback imports to support execution from both project root and src/ directory
try:
    from src.discovery import discover_paper
    from src.downloader import download_source
    from src.extractor import extract_tex_bib
    from src.references import get_references
    from src.utils import setup_logger
except ImportError:
    from discovery import discover_paper  # type: ignore[no-redef]
    from downloader import download_source  # type: ignore[no-redef]
    from extractor import extract_tex_bib  # type: ignore[no-redef]
    from references import get_references  # type: ignore[no-redef]
    from utils import setup_logger  # type: ignore[no-redef]

# Try importing tqdm for a progress bar, fallback gracefully if not installed
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore[assignment]

logger = logging.getLogger("arxiv_crawler")


def generate_arxiv_ids(month: str, start: int, end: int) -> list[str]:
    """Generate a list of standard modern arXiv IDs for a single month.

    Example:
        generate_arxiv_ids("2505", 10666, 10668)
        -> ["2505.10666", "2505.10667", "2505.10668"]

    Args:
        month: 4-digit year-month code (e.g., '2505' for May 2025).
        start: Starting 5-digit sequence number (inclusive).
        end: Ending 5-digit sequence number (inclusive).

    Returns:
        list[str]: Formatted arXiv identifier strings.
    """
    if start > end:
        raise ValueError(f"Start ID ({start}) must be <= End ID ({end})")
    return [f"{month}.{i:05d}" for i in range(start, end + 1)]


def generate_cross_month_ids(
    start_month: str, start_id: int,
    end_month: str, end_id: int,
    max_id_per_month: int = 99999,
) -> list[str]:
    """Generate arXiv IDs spanning two consecutive months.

    For ranges like Member3: 2503.21914 -> 2504.02522, where the range
    crosses a month boundary.

    Example:
        generate_cross_month_ids("2503", 21914, "2504", 2522)
        -> ["2503.21914", ..., "2503.99999", "2504.00001", ..., "2504.02522"]

    Args:
        start_month: 4-digit code of the first month (e.g., '2503').
        start_id: Starting sequence number in start_month (inclusive).
        end_month: 4-digit code of the second month (e.g., '2504').
        end_id: Ending sequence number in end_month (inclusive).
        max_id_per_month: Highest possible sequence number in a month.

    Returns:
        list[str]: Combined list of arXiv IDs across both months.
    """
    ids = generate_arxiv_ids(start_month, start_id, max_id_per_month)
    ids += generate_arxiv_ids(end_month, 1, end_id)
    return ids


def load_checkpoint(checkpoint_file: Path) -> set[str]:
    """Load previously completed arXiv IDs from a checkpoint file.

    Args:
        checkpoint_file: Path to the checkpoint tracking text file.

    Returns:
        set[str]: Set of arXiv IDs marked as completed.
    """
    completed_ids: set[str] = set()
    if checkpoint_file.exists():
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            for line in f:
                item = line.strip()
                if item and not item.startswith("#"):
                    completed_ids.add(item)
    return completed_ids


def mark_completed(checkpoint_file: Path, arxiv_id: str) -> None:
    """Record a successfully processed arXiv ID into the checkpoint file.

    Args:
        checkpoint_file: Path to the checkpoint tracking text file.
        arxiv_id: Successfully crawled arXiv ID.
    """
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_file, "a", encoding="utf-8") as f:
        f.write(f"{arxiv_id}\n")


def is_paper_complete(paper_dir: Path) -> bool:
    """Validate whether a paper folder has all required files.

    A paper is considered complete if both `metadata.json` and `references.json`
    exist within its directory.

    Args:
        paper_dir: Path to the paper directory (e.g., data/2505.10666).

    Returns:
        bool: True if required files exist, False otherwise.
    """
    metadata_file = paper_dir / "metadata.json"
    references_file = paper_dir / "references.json"
    return metadata_file.is_file() and references_file.is_file()


def crawl_single_paper(
    arxiv_id: str,
    output_dir: Path,
    temp_dir: Path,
) -> bool:
    """Execute the full crawling pipeline for a single paper.

    Pipeline Steps:
        1. Query metadata & detect all versions (`discovery.discover_paper`).
        2. For each detected version:
            a. Download source archive to a temporary file (`downloader.download_source`).
            b. Selectively extract `.tex` and `.bib` into `v{n}/` (`extractor.extract_tex_bib`).
            c. Delete temporary archive to minimize disk usage.
        3. Query citation references from Semantic Scholar (`references.get_references`).

    Args:
        arxiv_id: Base arXiv identifier (e.g., '2505.10666').
        output_dir: Root directory where paper folders are created.
        temp_dir: Temporary directory for intermediate archive downloads.

    Returns:
        bool: True if crawling succeeded, False on failure.
    """
    paper_dir = output_dir / arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------
    # Step 1: Discovery (Metadata & Version resolution)
    # ---------------------------------------------------------
    logger.info("[%s] Fetching metadata & detecting versions...", arxiv_id)
    metadata = discover_paper(arxiv_id, output_dir=output_dir)
    if not metadata:
        logger.error("[%s] Failed to discover metadata.", arxiv_id)
        return False

    versions: list[str] = metadata.get("versions", [])
    if not versions:
        # Fallback to at least version 1 if versions list was not populated
        versions = [f"{arxiv_id}v1"]

    logger.info("[%s] Detected %d version(s): %s", arxiv_id, len(versions), versions)

    # ---------------------------------------------------------
    # Step 2: Download & Extract each version
    # ---------------------------------------------------------
    for version_id in versions:
        # Parse version suffix (e.g., '2505.10666v2' -> 'v2')
        v_suffix = "v1"
        if "v" in version_id:
            v_suffix = f"v{version_id.split('v')[-1]}"

        version_dir = paper_dir / v_suffix
        version_dir.mkdir(parents=True, exist_ok=True)

        temp_archive_path = temp_dir / f"{version_id}.archive"
        logger.info("[%s] Downloading source for %s...", arxiv_id, version_id)

        try:
            downloaded_file = download_source(version_id, temp_archive_path)
            if downloaded_file and downloaded_file.exists():
                logger.info("[%s] Extracting LaTeX sources for %s...", arxiv_id, version_id)
                extract_tex_bib(downloaded_file, version_dir)
            else:
                logger.warning("[%s] Source not available for %s (empty folder created)", arxiv_id, version_id)
        finally:
            # Always clean up temporary downloaded archive to save disk space
            if temp_archive_path.exists():
                try:
                    temp_archive_path.unlink()
                except OSError as e:
                    logger.debug("Failed to remove temp file %s: %s", temp_archive_path, e)

    # ---------------------------------------------------------
    # Step 3: References (Semantic Scholar Graph API)
    # ---------------------------------------------------------
    logger.info("[%s] Fetching references from Semantic Scholar...", arxiv_id)
    try:
        get_references(arxiv_id, output_dir=output_dir)
    except Exception as e:
        logger.warning("[%s] Failed to fetch references: %s", arxiv_id, e)

    return True


def run_pipeline(
    arxiv_ids: Sequence[str],
    output_dir: Path,
    resume: bool = True,
    checkpoint_file: Optional[Path] = None,
) -> dict[str, Any]:
    """Execute the pipeline over a collection of arXiv IDs with progress tracking.

    Args:
        arxiv_ids: Ordered sequence of arXiv IDs to process.
        output_dir: Base directory where output is saved.
        resume: Whether to skip papers that are already completed.
        checkpoint_file: File path for recording checkpoint progress.

    Returns:
        dict[str, Any]: Execution summary metrics.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if checkpoint_file is None:
        checkpoint_file = output_dir / "checkpoint.txt"

    completed_ids = load_checkpoint(checkpoint_file) if resume else set()
    failed_papers: dict[str, str] = {}
    success_count = 0
    skipped_count = 0

    temp_dir = Path(tempfile.mkdtemp(prefix="arxiv_src_"))
    start_time = time.time()

    logger.info("Starting crawl for %d target paper(s).", len(arxiv_ids))
    logger.info("Output directory: %s", output_dir.resolve())
    logger.info("Checkpoint file: %s (%d previously completed)", checkpoint_file, len(completed_ids))

    try:
        iterator = tqdm(arxiv_ids, desc="Crawling arXiv papers") if tqdm else arxiv_ids

        for arxiv_id in iterator:
            # Checkpoint resume check
            if resume and (arxiv_id in completed_ids or is_paper_complete(output_dir / arxiv_id)):
                logger.debug("[%s] Already completed, skipping.", arxiv_id)
                skipped_count += 1
                continue

            try:
                success = crawl_single_paper(arxiv_id, output_dir, temp_dir)
                if success:
                    mark_completed(checkpoint_file, arxiv_id)
                    completed_ids.add(arxiv_id)
                    success_count += 1
                else:
                    failed_papers[arxiv_id] = "Crawling failed or paper not found"
            except Exception as exc:
                logger.exception("[%s] Unexpected exception occurred: %s", arxiv_id, exc)
                failed_papers[arxiv_id] = str(exc)

    finally:
        # Clean up global temp folder
        shutil.rmtree(temp_dir, ignore_errors=True)

    elapsed = time.time() - start_time
    summary = {
        "total_targets": len(arxiv_ids),
        "skipped": skipped_count,
        "succeeded": success_count,
        "failed": len(failed_papers),
        "failed_papers": failed_papers,
        "elapsed_seconds": round(elapsed, 2),
    }

    # Summary Report
    logger.info("=" * 60)
    logger.info("CRAWL SUMMARY REPORT")
    logger.info("Total targets:     %d", summary["total_targets"])
    logger.info("Skipped (resume):  %d", summary["skipped"])
    logger.info("Succeeded:         %d", summary["succeeded"])
    logger.info("Failed:            %d", summary["failed"])
    logger.info("Elapsed time:      %.2f seconds", summary["elapsed_seconds"])
    logger.info("=" * 60)

    return summary


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for the crawler runner."""
    parser = argparse.ArgumentParser(
        description="arXiv Data Science Crawler - Milestone 1",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--month",
        type=str,
        default=None,
        help="4-digit month code (e.g. '2505' for 2025-05). Use alone for single-month range.",
    )
    parser.add_argument(
        "--start",
        type=int,
        required=True,
        help="Starting paper ID sequence number (e.g. 10666)",
    )
    parser.add_argument(
        "--end",
        type=int,
        required=True,
        help="Ending paper ID sequence number (e.g. 15665)",
    )
    parser.add_argument(
        "--end-month",
        type=str,
        default=None,
        help="End month code for cross-month ranges (e.g. '2504'). Requires --month as start month.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./data"),
        help="Destination directory for output papers",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable checkpoint resumption and re-crawl all papers",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional file path to write log output",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for CLI execution."""
    args = parse_arguments(argv)

    # Initialize logger
    try:
        setup_logger(name="arxiv_crawler", log_file=args.log_file)
    except (NotImplementedError, Exception):
        # Fallback to basic logging if utils.setup_logger() is not yet implemented
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    # Generate IDs
    try:
        if args.end_month:
            if not args.month:
                logger.error("--month is required as start month when using --end-month")
                return 1
            ids_to_crawl = generate_cross_month_ids(
                args.month, args.start, args.end_month, args.end
            )
        else:
            if not args.month:
                logger.error("--month is required for single-month range")
                return 1
            ids_to_crawl = generate_arxiv_ids(args.month, args.start, args.end)
    except ValueError as err:
        logger.error("Invalid ID range: %s", err)
        return 1

    summary = run_pipeline(
        arxiv_ids=ids_to_crawl,
        output_dir=args.output,
        resume=not args.no_resume,
    )

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
