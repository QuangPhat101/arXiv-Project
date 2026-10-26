"""Crawler Orchestrator: Main Pipeline Coordinator.

Assigned to: Phát 
Purpose:
    Coordinate the end-to-end data acquisition workflow for arXiv papers:
        1. Resolve base IDs from command line range arguments (single month or cross month).
        2. Query metadata and discover available versions via batch discovery (discovery.py).
        3. Download source archives for all missing versions (downloader.py).
        4. Selectively extract .tex and .bib into version directories, handling PDF-only (extractor.py).
        5. Fetch citations and references from Semantic Scholar (references.py).
        6. Manage robust checkpointing/resumption per version and paper.
        7. Provide graceful error isolation, logging, and summary reporting.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional, Sequence

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

# Fallback imports to support execution from both project root and src/ directory
try:
    from src.discovery import discover_paper, discover_papers_batch
    from src.downloader import download_source
    from src.extractor import ExtractionResult, extract_tex_bib
    from src.references import get_references
    from src.utils import setup_logger, s2_rate_limiter
except ImportError:
    from discovery import discover_paper, discover_papers_batch  # type: ignore[no-redef]
    from downloader import download_source  # type: ignore[no-redef]
    from extractor import ExtractionResult, extract_tex_bib  # type: ignore[no-redef]
    from references import get_references  # type: ignore[no-redef]
    from utils import setup_logger, s2_rate_limiter  # type: ignore[no-redef]

# Enforce safe 3.0s interval for Semantic Scholar
s2_rate_limiter.min_interval = 3.0

# Try importing tqdm for progress bar
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
    """
    if not re.fullmatch(r"[0-9]{2}(0[1-9]|1[0-2])", month):
        raise ValueError(f"Invalid month format: '{month}'. Must be YYMM (e.g. 2505).")
    if not 1 <= start <= end <= 99999:
        raise ValueError(f"Invalid range: require 1 <= start ({start}) <= end ({end}) <= 99999")
    return [f"{month}.{i:05d}" for i in range(start, end + 1)]


def generate_cross_month_ids(
    start_month: str,
    start_id: int,
    end_month: str,
    end_id: int,
    start_month_max: Optional[int] = None,
    end_month_start: int = 1,
) -> list[str]:
    """Generate arXiv IDs spanning two consecutive months.

    For ranges like Member3 (Bảo): 2025-03: 21914 -> 2025-04: 2522.
    Requires start_month_max to specify the actual maximum sequence number of the start month,
    preventing generation of tens of thousands of non-existent IDs up to 99999.
    end_month_start defaults to 1 for standard cross-month transitions.
    """
    if start_month_max is None:
        raise ValueError(
            "start_month_max is required for cross-month range to avoid generating 80,000+ phantom IDs. "
            "Please provide --start-month-max (e.g. 26500 for March 2025)."
        )
    ids_first_month = generate_arxiv_ids(start_month, start_id, start_month_max)
    ids_second_month = generate_arxiv_ids(end_month, end_month_start, end_id)
    return ids_first_month + ids_second_month


def load_checkpoint(checkpoint_file: Path) -> set[str]:
    """Load previously completed arXiv IDs from a checkpoint file."""
    completed_ids: set[str] = set()
    if checkpoint_file.exists():
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            for line in f:
                item = line.strip()
                if item and not item.startswith("#"):
                    completed_ids.add(item)
    return completed_ids


def mark_completed_atomic(checkpoint_file: Path, arxiv_id: str) -> None:
    """Record a successfully processed arXiv ID into the checkpoint file atomically."""
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_file, "a", encoding="utf-8") as f:
        f.write(f"{arxiv_id}\n")


def _read_json(path: Path) -> Any:
    """Read and parse JSON file, returning None if missing or corrupt."""
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, UnicodeError):
        return None


