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
import queue
import re
import shutil
import sys
import tempfile
import threading
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

try:
    from src.profiler import CrawlerProfiler
except ImportError:
    try:
        from profiler import CrawlerProfiler  # type: ignore[no-redef]
    except ImportError:
        CrawlerProfiler = None  # type: ignore[assignment]

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]

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
    profiler: Optional[Any] = None,
    paper_phases: Optional[dict[str, float]] = None,
    error_holder: Optional[list[str]] = None,
) -> bool:
    """Execute the crawling pipeline for a single paper with strict error validation.

    Returns True ONLY if all required steps succeed.
    Never returns True on network failure or incomplete downloads.
    """
    if error_holder is not None:
        error_holder.clear()

    if paper_phases is not None:
        paper_phases.clear()
        paper_phases.update({"discovery": 0.0, "download": 0.0, "extract": 0.0, "s2_references": 0.0})

    paper_dir = output_dir / arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    # 1. Discovery
    metadata = _read_json(paper_dir / "metadata.json")
    if not isinstance(metadata, dict) or not metadata.get("versions"):
        if metadata_cache and arxiv_id in metadata_cache:
            metadata = metadata_cache[arxiv_id]
        else:
            try:
                t_disc_start = time.perf_counter()
                if profiler:
                    with profiler.time_phase("discovery"):
                        metadata = discover_paper(arxiv_id, output_dir=output_dir)
                else:
                    metadata = discover_paper(arxiv_id, output_dir=output_dir)
                if paper_phases is not None:
                    paper_phases["discovery"] += (time.perf_counter() - t_disc_start)
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
            t_s2_start = time.perf_counter()
            if profiler:
                with profiler.time_phase("s2_references"):
                    get_references(arxiv_id, output_dir=output_dir, api_key=s2_api_key, session=session)
            else:
                get_references(arxiv_id, output_dir=output_dir, api_key=s2_api_key, session=session)
            if paper_phases is not None:
                paper_phases["s2_references"] += (time.perf_counter() - t_s2_start)
        except NotImplementedError:
            logger.warning("[%s] get_references not implemented yet by Member3. Halting paper processing.", arxiv_id)
            if error_holder is not None:
                error_holder.append("Semantic Scholar: get_references not implemented")
            return False
        except Exception as exc:
            logger.error("[%s] Error fetching references from Semantic Scholar: %s", arxiv_id, exc)
            if error_holder is not None:
                error_holder.append(f"Semantic Scholar references: {exc}")
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
            t_dl_start = time.perf_counter()
            if profiler:
                with profiler.time_phase("download"):
                    downloaded_file = download_source(
                        versioned_id=version_id,
                        dest_path=temp_archive_path,
                        session=session,
                    )
            else:
                downloaded_file = download_source(
                    versioned_id=version_id,
                    dest_path=temp_archive_path,
                    session=session,
                )
            if paper_phases is not None:
                paper_phases["download"] += (time.perf_counter() - t_dl_start)
        except NotImplementedError:
            logger.warning("[%s] download_source not implemented yet.", version_id)
            if error_holder is not None:
                error_holder.append(f"Download: download_source not implemented for {version_id}")
            return False
        except Exception as exc:
            logger.error("[%s] Failed to download %s: %s", arxiv_id, version_id, exc)
            if error_holder is not None:
                error_holder.append(f"Download {version_id}: {exc}")
            return False

        # Extract source (.tex / .bib) or handle PDF-only
        try:
            archive_size_bytes = temp_archive_path.stat().st_size if temp_archive_path.exists() else 0

            t_ext_start = time.perf_counter()
            if profiler:
                with profiler.time_phase("extract"):
                    extract_result = extract_tex_bib(
                        archive_path=downloaded_file,
                        target_dir=version_dir,
                    )
            else:
                extract_result = extract_tex_bib(
                    archive_path=downloaded_file,
                    target_dir=version_dir,
                )
            if paper_phases is not None:
                paper_phases["extract"] += (time.perf_counter() - t_ext_start)

            if extract_result == ExtractionResult.FAILED:
                logger.error("[%s] Extraction failed for version %s", arxiv_id, version_id)
                if error_holder is not None:
                    error_holder.append(f"Extraction failed for {version_id} (corrupted or unsupported format)")
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
            if error_holder is not None:
                error_holder.append(f"Extraction: extract_tex_bib not implemented for {version_id}")
            return False
        except Exception as exc:
            logger.error("[%s] Extraction exception for %s: %s", arxiv_id, version_id, exc)
            if error_holder is not None:
                error_holder.append(f"Extraction exception for {version_id}: {exc}")
            return False
        finally:
            if temp_archive_path.exists():
                try:
                    temp_archive_path.unlink()
                except OSError:
                    pass

    return is_paper_complete(paper_dir)


