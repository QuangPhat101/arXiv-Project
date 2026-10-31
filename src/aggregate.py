"""Data Aggregator Module: Combine, Deduplicate, and Export Dataset Tables.

Assigned to: Bảo (Member 3)
Purpose:
    Aggregate crawled paper folders from multiple members into the two canonical
    dataset tables specified by Milestone 1 requirements:
        1. 'papers':
           - arxiv_id (str, non-null): Base arXiv ID
           - title (str): Paper title
           - authors (list[str]): List of author names
           - submission_date (str): ISO timestamp of first submission
           - revised_dates (list[str]): List of revision ISO timestamps
           - venue (str, nullable): Publication venue / journal_ref
        2. 'references':
           - arxiv_id (str, non-null): Base ID of citing paper
           - ref_arxiv_id (str, non-null): arXiv ID of cited paper
           - ref_title (str): Title of cited paper
           - ref_authors (list[str]): List of cited author names
           - ref_submission_date (str): Year or date of citation
           - ref_s2_id (str): Semantic Scholar paperId
    Also calculates crawl integrity metrics and summary statistics for statistics.ipynb.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Sequence

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("data_aggregator")


def _read_json(path: Path) -> Any:
    """Read JSON file safely, returning None on failure."""
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Corrupt JSON at %s: %s", path, exc)
        return None


def collect_paper_dirs(data_dirs: Sequence[Path | str]) -> dict[str, Path]:
    """Discover all valid paper folders across multiple member data directories.
    
    If an arXiv ID exists in multiple directories, keeps the one with valid metadata
    and references, eliminating duplicates.

    Args:
        data_dirs: Sequence of root data directories (e.g. ['./data', '../data_khanh/data']).

    Returns:
        dict[str, Path]: Mapping from canonical arxiv_id to its folder Path.
    """
    discovered: dict[str, Path] = {}

    for d in data_dirs:
        dir_path = Path(d).resolve()
        if not dir_path.is_dir():
            logger.warning("Directory not found or inaccessible: %s", dir_path)
            continue

        logger.info("Scanning directory: %s", dir_path)
        count = 0
        for item in dir_path.iterdir():
            if item.is_dir() and (item / "metadata.json").is_file():
                arxiv_id = item.name
                if arxiv_id not in discovered:
                    discovered[arxiv_id] = item
                    count += 1
                else:
                    # Deduplication: already discovered from an earlier directory
                    logger.debug("Duplicate paper %s found in %s, keeping existing.", arxiv_id, dir_path)
        logger.info("Found %d valid paper folders in %s", count, dir_path)

    logger.info("Total unique papers discovered across all sources: %d", len(discovered))
    return discovered


def aggregate_dataset(
    paper_dirs: dict[str, Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Aggregate paper records and reference rows from all paper folders.

    Returns:
        tuple containing:
            - papers_rows: list of dicts for 'papers' table
            - references_rows: list of dicts for 'references' table (only with non-null ref_arxiv_id)
            - stats: dictionary of crawl and dataset statistics
    """
    papers_rows: list[dict[str, Any]] = []
    references_rows: list[dict[str, Any]] = []

    # Detailed statistics counters
    stats: dict[str, Any] = {
        "total_papers": len(paper_dirs),
        "total_versions": 0,
        "total_tex_versions": 0,
        "total_pdf_only_versions": 0,
        "version_distribution": {},
        "total_raw_references": 0,
        "total_arxiv_references": 0,
        "papers_without_references": 0,
        "papers_with_arxiv_references": 0,
        "total_tex_bib_bytes": 0,
    }

    seen_refs: set[tuple[str, str]] = set()

    for arxiv_id, p_dir in paper_dirs.items():
        meta = _read_json(p_dir / "metadata.json")
        if not meta or not isinstance(meta, dict):
            logger.warning("Skipping paper %s due to missing or invalid metadata.json", arxiv_id)
            continue

        base_id = meta.get("arxiv_id", arxiv_id)
        title = meta.get("title", "")
        authors = meta.get("authors", [])
        sub_date = meta.get("submission_date")
        rev_dates = meta.get("revised_dates", [])
        venue = meta.get("venue")
        versions = meta.get("versions", [])

        # 1. Append to papers table
        papers_rows.append({
            "arxiv_id": str(base_id),
            "title": str(title),
            "authors": list(authors) if isinstance(authors, list) else [],
            "submission_date": str(sub_date) if sub_date else None,
            "revised_dates": list(rev_dates) if isinstance(rev_dates, list) else [],
            "venue": str(venue) if venue else None,
        })

        # Version statistics
        v_count = len(versions) if versions else 1
        stats["total_versions"] += v_count
        stats["version_distribution"][v_count] = stats["version_distribution"].get(v_count, 0) + 1

        # Check version directories for PDF_ONLY vs SUCCESS
        for v_dir in p_dir.glob("v*"):
            if v_dir.is_dir():
                complete_file = v_dir / ".complete"
                if complete_file.is_file():
                    content = complete_file.read_text(encoding="utf-8", errors="ignore")
                    if "PDF_ONLY" in content:
                        stats["total_pdf_only_versions"] += 1
                    elif "SUCCESS" in content:
                        stats["total_tex_versions"] += 1
                for f in v_dir.iterdir():
                    if f.is_file() and f.suffix in (".tex", ".bib"):
                        stats["total_tex_bib_bytes"] += f.stat().st_size

        # 2. Process references
        refs_data = _read_json(p_dir / "references.json")
        if not refs_data or not isinstance(refs_data, list) or len(refs_data) == 0:
            stats["papers_without_references"] += 1
            continue

        stats["total_raw_references"] += len(refs_data)
        paper_has_arxiv_ref = False

        for r in refs_data:
            if not isinstance(r, dict):
                continue
            ref_arxiv_id = r.get("ref_arxiv_id")

            # REQUIREMENT: Only keep rows where ref_arxiv_id is not null/empty
            if not ref_arxiv_id:
                continue

            ref_key = (base_id, str(ref_arxiv_id))
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)

            paper_has_arxiv_ref = True
            references_rows.append({
                "arxiv_id": str(base_id),
                "ref_arxiv_id": str(ref_arxiv_id),
                "ref_title": str(r.get("ref_title") or ""),
                "ref_authors": list(r.get("ref_authors") or []) if isinstance(r.get("ref_authors"), list) else [],
                "ref_submission_date": str(r.get("ref_submission_date") or ""),
                "ref_s2_id": str(r.get("ref_s2_id") or ""),
            })

        if paper_has_arxiv_ref:
            stats["papers_with_arxiv_references"] += 1

    stats["total_arxiv_references"] = len(references_rows)
    return papers_rows, references_rows, stats


