"""Parse and export the five working tables for Milestones 1 and 2.

Assigned to: Bảo
Usage:
    python src/run_m2_pipeline.py --data-dir data --output-dir export_m2 --workers 4
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.parser import parse_version
from src.bibtex_parser import build_cross_version_citation_map, parse_version_bibtex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("m2_pipeline")


def process_single_paper(paper_dir_str: str) -> Dict[str, Any]:
    """Parse a single paper directory for metadata, references, elements, hierarchy, and bibtex."""
    p_dir = Path(paper_dir_str)
    aid = p_dir.name

    errors: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []

    paper_meta = None
    meta_path = p_dir / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            paper_meta = {
                "arxiv_id": str(meta.get("arxiv_id", aid)),
                "title": str(meta.get("title", "")),
                "authors": list(meta.get("authors", [])),
                "submission_date": str(meta.get("submission_date", "")),
                "revised_dates": list(meta.get("revised_dates", [])),
                "venue": meta.get("venue") or None,
            }
        except Exception as e:
            errors.append({
                "arxiv_id": str(aid),
                "version": 0,
                "stage": "metadata",
                "message": str(e),
            })

    paper_refs = []
    ref_path = p_dir / "references.json"
    if ref_path.exists():
        try:
            with open(ref_path, "r", encoding="utf-8") as f:
                refs = json.load(f)
            for r in refs:
                ref_aid = r.get("ref_arxiv_id")
                if ref_aid and str(ref_aid).strip() and str(ref_aid).strip().lower() != "none":
                    paper_refs.append({
                        "arxiv_id": str(aid),
                        "ref_arxiv_id": str(ref_aid).strip(),
                        "ref_title": str(r.get("ref_title", "")),
                        "ref_authors": list(r.get("ref_authors", [])),
                        "ref_submission_date": str(r.get("ref_submission_date", "")) or None,
                        "ref_s2_id": str(r.get("ref_s2_id", "")) or None,
                    })
        except Exception as e:
            errors.append({
                "arxiv_id": str(aid),
                "version": 0,
                "stage": "references",
                "message": str(e),
            })

    elements_list = []
    hierarchy_list = []
    entries_by_version = {}

    v_dirs = sorted([v for v in p_dir.iterdir() if v.is_dir() and v.name.startswith("v")],
                    key=lambda x: int(x.name[1:]) if x.name[1:].isdigit() else 0)

    if not v_dirs:
        coverage.append({
            "arxiv_id": str(aid),
            "version": 1,
            "status": "empty",
        })

    # 1. Collect BibTeX entries across all versions
    for v_dir in v_dirs:
        v_num = int(v_dir.name[1:]) if v_dir.name[1:].isdigit() else 1
        try:
            v_bib = parse_version_bibtex(v_dir, aid)
            if v_bib:
                entries_by_version[v_num] = v_bib
        except Exception as e:
            errors.append({
                "arxiv_id": str(aid),
                "version": v_num,
                "stage": "parse_version_bibtex",
                "message": str(e),
            })

    # 2. Build cross-version citation map and union fields of duplicate entries
    bibtex_list = []
    key_map = {}
    if entries_by_version:
        key_map = build_cross_version_citation_map(entries_by_version)
        merged_entries: Dict[str, Dict[str, Any]] = {}
        for v_num, entries in sorted(entries_by_version.items()):
            for e in entries:
                orig_key = e["citation_key"]
                canon_key = key_map.get((v_num, orig_key), orig_key)
                if canon_key not in merged_entries:
                    e_copy = dict(e)
                    e_copy["citation_key"] = canon_key
                    merged_entries[canon_key] = e_copy
                else:
                    target = merged_entries[canon_key]
                    for k, val in e.items():
                        if k == "citation_key":
                            continue
                        if val is not None and (target.get(k) is None or target.get(k) == ""):
                            target[k] = val
        bibtex_list = list(merged_entries.values())

    # 3. Parse LaTeX versions passing version-specific cite_map
    for v_dir in v_dirs:
        v_num = int(v_dir.name[1:]) if v_dir.name[1:].isdigit() else 1
        v_cite_map = {
            orig_k: canon_k
            for (v, orig_k), canon_k in key_map.items()
            if v == v_num
        }

        tex_files = list(v_dir.glob("*.tex"))
        if not tex_files:
            coverage.append({
                "arxiv_id": str(aid),
                "version": v_num,
                "status": "empty",
            })
            continue

        try:
            el_list, hi_list = parse_version(v_dir, aid, v_num, cite_map=v_cite_map)
            elements_list.extend(el_list)
            hierarchy_list.extend(hi_list)
            coverage.append({
                "arxiv_id": str(aid),
                "version": v_num,
                "status": "parsed",
                "elements_count": len(el_list),
            })
        except Exception as e:
            errors.append({
                "arxiv_id": str(aid),
                "version": v_num,
                "stage": "parse_version",
                "message": str(e),
            })
            coverage.append({
                "arxiv_id": str(aid),
                "version": v_num,
                "status": "error",
            })

    return {
        "paper_meta": paper_meta,
        "references": paper_refs,
        "elements": elements_list,
        "hierarchy": hierarchy_list,
        "bibtex": bibtex_list,
        "errors": errors,
        "coverage": coverage,
    }


def run_pipeline(data_dir: Path, output_dir: Path, workers: int = 4, sample_n: Optional[int] = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_paper_dirs = sorted([
        str(d) for d in data_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in ["aggregated", "temp_fix_dl", "export_bao"]
    ])

    if sample_n:
        all_paper_dirs = all_paper_dirs[:sample_n]

    logger.info("Found %d paper directories to process using %d worker processes.", len(all_paper_dirs), workers)

    papers_rows = []
    references_rows = []
    elements_dict = {}
    hierarchy_rows = []
    bibtex_rows = []

    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_paper, p_str): p_str for p_str in all_paper_dirs}
        for fut in as_completed(futures):
            completed += 1
            if completed % 500 == 0 or completed == len(all_paper_dirs):
                logger.info("Processed [%d/%d] papers (%.1f%%)...", completed, len(all_paper_dirs), 100.0 * completed / len(all_paper_dirs))
            
            res = fut.result()
            if res["paper_meta"]:
                papers_rows.append(res["paper_meta"])
            
            references_rows.extend(res["references"])
            
            for el in res["elements"]:
                eid = el[0]
                if eid not in elements_dict:
                    elements_dict[eid] = el
            
            hierarchy_rows.extend(res["hierarchy"])
            bibtex_rows.extend(res["bibtex"])

    logger.info("Content and citation extraction completed!")
    logger.info("  Total papers: %d", len(papers_rows))
    logger.info("  Total references: %d", len(references_rows))
    logger.info("  Total elements: %d", len(elements_dict))
    logger.info("  Total hierarchy edges: %d", len(hierarchy_rows))
    logger.info("  Total bibtex entries: %d", len(bibtex_rows))

    # Export Parquet tables
    logger.info("Writing five Parquet tables to: %s", output_dir)
    pd.DataFrame(papers_rows).to_parquet(output_dir / "papers.parquet", index=False)
    pd.DataFrame(references_rows).to_parquet(output_dir / "references.parquet", index=False)
    pd.DataFrame(list(elements_dict.values()), columns=["element_id", "arxiv_id", "kind", "content"]).to_parquet(output_dir / "elements.parquet", index=False)
    pd.DataFrame(hierarchy_rows, columns=["arxiv_id", "version", "element_id", "parent_id"]).to_parquet(output_dir / "hierarchy.parquet", index=False)
    pd.DataFrame(bibtex_rows).to_parquet(output_dir / "bibtex.parquet", index=False)

    logger.info("Five Parquet tables written to: %s", output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Directory containing paper directories")
    parser.add_argument("--output-dir", type=Path, default=Path("export_m2"), help="Output directory for Parquet tables")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent worker processes")
    parser.add_argument("--sample-n", type=int, default=None, help="Process only the first N papers for test")
    args = parser.parse_args()

    run_pipeline(data_dir=args.data_dir, output_dir=args.output_dir, workers=args.workers, sample_n=args.sample_n)