def run_sequential_pipeline(
    arxiv_ids: Sequence[str],
    output_dir: Path,
    resume: bool = True,
    checkpoint_file: Optional[Path] = None,
    batch_size: int = 100,
    s2_api_key: Optional[str] = None,
    profile: bool = False,
    profile_output: Optional[Path] = None,
) -> dict[str, Any]:
    """Execute the baseline sequential pipeline over target arXiv IDs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if checkpoint_file is None:
        checkpoint_file = output_dir / "checkpoint.txt"

    profiler = None
    if profile and CrawlerProfiler is not None:
        profiler = CrawlerProfiler(sample_interval=1.0, n_workers=1)
        profiler.start()

    completed_ids = load_checkpoint(checkpoint_file) if resume else set()
    failed_papers: dict[str, str] = {}
    success_count = 0
    skipped_count = 0

    pending_ids = [aid for aid in arxiv_ids if aid not in completed_ids or not is_paper_complete(output_dir / aid)]
    skipped_count = len(arxiv_ids) - len(pending_ids)

    logger.info("Total targets: %d | Completed previously: %d | Pending: %d", len(arxiv_ids), skipped_count, len(pending_ids))

    if not pending_ids:
        logger.info("All target papers are already completed.")
        if profiler:
            profiler.stop()
        return {
            "total_targets": len(arxiv_ids),
            "skipped": skipped_count,
            "succeeded": 0,
            "failed": 0,
            "failed_papers": {},
            "elapsed_seconds": 0.0,
        }

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
                    if profiler:
                        with profiler.time_phase("discovery"):
                            chunk_meta = discover_papers_batch(chunk, output_dir=output_dir)
                    else:
                        chunk_meta = discover_papers_batch(chunk, output_dir=output_dir)
                    if chunk_meta:
                        metadata_cache.update(chunk_meta)
            except NotImplementedError:
                logger.info("Batch discovery not implemented yet by Member3; will fallback to single discovery.")
        else:
            logger.info("Phase 1: Skipping remote discovery (100%% of metadata exists locally for %d papers).", len(pending_ids))

        # Phase 2: Process Download & Extraction per paper sequentially
        logger.info("Phase 2: Downloading & Extracting paper sources (Sequential Mode)...")

        for idx, arxiv_id in enumerate(pending_ids, 1):
            t_paper_start = time.perf_counter()
            cur_phases: dict[str, float] = {}
            cur_errors: list[str] = []
            try:
                success = crawl_single_paper(
                    arxiv_id=arxiv_id,
                    output_dir=output_dir,
                    temp_dir=temp_dir,
                    session=session,
                    s2_api_key=s2_api_key,
                    metadata_cache=metadata_cache,
                    profiler=profiler,
                    paper_phases=cur_phases,
                    error_holder=cur_errors,
                )
                paper_duration = time.perf_counter() - t_paper_start
                fail_reason = cur_errors[0] if (not success and cur_errors) else None

                paper_dir = output_dir / arxiv_id
                raw_bytes = 0
                ext_bytes = 0
                status_str = "SUCCESS" if success else "FAILED"
                for v_dir in paper_dir.glob("v*"):
                    st_file = v_dir / ".complete"
                    if st_file.is_file():
                        txt = st_file.read_text(encoding="utf-8").strip()
                        if "PDF_ONLY" in txt:
                            status_str = "PDF_ONLY"
                        for part in txt.split("|"):
                            if part.startswith("raw_bytes:"):
                                try:
                                    raw_bytes += int(part.split(":")[1])
                                except ValueError:
                                    pass
                            elif part.startswith("extracted_bytes:"):
                                try:
                                    ext_bytes += int(part.split(":")[1])
                                except ValueError:
                                    pass
                    if ext_bytes == 0 and status_str != "PDF_ONLY" and v_dir.is_dir():
                        ext_bytes = sum(
                            f.stat().st_size
                            for f in v_dir.iterdir()
                            if f.is_file() and f.suffix.lower() in {".tex", ".bib"}
                        )

                if profiler:
                    profiler.record_paper(
                        arxiv_id,
                        paper_duration,
                        raw_bytes,
                        ext_bytes,
                        status_str,
                        phase_times=cur_phases,
                        error=fail_reason,
                    )

                current_ram = 0.0
                if psutil:
                    try:
                        current_ram = psutil.Process().memory_info().rss / (1024 * 1024)
                    except Exception:
                        pass
                err_suffix = f" -> Reason: {fail_reason}" if fail_reason else ""
                print(
                    f"[{idx}/{len(pending_ids)}] Paper {arxiv_id} | "
                    f"Time: {paper_duration:.2f}s | "
                    f"RAM: {current_ram:.1f} MB | "
                    f"Status: {status_str}{err_suffix}",
                    flush=True,
                )

                if success:
                    mark_completed_atomic(checkpoint_file, arxiv_id)
                    completed_ids.add(arxiv_id)
                    success_count += 1
                else:
                    failed_papers[arxiv_id] = fail_reason or "Step failure (download/extraction/metadata)"
            except Exception as exc:
                logger.exception("[%s] Unexpected exception: %s", arxiv_id, exc)
                fail_reason = f"Unexpected exception: {exc}"
                failed_papers[arxiv_id] = fail_reason
                if profiler:
                    profiler.record_paper(
                        arxiv_id,
                        time.perf_counter() - t_paper_start,
                        0,
                        0,
                        "FAILED",
                        phase_times=cur_phases,
                        error=fail_reason,
                    )

            if profiler:
                with profiler.time_phase("rate_limit_sleep"):
                    time.sleep(3.0)
            else:
                time.sleep(3.0)

    finally:
        if session:
            session.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
        if profiler:
            profiler.stop()
            profiler.print_summary_table()
            report_path = profile_output or (output_dir / "profile_stats.json")
            profiler.export_json(report_path)
            logger.info("Saved benchmark profile report to: %s", report_path)

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
    logger.info("SEQUENTIAL CRAWL SUMMARY REPORT")
    logger.info("Total targets:     %d", summary["total_targets"])
    logger.info("Skipped (resume):  %d", summary["skipped"])
    logger.info("Succeeded:         %d", summary["succeeded"])
    logger.info("Failed:            %d", summary["failed"])
    logger.info("Elapsed time:      %.2f seconds", summary["elapsed_seconds"])
    logger.info("=" * 60)

    return summary


class PaperDownloadJob:
    """Encapsulates job metadata passed from Discovery Producer to Download Workers."""

    def __init__(self, arxiv_id: str, metadata: dict[str, Any]) -> None:
        self.arxiv_id = arxiv_id
        self.metadata = metadata


class PaperProcessJob:
    """Encapsulates downloaded archive references passed from Download Workers to Extract+S2 Workers."""

    def __init__(
        self,
        arxiv_id: str,
        metadata: dict[str, Any],
        archives: dict[str, Optional[Path]],
        paper_phases: dict[str, float],
        start_time: float,
        error: Optional[str] = None,
    ) -> None:
        self.arxiv_id = arxiv_id
        self.metadata = metadata
        self.archives = archives
        self.paper_phases = paper_phases
        self.start_time = start_time
        self.error = error


def run_parallel_pipeline(
    arxiv_ids: Sequence[str],
    output_dir: Path,
    resume: bool = True,
    checkpoint_file: Optional[Path] = None,
    batch_size: int = 100,
    s2_api_key: Optional[str] = None,
    profile: bool = False,
    profile_output: Optional[Path] = None,
    n_workers: int = 3,
    download_workers: Optional[int] = None,
    s2_workers: Optional[int] = None,
) -> dict[str, Any]:
    """Execute the 3-Stage Producer-Consumer Parallel Pipeline.

    Architecture:
        [ Discovery (1 Producer) ]
                    | (Queue 1: maxsize 20)
                    v
        [ Download Pool (I/O Workers: 3-5) ] (arXiv polite rate limiter: 3.0s)
                    | (Queue 2: maxsize 10)
                    v
        [ S2 References + Extract Pool (2-4 Workers) ] (Semantic Scholar rate limiter)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if checkpoint_file is None:
        checkpoint_file = output_dir / "checkpoint.txt"

    dl_workers_cnt = max(1, download_workers or n_workers)
    s2_workers_cnt = max(1, s2_workers or min(dl_workers_cnt, 4))

    # Configure S2 rate limiter interval based on API key availability
    if s2_api_key:
        s2_rate_limiter.min_interval = 1.0
    else:
        s2_rate_limiter.min_interval = 2.5

    profiler = None
    if profile and CrawlerProfiler is not None:
        profiler = CrawlerProfiler(sample_interval=1.0, n_workers=dl_workers_cnt)
        profiler.start()

    completed_ids = load_checkpoint(checkpoint_file) if resume else set()
    failed_papers: dict[str, str] = {}
    success_count = [0]
    processed_count = [0]

    pending_ids = [aid for aid in arxiv_ids if aid not in completed_ids or not is_paper_complete(output_dir / aid)]
    skipped_count = len(arxiv_ids) - len(pending_ids)

    logger.info(
        "Parallel Pipeline: Targets=%d | Skipped=%d | Pending=%d | Download Workers=%d | S2 Workers=%d",
        len(arxiv_ids),
        skipped_count,
        len(pending_ids),
        dl_workers_cnt,
        s2_workers_cnt,
    )

    if not pending_ids:
        logger.info("All target papers are already completed.")
        if profiler:
            profiler.stop()
        return {
            "total_targets": len(arxiv_ids),
            "skipped": skipped_count,
            "succeeded": 0,
            "failed": 0,
            "failed_papers": {},
            "elapsed_seconds": 0.0,
        }

    download_queue: queue.Queue[Optional[PaperDownloadJob]] = queue.Queue(maxsize=20)
    extract_s2_queue: queue.Queue[Optional[PaperProcessJob]] = queue.Queue(maxsize=10)
    temp_dir = Path(tempfile.mkdtemp(prefix="arxiv_src_", dir=output_dir))

    state_lock = threading.Lock()
    profiler_lock = threading.Lock()
    print_lock = threading.Lock()

    start_time = time.perf_counter()

    # ── Stage 1: Discovery Producer ───────────────────────────────────────────
    def discovery_producer():
        try:
            missing_meta = [
                aid for aid in pending_ids
                if not (output_dir / aid / "metadata.json").is_file()
                or not _read_json(output_dir / aid / "metadata.json")
            ]
            metadata_cache: dict[str, Any] = {}
            if missing_meta:
                logger.info("Stage 1 Discovery: Batch querying metadata for %d papers...", len(missing_meta))
                for i in range(0, len(missing_meta), batch_size):
                    chunk = missing_meta[i:i + batch_size]
                    try:
                        if profiler:
                            with profiler.time_phase("discovery"):
                                chunk_meta = discover_papers_batch(chunk, output_dir=output_dir)
                        else:
                            chunk_meta = discover_papers_batch(chunk, output_dir=output_dir)
                        if chunk_meta:
                            metadata_cache.update(chunk_meta)
                    except Exception as exc:
                        logger.warning("Batch discovery warning on chunk: %s", exc)

            for aid in pending_ids:
                paper_dir = output_dir / aid
                paper_dir.mkdir(parents=True, exist_ok=True)
                meta = _read_json(paper_dir / "metadata.json") or metadata_cache.get(aid)
                if not meta or not meta.get("versions"):
                    try:
                        if profiler:
                            with profiler.time_phase("discovery"):
                                meta = discover_paper(aid, output_dir=output_dir)
                        else:
                            meta = discover_paper(aid, output_dir=output_dir)
                    except Exception:
                        meta = {
                            "arxiv_id": aid,
                            "title": "",
                            "authors": [],
                            "versions": [f"{aid}v1"],
                        }
                        with open(paper_dir / "metadata.json", "w", encoding="utf-8") as f:
                            json.dump(meta, f, indent=2)

                download_queue.put(PaperDownloadJob(arxiv_id=aid, metadata=meta))

        except Exception as exc:
            logger.exception("Stage 1 Discovery Producer exception: %s", exc)
        finally:
            for _ in range(dl_workers_cnt):
                download_queue.put(None)

    # ── Stage 2: Download Workers ─────────────────────────────────────────────
    def download_worker_loop(worker_id: int):
        session = requests.Session() if requests else None
        try:
            while True:
                job = download_queue.get()
                if job is None:
                    download_queue.task_done()
                    break

                arxiv_id = job.arxiv_id
                metadata = job.metadata
                paper_dir = output_dir / arxiv_id
                versions = metadata.get("versions", [f"{arxiv_id}v1"])
                archives: dict[str, Optional[Path]] = {}
                paper_phases: dict[str, float] = {
                    "discovery": 0.0,
                    "download": 0.0,
                    "extract": 0.0,
                    "s2_references": 0.0,
                    "rate_limit_sleep": 0.0,
                }
                error = None
                t_paper_start = time.perf_counter()

                for version_id in versions:
                    v_suffix = f"v{version_id.split('v')[-1]}" if "v" in version_id else "v1"
                    version_dir = paper_dir / v_suffix
                    if is_version_completed(version_dir):
                        continue

                    temp_archive_path = temp_dir / f"{version_id}.archive"
                    try:
                        t_dl_start = time.perf_counter()
                        if profiler:
                            with profiler.time_phase("download"):
                                dl_path = download_source(
                                    versioned_id=version_id,
                                    dest_path=temp_archive_path,
                                    session=session,
                                )
                        else:
                            dl_path = download_source(
                                versioned_id=version_id,
                                dest_path=temp_archive_path,
                                session=session,
                            )
                        paper_phases["download"] += (time.perf_counter() - t_dl_start)
                        archives[version_id] = dl_path
                    except Exception as exc:
                        error = f"Download {version_id}: {exc}"
                        logger.error("[%s] %s", arxiv_id, error)
                        break

                proc_job = PaperProcessJob(
                    arxiv_id=arxiv_id,
                    metadata=metadata,
                    archives=archives,
                    paper_phases=paper_phases,
                    start_time=t_paper_start,
                    error=error,
                )
                extract_s2_queue.put(proc_job)
                download_queue.task_done()
        except Exception as exc:
            logger.exception("DownloadWorker-%d fatal error: %s", worker_id, exc)
        finally:
            if session:
                session.close()

    # ── Stage 3: Extract + S2 Workers ─────────────────────────────────────────
    def extract_s2_worker_loop(worker_id: int):
        session = requests.Session() if requests else None
        try:
            while True:
                job = extract_s2_queue.get()
                if job is None:
                    extract_s2_queue.task_done()
                    break

                arxiv_id = job.arxiv_id
                metadata = job.metadata
                paper_dir = output_dir / arxiv_id
                paper_phases = job.paper_phases
                error = job.error
                success = (error is None)

                # 1. Extraction (only if download succeeded)
                if success:
                    versions = metadata.get("versions", [f"{arxiv_id}v1"])
                    for version_id in versions:
                        v_suffix = f"v{version_id.split('v')[-1]}" if "v" in version_id else "v1"
                        version_dir = paper_dir / v_suffix
                        if is_version_completed(version_dir):
                            continue

                        archive_file = job.archives.get(version_id)
                        if archive_file is None:
                            # 404 indicates PDF-only submission
                            mark_version_completed(version_dir, status="PDF_ONLY|raw_bytes:0|extracted_bytes:0")
                            continue

                        archive_size_bytes = archive_file.stat().st_size if archive_file.exists() else 0
                        try:
                            t_ext_start = time.perf_counter()
                            if profiler:
                                with profiler.time_phase("extract"):
                                    extract_result = extract_tex_bib(
                                        archive_path=archive_file,
                                        target_dir=version_dir,
                                    )
                            else:
                                extract_result = extract_tex_bib(
                                    archive_path=archive_file,
                                    target_dir=version_dir,
                                )
                            paper_phases["extract"] += (time.perf_counter() - t_ext_start)

                            if extract_result == ExtractionResult.FAILED:
                                success = False
                                error = f"Extraction failed for {version_id} (corrupted or unsupported format)"
                                break

                            extracted_size_bytes = sum(
                                f.stat().st_size
                                for f in version_dir.iterdir()
                                if f.is_file() and f.suffix.lower() in {".tex", ".bib"}
                            )
                            status_payload = f"{extract_result.value}|raw_bytes:{archive_size_bytes}|extracted_bytes:{extracted_size_bytes}"
                            mark_version_completed(version_dir, status=status_payload)
                        except Exception as exc:
                            success = False
                            error = f"Extraction exception for {version_id}: {exc}"
                            break
                        finally:
                            if archive_file.exists():
                                try:
                                    archive_file.unlink(missing_ok=True)
                                except OSError:
                                    pass

                # 2. S2 References (only if extraction didn't fail)
                if success:
                    refs_exist = isinstance(_read_json(paper_dir / "references.json"), list)
                    if not refs_exist:
                        try:
                            t_s2_start = time.perf_counter()
                            if profiler:
                                with profiler.time_phase("s2_references"):
                                    get_references(arxiv_id, output_dir=output_dir, api_key=s2_api_key, session=session)
                            else:
                                get_references(arxiv_id, output_dir=output_dir, api_key=s2_api_key, session=session)
                            paper_phases["s2_references"] += (time.perf_counter() - t_s2_start)
                        except Exception as exc:
                            success = False
                            error = f"Semantic Scholar references: {exc}"

                # 3. Finalize paper status & stats
                paper_duration = time.perf_counter() - job.start_time
                raw_bytes = 0
                ext_bytes = 0
                status_str = "SUCCESS" if (success and not error) else "FAILED"

                for v_dir in paper_dir.glob("v*"):
                    st_file = v_dir / ".complete"
                    if st_file.is_file():
                        txt = st_file.read_text(encoding="utf-8").strip()
                        if "PDF_ONLY" in txt and status_str != "FAILED":
                            status_str = "PDF_ONLY"
                        for part in txt.split("|"):
                            if part.startswith("raw_bytes:"):
                                try:
                                    raw_bytes += int(part.split(":")[1])
                                except ValueError:
                                    pass
                            elif part.startswith("extracted_bytes:"):
                                try:
                                    ext_bytes += int(part.split(":")[1])
                                except ValueError:
                                    pass
                    if ext_bytes == 0 and status_str != "PDF_ONLY" and v_dir.is_dir():
                        ext_bytes = sum(
                            f.stat().st_size
                            for f in v_dir.iterdir()
                            if f.is_file() and f.suffix.lower() in {".tex", ".bib"}
                        )

                with state_lock:
                    processed_count[0] += 1
                    curr_idx = processed_count[0]
                    if success and not error:
                        mark_completed_atomic(checkpoint_file, arxiv_id)
                        completed_ids.add(arxiv_id)
                        success_count[0] += 1
                    else:
                        failed_papers[arxiv_id] = error or "Step failure"

                if profiler:
                    with profiler_lock:
                        profiler.record_paper(
                            arxiv_id,
                            paper_duration,
                            raw_bytes,
                            ext_bytes,
                            status_str,
                            phase_times=paper_phases,
                            error=error,
                        )

                current_ram = 0.0
                if psutil:
                    try:
                        current_ram = psutil.Process().memory_info().rss / (1024 * 1024)
                    except Exception:
                        pass

                err_suffix = f" -> Reason: {error}" if error else ""
                with print_lock:
                    print(
                        f"[{curr_idx}/{len(pending_ids)}] Paper {arxiv_id} | "
                        f"Time: {paper_duration:.2f}s | "
                        f"RAM: {current_ram:.1f} MB | "
                        f"Status: {status_str}{err_suffix}",
                        flush=True,
                    )

                extract_s2_queue.task_done()
        except Exception as exc:
            logger.exception("S2Worker-%d fatal error: %s", worker_id, exc)
        finally:
            if session:
                session.close()

    # ── Launch Threads ────────────────────────────────────────────────────────
    dl_threads = []
    s2_threads = []

    producer_thread = threading.Thread(target=discovery_producer, name="DiscoveryProducer")
    producer_thread.start()

    for i in range(dl_workers_cnt):
        t = threading.Thread(target=download_worker_loop, args=(i + 1,), name=f"DownloadWorker-{i+1}")
        t.start()
        dl_threads.append(t)

    for i in range(s2_workers_cnt):
        t = threading.Thread(target=extract_s2_worker_loop, args=(i + 1,), name=f"S2Worker-{i+1}")
        t.start()
        s2_threads.append(t)

    try:
        producer_thread.join()
        for t in dl_threads:
            t.join()

        # Send sentinels to Stage 3 workers
        for _ in range(s2_workers_cnt):
            extract_s2_queue.put(None)

        for t in s2_threads:
            t.join()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if profiler:
            profiler.stop()
            profiler.print_summary_table()
            report_path = profile_output or (output_dir / "profile_stats.json")
            profiler.export_json(report_path)
            logger.info("Saved benchmark profile report to: %s", report_path)

    elapsed = time.perf_counter() - start_time
    summary = {
        "total_targets": len(arxiv_ids),
        "skipped": skipped_count,
        "succeeded": success_count[0],
        "failed": len(failed_papers),
        "failed_papers": failed_papers,
        "elapsed_seconds": round(elapsed, 2),
    }

    logger.info("=" * 60)
    logger.info("PARALLEL CRAWL SUMMARY REPORT")
    logger.info("Total targets:     %d", summary["total_targets"])
    logger.info("Skipped (resume):  %d", summary["skipped"])
    logger.info("Succeeded:         %d", summary["succeeded"])
    logger.info("Failed:            %d", summary["failed"])
    logger.info("Elapsed time:      %.2f seconds", summary["elapsed_seconds"])
    logger.info("=" * 60)

    return summary