def export_tables(
    papers_rows: list[dict[str, Any]],
    references_rows: list[dict[str, Any]],
    stats: dict[str, Any],
    output_dir: Path | str,
    export_format: str = "both",
) -> None:
    """Export aggregated tables to CSV and/or Parquet, and save stats JSON.

    Args:
        papers_rows: Rows for papers table.
        references_rows: Rows for references table.
        stats: Aggregated statistics dict.
        output_dir: Directory to save exported files.
        export_format: 'csv', 'parquet', or 'both'.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. Save stats JSON
    stats_file = out_path / "crawl_statistics.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    logger.info("Saved statistics to %s", stats_file)

    if pd is None:
        logger.warning("Pandas is not installed. Exporting tables as JSON Lines instead.")
        with open(out_path / "papers.jsonl", "w", encoding="utf-8") as f:
            for r in papers_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(out_path / "references.jsonl", "w", encoding="utf-8") as f:
            for r in references_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return

    df_papers = pd.DataFrame(papers_rows)
    df_refs = pd.DataFrame(references_rows)

    if export_format in ("csv", "both"):
        csv_papers = out_path / "papers.csv"
        csv_refs = out_path / "references.csv"
        # Export authors lists as json strings for CSV compatibility
        df_papers_csv = df_papers.copy()
        if "authors" in df_papers_csv.columns:
            df_papers_csv["authors"] = df_papers_csv["authors"].apply(json.dumps)
        if "revised_dates" in df_papers_csv.columns:
            df_papers_csv["revised_dates"] = df_papers_csv["revised_dates"].apply(json.dumps)
        df_papers_csv.to_csv(csv_papers, index=False, encoding="utf-8")

        df_refs_csv = df_refs.copy()
        if "ref_authors" in df_refs_csv.columns:
            df_refs_csv["ref_authors"] = df_refs_csv["ref_authors"].apply(json.dumps)
        df_refs_csv.to_csv(csv_refs, index=False, encoding="utf-8")
        logger.info("Exported CSV tables: %s (%d rows), %s (%d rows)", csv_papers.name, len(df_papers), csv_refs.name, len(df_refs))

    if export_format in ("parquet", "both"):
        try:
            pq_papers = out_path / "papers.parquet"
            pq_refs = out_path / "references.parquet"
            df_papers.to_parquet(pq_papers, index=False)
            df_refs.to_parquet(pq_refs, index=False)
            logger.info("Exported Parquet tables: %s, %s", pq_papers.name, pq_refs.name)
        except Exception as exc:
            logger.warning("Could not export Parquet (pyarrow/fastparquet might be missing): %s", exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate dataset from multiple crawled data directories.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dirs",
        nargs="+",
        required=True,
        help="List of paths to data directories to aggregate (e.g. ./data ../data_khanh/data)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./data/aggregated"),
        help="Directory to save aggregated tables and crawl_statistics.json",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "parquet", "both"],
        default="both",
        help="Output export format",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logger.info("Starting dataset aggregation...")
    paper_dirs = collect_paper_dirs(args.data_dirs)
    if not paper_dirs:
        logger.error("No valid paper folders found in specified directories.")
        return 1

    papers_rows, references_rows, stats = aggregate_dataset(paper_dirs)
    logger.info("Aggregated %d papers and %d arXiv references.", len(papers_rows), len(references_rows))

    export_tables(papers_rows, references_rows, stats, args.output_dir, export_format=args.format)
    logger.info("Aggregation completed successfully!")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