def is_version_completed(version_dir: Path) -> bool:
    """Check if a specific version directory has been successfully extracted or verified as PDF-only."""
    if not version_dir.is_dir():
        return False
    # Marked complete by a stamp file (covers both SUCCESS and PDF_ONLY)
    stamp_file = version_dir / ".complete"
    if stamp_file.is_file():
        return True
    # Or contains valid .tex or .bib files
    has_latex = any(
        f.suffix.lower() in {".tex", ".bib"}
        for f in version_dir.iterdir()
        if f.is_file()
    )
    return has_latex


def mark_version_completed(version_dir: Path, status: str = "ok") -> None:
    """Write an atomic completion marker inside the version directory."""
    version_dir.mkdir(parents=True, exist_ok=True)
    stamp_path = version_dir / ".complete"
    tmp_path = version_dir / ".complete.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(f"{status}\n")
    os.replace(tmp_path, stamp_path)


def is_paper_complete(paper_dir: Path) -> bool:
    """Validate whether all required components of a paper exist and are valid.

    Completion criteria:
        1. Valid `metadata.json` exists with non-empty versions list.
        2. Valid `references.json` exists (can be empty list if unindexed).
        3. Every detected version folder (v1, v2, ...) is completed.
    """
    if not paper_dir.is_dir():
        return False

    metadata = _read_json(paper_dir / "metadata.json")
    if not isinstance(metadata, dict):
        return False

    versions = metadata.get("versions")
    if not isinstance(versions, list) or not versions:
        return False

    # Check references
    refs = _read_json(paper_dir / "references.json")
    if not isinstance(refs, list):
        return False

    # Check each version folder
    for version_id in versions:
        v_suffix = "v1"
        if "v" in version_id:
            v_suffix = f"v{version_id.split('v')[-1]}"
        v_dir = paper_dir / v_suffix
        if not is_version_completed(v_dir):
            return False

    return True


def crawl_single_paper(
    arxiv_id: str,
    output_dir: Path,
    temp_dir: Path,
    session: Optional[Any] = None,
    s2_api_key: Optional[str] = None,
    metadata_cache: Optional[dict[str, Any]] = None,
) -> bool:
    """Execute the crawling pipeline for a single paper with strict error validation.

    Returns True ONLY if all required steps succeed.
    Never returns True on network failure or incomplete downloads.
    """
    paper_dir = output_dir / arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    # 1. Discovery
    metadata = _read_json(paper_dir / "metadata.json")
    if not isinstance(metadata, dict) or not metadata.get("versions"):
        if metadata_cache and arxiv_id in metadata_cache:
            metadata = metadata_cache[arxiv_id]
        else:
            try:
                metadata = discover_paper(arxiv_id, output_dir=output_dir)
            except NotImplementedError:
                logger.warning("[%s] discover_paper not implemented yet.", arxiv_id)
                metadata = None

    if not metadata or not metadata.get("versions"):
        logger.warning("[%s] Discovery query unavailable (API rate limit). Defaulting to v1 to proceed with download.", arxiv_id)
        metadata = {
            "arxiv_id": arxiv_id,
            "title": "",
            "authors": [],
            "submission_date": None,
            "revised_dates": [],
            "venue": None,
            "versions": [f"{arxiv_id}v1"],
        }
        with open(paper_dir / "metadata.json", "w", encoding="utf-8") as f_meta:
            json.dump(metadata, f_meta, indent=2)

    versions: list[str] = metadata["versions"]

    # 2. Parallel / Async trigger for Semantic Scholar references
    # Fetch references while downloading sources to optimize overall wall-clock time
    refs_exist = isinstance(_read_json(paper_dir / "references.json"), list)
    if not refs_exist:
        try:
            get_references(arxiv_id, output_dir=output_dir, api_key=s2_api_key, session=session)
        except NotImplementedError:
            logger.warning("[%s] get_references not implemented yet by Member3. Halting paper processing.", arxiv_id)
            return False
        except Exception as exc:
            logger.error("[%s] Error fetching references from Semantic Scholar: %s", arxiv_id, exc)
            return False

    # 3. Process each version
    for version_id in versions:
        v_suffix = "v1"
        if "v" in version_id:
            v_suffix = f"v{version_id.split('v')[-1]}"

        version_dir = paper_dir / v_suffix
        if is_version_completed(version_dir):
            logger.debug("[%s] Version %s already completed, skipping.", arxiv_id, v_suffix)
            continue

        temp_archive_path = temp_dir / f"{version_id}.archive"

        # Download source
        try:
            downloaded_file = download_source(
                versioned_id=version_id,
                dest_path=temp_archive_path,
                session=session,
            )
        except NotImplementedError:
            logger.warning("[%s] download_source not implemented yet.", version_id)
            return False
        except Exception as exc:
            logger.error("[%s] Failed to download %s: %s", arxiv_id, version_id, exc)
            return False

        # Extract source (.tex / .bib) or handle PDF-only
        try:
            archive_size_bytes = temp_archive_path.stat().st_size if temp_archive_path.exists() else 0

            extract_result = extract_tex_bib(
                archive_path=downloaded_file,
                target_dir=version_dir,
            )
            if extract_result == ExtractionResult.FAILED:
                logger.error("[%s] Extraction failed for version %s", arxiv_id, version_id)
                return False

            # Calculate extracted size (.tex and .bib only) for benchmark reporting
            extracted_size_bytes = sum(
                f.stat().st_size
                for f in version_dir.iterdir()
                if f.is_file() and f.suffix.lower() in {".tex", ".bib"}
            )

            status_payload = f"{extract_result.value}|raw_bytes:{archive_size_bytes}|extracted_bytes:{extracted_size_bytes}"
            mark_version_completed(version_dir, status=status_payload)
        except NotImplementedError:
            logger.warning("[%s] extract_tex_bib not implemented yet.", version_id)
            return False
        except Exception as exc:
            logger.error("[%s] Extraction exception for %s: %s", arxiv_id, version_id, exc)
            return False
        finally:
            if temp_archive_path.exists():
                try:
                    temp_archive_path.unlink()
                except OSError:
                    pass

    return is_paper_complete(paper_dir)