def run_pipeline(
    arxiv_ids: Sequence[str],
    output_dir: Path,
    resume: bool = True,
    checkpoint_file: Optional[Path] = None,
    batch_size: int = 100,
    s2_api_key: Optional[str] = None,
    profile: bool = False,
    profile_output: Optional[Path] = None,
    n_workers: int = 1,
    download_workers: Optional[int] = None,
    s2_workers: Optional[int] = None,
) -> dict[str, Any]:
    """Execute the pipeline over target arXiv IDs, routing to sequential or parallel engine."""
    effective_workers = download_workers or n_workers
    if effective_workers > 1:
        return run_parallel_pipeline(
            arxiv_ids=arxiv_ids,
            output_dir=output_dir,
            resume=resume,
            checkpoint_file=checkpoint_file,
            batch_size=batch_size,
            s2_api_key=s2_api_key,
            profile=profile,
            profile_output=profile_output,
            n_workers=n_workers,
            download_workers=download_workers,
            s2_workers=s2_workers,
        )
    else:
        return run_sequential_pipeline(
            arxiv_ids=arxiv_ids,
            output_dir=output_dir,
            resume=resume,
            checkpoint_file=checkpoint_file,
            batch_size=batch_size,
            s2_api_key=s2_api_key,
            profile=profile,
            profile_output=profile_output,
        )


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for the crawler runner."""
    parser = argparse.ArgumentParser(
        description="arXiv Data Science Crawler - Milestone 1",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--month", type=str, default=None, help="4-digit month code (e.g. '2505')")
    parser.add_argument("--start", type=str, required=True, help="Starting sequence ID or full arXiv ID (e.g. 10666 or 2506.05788)")
    parser.add_argument("--end", type=str, required=True, help="Ending sequence ID or full arXiv ID (e.g. 15665 or 2506.05837)")
    parser.add_argument("--end-month", type=str, default=None, help="End month for cross-month range (e.g. '2504')")
    parser.add_argument("--end-month-start", type=int, default=1, help="Starting sequence ID of the end month (default: 1)")
    parser.add_argument("--start-month-max", type=int, default=None, help="Verified max ID of start month for cross-month ranges")
    parser.add_argument("--output", "--output-dir", dest="output", type=Path, default=Path("./data"), help="Output directory")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for discovery API queries")
    parser.add_argument("--s2-api-key", type=str, default=None, help="Optional Semantic Scholar API Key")
    parser.add_argument("--no-resume", action="store_true", help="Disable checkpoint resumption")
    parser.add_argument("--profile", action="store_true", help="Monitor RAM consumption periodically via psutil for Colab benchmark")
    parser.add_argument("--profile-output", "--stats-file", dest="profile_output", type=Path, default=None, help="Optional output JSON path for benchmark profile report")
    parser.add_argument("--log-file", type=Path, default=None, help="Optional log file path")
    parser.add_argument("--n-workers", type=int, default=1, help="Number of download worker threads (default: 1 for sequential)")
    parser.add_argument("--download-workers", type=int, default=None, help="Explicit number of download workers (overrides --n-workers)")
    parser.add_argument("--s2-workers", type=int, default=None, help="Explicit number of S2 reference workers (default: min(n_workers, 4))")
    parser.add_argument("--parallel", action="store_true", help="Enable parallel mode (equivalent to --n-workers 3 if not set)")
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

    if args.parallel and args.n_workers <= 1:
        args.n_workers = 3

    if args.profile_output is not None:
        args.profile = True

    start_str = str(args.start).strip()
    end_str = str(args.end).strip()
    month = args.month

    try:
        if "." in start_str:
            month_part, seq_part = start_str.split(".", 1)
            if not month:
                month = month_part
            start_seq = int(seq_part)
        else:
            start_seq = int(start_str)

        if "." in end_str:
            end_seq = int(end_str.split(".", 1)[1])
        else:
            end_seq = int(end_str)

        if args.end_month:
            if not month:
                logger.error("--month is required when using --end-month")
                return 1
            ids_to_crawl = generate_cross_month_ids(
                start_month=month,
                start_id=start_seq,
                end_month=args.end_month,
                end_id=end_seq,
                start_month_max=args.start_month_max,
                end_month_start=args.end_month_start,
            )
        else:
            if not month:
                logger.error("--month is required for single-month range")
                return 1
            ids_to_crawl = generate_arxiv_ids(month, start_seq, end_seq)
    except ValueError as err:
        logger.error("Invalid range configuration: %s", err)
        return 1

    summary = run_pipeline(
        arxiv_ids=ids_to_crawl,
        output_dir=args.output,
        resume=not args.no_resume,
        batch_size=args.batch_size,
        s2_api_key=args.s2_api_key,
        profile=args.profile,
        profile_output=args.profile_output,
        n_workers=args.n_workers,
        download_workers=args.download_workers,
        s2_workers=args.s2_workers,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