def run_pipeline(
    arxiv_ids: Sequence[str],
    output_dir: Path,
    resume: bool = True,
    checkpoint_file: Optional[Path] = None,
    batch_size: int = 100,
    s2_api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Execute the pipeline over target arXiv IDs with batch discovery and version-level resume."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if checkpoint_file is None:
        checkpoint_file = output_dir / "checkpoint.txt"

    completed_ids = load_checkpoint(checkpoint_file) if resume else set()
    failed_papers: dict[str, str] = {}
    success_count = 0
    skipped_count = 0

    pending_ids = [aid for aid in arxiv_ids if aid not in completed_ids or not is_paper_complete(output_dir / aid)]
    skipped_count = len(arxiv_ids) - len(pending_ids)

    logger.info("Total targets: %d | Completed previously: %d | Pending: %d", len(arxiv_ids), skipped_count, len(pending_ids))

    if not pending_ids:
        logger.info("All target papers are already completed.")
        return {
            "total_targets": len(arxiv_ids),
            "skipped": skipped_count,
            "succeeded": 0,
            "failed": 0,
            "failed_papers": {},
            "elapsed_seconds": 0.0,
        }

    # Session reuse for HTTP connection pooling
    session = requests.Session() if requests else None
    temp_dir = Path(tempfile.mkdtemp(prefix="arxiv_src_", dir=output_dir))
    start_time = time.perf_counter()

    try:
        # Phase 1: High-Performance Batch Discovery
        missing_meta = [
            aid for aid in pending_ids
            if not (output_dir / aid / "metadata.json").is_file()
            or not _read_json(output_dir / aid / "metadata.json")
        ]
        metadata_cache: dict[str, Any] = {}
        if missing_meta:
            logger.info("Phase 1: Running Batch Discovery for %d papers lacking metadata...", len(missing_meta))
            try:
                for i in range(0, len(missing_meta), batch_size):
                    chunk = missing_meta[i:i + batch_size]
                    chunk_meta = discover_papers_batch(chunk, output_dir=output_dir)
                    if chunk_meta:
                        metadata_cache.update(chunk_meta)
            except NotImplementedError:
                logger.info("Batch discovery not implemented yet by Member3; will fallback to single discovery.")
        else:
            logger.info("Phase 1: Skipping remote discovery (100%% of metadata exists locally for %d papers).", len(pending_ids))

        # Phase 2: Process Download & Extraction per paper
        logger.info("Phase 2: Downloading & Extracting paper sources...")
        iterator = tqdm(pending_ids, desc="Crawling arXiv papers") if tqdm else pending_ids

        for arxiv_id in iterator:
            try:
                success = crawl_single_paper(
                    arxiv_id=arxiv_id,
                    output_dir=output_dir,
                    temp_dir=temp_dir,
                    session=session,
                    s2_api_key=s2_api_key,
                    metadata_cache=metadata_cache,
                )
                if success:
                    mark_completed_atomic(checkpoint_file, arxiv_id)
                    completed_ids.add(arxiv_id)
                    success_count += 1
                else:
                    failed_papers[arxiv_id] = "Step failure (download/extraction/metadata)"
            except Exception as exc:
                logger.exception("[%s] Unexpected exception: %s", arxiv_id, exc)
                failed_papers[arxiv_id] = str(exc)

            # Clean 3.0s cooldown between consecutive papers as requested
            time.sleep(3.0)

    finally:
        if session:
            session.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    elapsed = time.perf_counter() - start_time
    summary = {
        "total_targets": len(arxiv_ids),
        "skipped": skipped_count,
        "succeeded": success_count,
        "failed": len(failed_papers),
        "failed_papers": failed_papers,
        "elapsed_seconds": round(elapsed, 2),
    }

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
    parser.add_argument("--month", type=str, default=None, help="4-digit month code (e.g. '2505')")
    parser.add_argument("--start", type=int, required=True, help="Starting sequence ID (e.g. 10666)")
    parser.add_argument("--end", type=int, required=True, help="Ending sequence ID (e.g. 15665)")
    parser.add_argument("--end-month", type=str, default=None, help="End month for cross-month range (e.g. '2504')")
    parser.add_argument("--end-month-start", type=int, default=1, help="Starting sequence ID of the end month (default: 1)")
    parser.add_argument("--start-month-max", type=int, default=None, help="Verified max ID of start month for cross-month ranges")
    parser.add_argument("--output", type=Path, default=Path("./data"), help="Output directory")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for discovery API queries")
    parser.add_argument("--s2-api-key", type=str, default=None, help="Optional Semantic Scholar API Key")
    parser.add_argument("--no-resume", action="store_true", help="Disable checkpoint resumption")
    parser.add_argument("--profile", action="store_true", help="Monitor RAM consumption periodically via psutil for Colab benchmark")
    parser.add_argument("--log-file", type=Path, default=None, help="Optional log file path")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for CLI execution."""
    args = parse_arguments(argv)

    try:
        setup_logger(name="arxiv_crawler", log_file=args.log_file)
    except NotImplementedError:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    try:
        if args.end_month:
            if not args.month:
                logger.error("--month is required when using --end-month")
                return 1
            ids_to_crawl = generate_cross_month_ids(
                start_month=args.month,
                start_id=args.start,
                end_month=args.end_month,
                end_id=args.end,
                start_month_max=args.start_month_max,
                end_month_start=args.end_month_start,
            )
        else:
            if not args.month:
                logger.error("--month is required for single-month range")
                return 1
            ids_to_crawl = generate_arxiv_ids(args.month, args.start, args.end)
    except ValueError as err:
        logger.error("Invalid range configuration: %s", err)
        return 1

    summary = run_pipeline(
        arxiv_ids=ids_to_crawl,
        output_dir=args.output,
        resume=not args.no_resume,
        batch_size=args.batch_size,
        s2_api_key=args.s2_api_key,
    )

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
